"""
Where the provider key came from, and whether it can possibly be a key at all.

Split out of router.py so the three provider modules can report the same thing
without importing the router that dispatches to them.

The failure this exists for, found on release day. A key pasted with one stray
character in front was rejected by Gemini as unauthenticated, and the message
told the user to check `API_KEY` for typos: a variable they had never set, and
which was not set. The good key was sitting in `GEMINI_API_KEY` the whole time,
one character longer than the one that worked. Naming the variable the key was
actually read from, and its length, turns that hunt into a glance.
"""
import os

_source = None  # the environment variable the current API_KEY was taken from

_QUOTES = "\"'"

# A run is a parent process and one child per task, and the parent normalises
# the key into API_KEY before spawning. The child therefore inherits an
# API_KEY that is already set, takes the early return in _ensure_api_key, and
# would report "API_KEY" as the source no matter what the user actually set.
# That is the original bug wearing a different hat, so the true source travels
# to the child in the environment beside the key it describes.
SOURCE_ENV = "QIKLY_KEY_SOURCE"


def remember_source(var):
    """
    Record which environment variable API_KEY was normalised from, and pass it
    to any child process. `None` clears both, which is what tests want.
    """
    global _source
    _source = var
    if var:
        os.environ[SOURCE_ENV] = var
    else:
        os.environ.pop(SOURCE_ENV, None)


def source():
    """
    The variable the key came from, or None if nothing has resolved one.

    Falls back to the inherited value so a child process names the variable the
    user set rather than the one the parent normalised it into.
    """
    return _source or os.environ.get(SOURCE_ENV) or None


def defect(value):
    """
    Why `value` cannot be a key, as a phrase, or None if it looks usable.

    Deliberately narrow. It reports only characters that are never part of any
    provider's key, so it cannot reject a valid key in a format nobody here has
    seen yet. Length and prefix are left to `auth_hint`, which only speaks once
    the provider has already refused the credential, because both of those
    change without warning and a wrong refusal is worse than a late one.
    """
    if not value:
        return None
    if value.startswith("﻿"):
        return ("starts with a byte order mark, so it was probably pasted from "
                "a file saved as UTF-8 with BOM")
    if value != value.strip():
        return "has leading or trailing whitespace"
    if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:
        return "is wrapped in quotes, which the shell did not strip"
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return "contains a control character"
    if any(c.isspace() for c in value):
        return "contains a space"
    if not value.isascii():
        return "contains a non-ASCII character"
    return None


# Key shapes seen in the wild, used ONLY to phrase a hint after the provider
# has already refused the credential. Never to refuse one here: providers add
# formats without notice, and a hint that has aged badly costs a sentence
# whereas a refusal that has aged badly costs the user the whole run.
_SHAPES = {
    "gemini": "39 characters starting AIza, or 53 starting AQ.",
    "openai": "starting sk- or sk-proj-",
    "anthropic": "starting sk-ant-",
}


def auth_hint(provider=None):
    """
    What to check when a provider rejects the credential.

    Names the variable the key was actually taken from and its length. The
    common failure is a good key in the provider's conventional variable and a
    stale or mistyped one somewhere with higher precedence, and a message that
    names only `API_KEY` sends the reader to a variable they never set.

    The length is here because of the failure that prompted all this: the key
    was right, and one stray printable character in front of it made it one
    longer. Nothing can detect that from the value alone, but a user who sees
    "54 characters" next to "normally 53" finds it immediately.
    """
    key = os.environ.get("API_KEY", "")
    var = source() or "API_KEY"
    if not key:
        return f"No key is set: {var} is empty."
    hint = (f"If this looks like an auth error, the key in use came from "
            f"{var} and is {len(key)} characters long")
    problem = defect(key)
    if problem:
        hint += f", and it {problem}"
    shape = _SHAPES.get(provider)
    if shape:
        hint += f" (a {provider} key is normally {shape})"
    return hint + f". Check {var} rather than any other variable."
