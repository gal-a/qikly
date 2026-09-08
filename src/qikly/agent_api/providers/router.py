"""
Every call mode (fix, patch, test_integration, test_system, test_unit) is
routed to a single LLM provider, chosen via the LLM_PROVIDER environment
variable (default: gemini) -- see README's "LLM provider" section. Mixed
per-mode routing to different providers isn't supported yet; `mode` is
used by route_model() to pick that agent's provider and model.
"""
import importlib
import contextlib
import os
import socket

from qikly.agent_api.providers import keys

DEFAULT_PROVIDER = "gemini"

# provider name -> (module, function name, extra required env vars beyond API_KEY)
_PROVIDERS = {
    "gemini": ("qikly.agent_api.providers.gemini", "call_gemini", []),
    "openai": ("qikly.agent_api.providers.openai", "call_openai", []),
    "anthropic": ("qikly.agent_api.providers.anthropic", "call_anthropic", []),
}

# provider name -> that provider's own conventional key variable(s), accepted
# as fallbacks for API_KEY and checked in this order.
#
# A machine that already talks to Gemini has GEMINI_API_KEY exported, not
# API_KEY. Accepting only the generic name meant a first run failed for
# exactly the users who were already set up, turning "pip install and run"
# into "read the README first". Whichever one is set is normalised into
# API_KEY below, so every provider module still reads one variable.
_KEY_VARS = {
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
}


def accepted_key_vars(provider):
    """Every environment variable this provider will take a key from."""
    return ["API_KEY", *_KEY_VARS.get(provider, [])]


def _ensure_api_key(provider):
    """
    Normalise whichever accepted variable is set into API_KEY. Returns True
    if a key is now available. Idempotent, and never overwrites an API_KEY
    that is already set.

    Refuses a value that cannot be a key. A stray quote or a leading space
    survives a paste silently and is only reported by the provider, one model
    call later, as an unauthenticated request. Failing here costs nothing and
    names the variable at fault. Only characters no provider's key ever
    contains are refused; length and prefix are left alone, because those
    change and a wrong refusal is worse than a late one.
    """
    if os.environ.get("API_KEY"):
        _reject_unusable("API_KEY", os.environ["API_KEY"])
        keys.remember_source("API_KEY")
        return True
    for var in _KEY_VARS.get(provider, []):
        value = os.environ.get(var)
        if value:
            _reject_unusable(var, value)
            os.environ["API_KEY"] = value
            keys.remember_source(var)
            return True
    return False


def _reject_unusable(var, value):
    problem = keys.defect(value)
    if problem:
        raise RuntimeError(
            f"{var} {problem}, so it cannot be a valid API key "
            f"({len(value)} characters). Fix that variable and run again. "
            f"No model call was made."
        )


# Substrings that mean "the name never resolved", across platforms and SDKs.
_DNS_HINTS = (
    "getaddrinfo", "name or service not known", "nodename nor servname",
    "temporary failure in name resolution", "no address associated",
)


def _causes(exc):
    """The exception and everything it was raised from, innermost last."""
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    return chain


def _explain_call_failure(exc, provider):
    """
    Turn a transport-level exception into one actionable sentence.

    Provider SDKs raise through several layers (httpx over httpcore over
    socket, wrapped again by a retry library), so an unhandled network
    failure reaches the user as sixty lines of traceback whose only real
    content is "getaddrinfo failed" on the twelfth line. The provider
    modules already convert API-level errors into clean messages; this does
    the same for the layer beneath them, in one place, for every provider.
    """
    chain = _causes(exc)
    blob = " ".join(str(c) for c in chain).lower()
    names = " ".join(type(c).__name__.lower() for c in chain)

    if isinstance(exc, socket.gaierror) or any(h in blob for h in _DNS_HINTS):
        return (f"Cannot reach the {provider} API server: the hostname did not "
                f"resolve. Check your internet connection, DNS, VPN or proxy.")
    if "timeout" in names or "timed out" in blob:
        return (f"Timed out reaching the {provider} API server. Check your "
                f"connection, or retry if the provider is briefly degraded.")
    if any(isinstance(c, (ConnectionError, OSError)) for c in chain) or "connect" in names:
        return (f"Cannot reach the {provider} API server: the connection failed "
                f"({type(exc).__name__}). Check your internet connection, VPN or proxy.")
    return f"The {provider} call failed ({type(exc).__name__}): {exc}"


def _inferred_provider():
    """
    The provider to use when LLM_PROVIDER is unset and the default cannot work.

    Gemini is the default for good reasons: it is the only one with a free tier
    that needs no card, it is roughly twenty times cheaper than the
    alternatives, its SDK is the one hard dependency, and every published
    convergence figure was measured on it. None of that helps someone whose
    only key is OPENAI_API_KEY, who currently gets told to go and get a
    different key from a different company before they can see the tool run.

    So the default stays, and stops being unconditional. This fires only when
    all three are true: no explicit choice, no key the default could use, and
    exactly one other provider configured. It never overrides a choice, never
    changes behaviour for anyone who has a Gemini key, and never guesses
    between two candidates. In every other case the caller reports the missing
    key as before.
    """
    if os.environ.get("API_KEY"):
        return None  # generic key: it belongs to the default, whatever it is
    if any(os.environ.get(v) for v in _KEY_VARS[DEFAULT_PROVIDER]):
        return None
    candidates = [name for name, variables in _KEY_VARS.items()
                  if name != DEFAULT_PROVIDER
                  and any(os.environ.get(v) for v in variables)]
    return candidates[0] if len(candidates) == 1 else None


def _resolve_provider_name():
    explicit = os.environ.get("LLM_PROVIDER")
    if not explicit:
        inferred = _inferred_provider()
        if inferred:
            # Said out loud, every time. A tool that silently picks a provider
            # is a tool that silently picks who gets billed, and the next
            # question after an unexpected charge is "which one did it use".
            print(f"No LLM_PROVIDER set and no key for {DEFAULT_PROVIDER}, but "
                  f"{inferred} is configured. Using {inferred}. "
                  f"Set LLM_PROVIDER to choose explicitly.")
            os.environ["LLM_PROVIDER"] = inferred
            return inferred

    provider = (explicit or DEFAULT_PROVIDER).strip().lower()
    if provider not in _PROVIDERS:
        supported = ", ".join(sorted(_PROVIDERS))
        raise RuntimeError(
            f"LLM_PROVIDER={provider!r} is not supported. Supported providers: {supported}."
        )
    return provider


def _resolve_call_fn(provider):
    module_name, fn_name, _ = _PROVIDERS[provider]
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        # Not just ImportError: a present-but-broken install (e.g. a native
        # extension failing to load) can raise other exception types too,
        # and both cases need the same actionable message here.
        raise RuntimeError(
            f"LLM_PROVIDER={provider!r} requires its SDK package to be installed and "
            f"importable, which failed ({type(e).__name__}: {e}). Install/repair it "
            f"and retry -- see README's \"LLM provider\" section."
        ) from e
    return getattr(module, fn_name)


def validate_config():
    """
    Fail fast, with one clear message, before doing any real work (run.py
    calls this before spawning any per-task process) -- checks the
    configured provider is supported, its SDK package is importable, and
    its required environment variables are set. Makes no network call.
    Returns the resolved provider name.
    """
    provider = _resolve_provider_name()
    _resolve_call_fn(provider)  # raises RuntimeError if the SDK isn't installed

    problems = []
    if not _ensure_api_key(provider):
        problems.append("an API key in one of " + ", ".join(accepted_key_vars(provider)))

    _, _, extra_vars = _PROVIDERS[provider]
    missing = [v for v in extra_vars if not os.environ.get(v)]
    if missing:
        problems.append("environment variable(s) " + ", ".join(missing))

    if problems:
        raise RuntimeError(f"LLM_PROVIDER={provider!r} requires " + " and ".join(problems) + ".")
    return provider



# Each of the four agents can run on its own provider and model. The mode
# strings the call sites already pass are mapped to a role here, and the role is
# looked up in settings.yaml under `agents:`.
#
# The four agents are genuinely different jobs. Drafting a bar and adversarially
# reviewing one reward a stronger model than emitting a unified diff does, and
# the coding agent is the one invoked most often, so it is the one where a cheap
# model pays. Forcing all four onto one model makes that trade impossible.
# A role resolves through a chain: its own entry, then any group entry, then
# `default`. The three test stages are separate roles because they are separate
# jobs: unit generation is the only one that sees the implementation, and it is
# the stage that stalls most, so it is the one worth spending a stronger model
# on without paying for that model at the other two.
_MODE_ROLE = {
    "fix": "code",
    "patch": "code",
    "test_integration": "test_integration",
    "test_system": "test_system",
    "test_unit": "test_unit",
    "acceptance_criteria": "criteria",
    "acceptance_criteria_review": "review",
    "fixture_proposal": "fixtures",
}

# role -> the group entry it falls back to before `default`
_ROLE_GROUP = {
    "test_integration": "test",
    "test_system": "test",
    "test_unit": "test",
}


def _agent_config(role):
    """
    Resolve {provider, model} for one role: the role's own entry, falling back
    to its group entry (`test` for the three test stages), then to
    `agents.default`, then to the environment.

    Imported lazily. orchestrator imports agent_interface imports call_llm
    imports this module, so a module-level import of load_settings would close
    that loop.
    """
    try:
        from qikly.orchestrator.orchestrator import load_settings
        agents = (load_settings().get("agents") or {})
    except Exception:
        return {}
    cfg = dict(agents.get("default") or {})
    group = _ROLE_GROUP.get(role)
    if group:
        cfg.update({k: v for k, v in (agents.get(group) or {}).items() if v})
    cfg.update({k: v for k, v in (agents.get(role) or {}).items() if v})
    return cfg


@contextlib.contextmanager
def _selected(cfg):
    """
    Apply a role's provider and model for the duration of one call.

    Set as environment variables rather than threaded through every provider
    signature, because that is already how each provider reads its model, so
    this needs no change in any of them. An explicitly exported LLM_PROVIDER or
    LLM_MODEL still wins: the settings file configures the default arrangement,
    the environment overrides it for one run.

    The API_KEY handling is the part that is easy to get wrong. _ensure_api_key
    normalises a provider's conventional variable into API_KEY and deliberately
    never overwrites an API_KEY that is already set, which is correct when one
    provider serves the whole run. The moment two roles use two providers it is
    a silent failure: the first call populates API_KEY from, say,
    GEMINI_API_KEY, and the second call hands that Gemini key to Anthropic and
    fails to authenticate for reasons the message will not explain. So when a
    role selects its own provider, that provider's key is selected with it, and
    both are restored afterwards.
    """
    provider = cfg.get("provider")
    overrides = {}

    # A model name belongs to a provider, so the two are applied together or
    # not at all. Applying them independently produced a real failure: settings
    # said gemini + gemini-3.5-flash-lite, the user exported
    # LLM_PROVIDER=openai, and the provider override was correctly skipped
    # while the model override was not. OpenAI was then asked for
    # `gemini-3.5-flash-lite` and answered, accurately and uselessly, that no
    # such model exists.
    #
    # A model with no provider beside it is different: it is meant for whatever
    # provider ends up running, so it still applies.
    provider_overridden = bool(provider and os.environ.get("LLM_PROVIDER"))

    for key, var in (("provider", "LLM_PROVIDER"), ("model", "LLM_MODEL")):
        value = cfg.get(key)
        if not value or os.environ.get(var):
            continue
        if key == "model" and provider_overridden:
            continue
        overrides[var] = str(value)

    if provider and "LLM_PROVIDER" in overrides:
        for var in _KEY_VARS.get(provider, []):
            value = os.environ.get(var)
            if value:
                overrides["API_KEY"] = value
                break

    if not overrides:
        yield
        return

    previous = {var: os.environ.get(var) for var in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for var, was in previous.items():
            if was is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = was


def route_model(mode, prompt, seed=None):
    with _selected(_agent_config(_MODE_ROLE.get(mode, "default"))):
        return _call(prompt, seed)


def _call(prompt, seed):
    provider = _resolve_provider_name()
    # Also here, not only in validate_config(): a child process spawned with
    # a provider-conventional key but no API_KEY would otherwise reach the
    # SDK with nothing set.
    _ensure_api_key(provider)
    call_fn = _resolve_call_fn(provider)
    try:
        return call_fn(prompt, seed=seed)
    except RuntimeError:
        # Already an actionable message from the provider module (a rejected
        # request, a truncated response). Don't rewrap and lose it.
        raise
    except Exception as e:
        raise RuntimeError(_explain_call_failure(e, provider)) from e
