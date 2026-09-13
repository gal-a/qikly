# Configuration and LLM provider

Settings, environment variables and provider setup. For getting a key onto a
machine, into CI, or diagnosing one that is wrong, see
[PROVIDER_KEY_SETUP.md](https://github.com/gal-a/qikly/blob/main/docs/PROVIDER_KEY_SETUP.md).

## Configuration

### Timeouts

Every model call has a deadline of **300 seconds**, set by
`QIKLY_REQUEST_TIMEOUT` in seconds. `0` waits forever, which is what provider
SDKs do by default and is why the setting exists: a stalled connection blocks a
call that never raises, so nothing downstream can react to it. With a deadline
the same stall becomes an ordinary transient error and is retried with backoff.

A task process prints `still running, N minutes elapsed` every five minutes, so
that "not answering" is visible rather than inferred.


`config/settings.yaml`, shared across all tasks:

| Key | Meaning |
|---|---|
| `orchestrator.max_retries_per_stage` | Attempt budget per stage before the run raises. If you see the exact same patch content repeating verbatim, that's usually a requirement fighting the model's real-world prior (see below) rather than a budget problem. If instead each attempt is a *different* patch that never resolves the same failing test, that's a different signal: a bug that needs more than the failure text to resolve, rather than an artificial requirement; see [Where it fits today](https://github.com/gal-a/qikly/blob/main/README.md#where-it-fits-today) on telling the two signatures apart. |
| `orchestrator.test_order` | Stage order; `unit` is always forced last (it's generated from the implementation, which doesn't exist yet during integration/system). |
| `agent.max_patch_size` | Rejects an oversized PATCH and asks the model to retry smaller. Tune per task if a bigger implementation needs more room. |
| `logging.save_transactions` | Turns off `transactions_*.jsonl` logging entirely; also disables the HTML report, which reads that log. |

## LLM provider

Every call in a run goes to one provider. One provider per run; mixing them
per agent role is not supported.

### Getting a key

| Provider | Where the key comes from | Install |
|---|---|---|
| **Gemini** (default) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | included |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `pip install "qikly[openai]"` |
| **Anthropic** | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) | `pip install "qikly[anthropic]"` |

Then export the key and pick the provider:

```bash
# Gemini, the default. Nothing else needed.
export GEMINI_API_KEY=...
qikly --demo

# OpenAI
pip install "qikly[openai]"
export OPENAI_API_KEY=...
export LLM_PROVIDER=openai
qikly --demo

# Anthropic
pip install "qikly[anthropic]"
export ANTHROPIC_API_KEY=...
export LLM_PROVIDER=anthropic
qikly --demo
```

On Windows PowerShell, `$env:OPENAI_API_KEY = "..."` instead of `export`.

`API_KEY` works for any of them, and each provider's own conventional variable
is accepted too, so a machine already configured for one needs nothing extra.

**A note on which provider to start with.** Every convergence figure in this
README was measured on `gemini-3.5-flash-lite`, over hundreds of runs, and the
bundled demo is tuned to that path. The other providers work and are far less
travelled here, and an entry-level model on any of them may stall on tasks that
the measured path clears. If a provider you have chosen converges poorly, reach
for a stronger model on it before concluding anything about the tool: model
choice moves convergence more than any setting in this file.

**PowerShell, CI, persisting a key, restricting one, and what a wrong key or
a wrong model looks like:** [docs/PROVIDER_KEY_SETUP.md](https://github.com/gal-a/qikly/blob/main/docs/PROVIDER_KEY_SETUP.md).

### Checking a key works, for about a cent

```bash
qikly --validate                       # free: does not touch the network
LLM_PROVIDER=openai qikly --demo       # one task, about a cent
```

`--demo` is the real test. It makes actual calls, writes to a throwaway folder,
and reports the model, the estimated cost and whether it converged. A wrong key
fails on the first call with a message naming what to check.

`--validate` will not catch a bad key, because it never opens a socket. That is
the point of it.

### The variables

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER` | `gemini` (default), `openai` or `anthropic` |
| `LLM_MODEL` | Overrides the provider default: `gemini-3.5-flash-lite`, `gpt-4o`, `claude-sonnet-5` |
| `API_KEY` | The key. Provider-specific names above are accepted too |
| `QIKLY_REQUEST_TIMEOUT` | Seconds per call, default 300. `0` waits forever |
| `QIKLY_MAX_CALLS` | Hard stop after N model calls, for an unattended run |

One provider per run. Mixing them per agent role is not supported.

### Determinism is best-effort, and uneven

With a seed set, Gemini and OpenAI are called at `temperature=0` and are given
the seed itself. **Anthropic gets neither.** Its Messages API has never had a
seed, and SDK 1.x removed `temperature` from `messages.create()` entirely, so
there is no sampling lever left to pull.

That matters if you compare rates across providers: an Anthropic figure carries
more run-to-run variance than the others by construction. No provider promises
identical output either way, so treat all of this as reduced drift rather than
reproducibility.

### Keeping providers working

The SDKs are other people's code on other people's release schedules, and this
is the part of qikly most likely to break without you touching it. Two habits
cover it:

```bash
pip install "qikly[all-providers]"
python -m pytest tests/test_provider_signatures.py -v
```

That reads the signature of every SDK you have installed and compares it
against what qikly sends, so a removed or renamed parameter fails a test rather
than a user's first run. It is how the Anthropic `temperature` break was found.

What it cannot catch is a parameter that still exists and now means something
different, or a model name retired server-side. **One `--demo` per provider
before each release** covers that, costs a few cents, and is the only check
that exercises the real API.

Dependencies carry upper bounds for the same reason. Raising one after testing
is a two-line change; not having one lets a major version arrive unannounced.

