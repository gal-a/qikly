# Setting up a provider key

Every qikly run calls one model provider, and that provider needs a key. This
page covers all three, on PowerShell, bash and CI, plus how to check a key took
and how to stop paying for one you forgot about.

If you only want the shortest path: get a
[Gemini key](https://aistudio.google.com/apikey), which has a free tier and
needs no card, then `qikly --demo`.

---

## Which provider

| Provider | Key from | Install | Notes |
|---|---|---|---|
| **Gemini** (default) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | included | Free tier, no card. Cheapest by roughly 20x. Every published qikly figure was measured on it |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `pip install "qikly[openai]"` | Requires billing set up |
| **Anthropic** | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) | `pip install "qikly[anthropic]"` | Requires billing. No seed and no temperature, so runs vary more than the others. A reasoning model, so it produces thinking tokens you are billed for on top of the answer |

You do not have to choose one forever. All three keys can sit in your
environment at once; `LLM_PROVIDER` decides which is used, and if you set no
provider and hold exactly one key, qikly uses that one and says so.

**Restricting the key.** qikly calls exactly one endpoint per provider, so a
minimal key is enough. On OpenAI, choose **Restricted** and grant only
**Chat completions (`/v1/chat/completions`)**; every other row stays `None`.
Read-only will not work, because creating a completion is a write.

---

## Windows PowerShell

### Gemini

```powershell
$env:GEMINI_API_KEY = "AIza..."
$env:LLM_PROVIDER   = "gemini"

Write-Output "provider: $env:LLM_PROVIDER"
Write-Output "key:      $($env:GEMINI_API_KEY.Length) chars, ends ...$($env:GEMINI_API_KEY.Substring($env:GEMINI_API_KEY.Length-4))"

qikly --demo
```

### OpenAI

```powershell
pip install "qikly[openai]"

$env:OPENAI_API_KEY = "sk-proj-..."
$env:LLM_PROVIDER   = "openai"

Write-Output "provider: $env:LLM_PROVIDER"
Write-Output "key:      $($env:OPENAI_API_KEY.Length) chars, ends ...$($env:OPENAI_API_KEY.Substring($env:OPENAI_API_KEY.Length-4))"

qikly --demo
```

### Anthropic

```powershell
pip install "qikly[anthropic]"

$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:LLM_PROVIDER      = "anthropic"

Write-Output "provider: $env:LLM_PROVIDER"
Write-Output "key:      $($env:ANTHROPIC_API_KEY.Length) chars, ends ...$($env:ANTHROPIC_API_KEY.Substring($env:ANTHROPIC_API_KEY.Length-4))"

qikly --demo
```

The check prints the length and last four characters rather than the key. A
plain `$env:OPENAI_API_KEY` writes the whole secret into your terminal
scrollback and your PSReadLine history file, which is a bad habit for something
that bills you.

### Making it stick

`$env:` lasts for that window only. Close the terminal and the key is gone.

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-proj-...", "User")
```

Then **open a new terminal**: the current one will not see it.

```powershell
# what is persisted, as opposed to only set here
[Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")

# everything qikly might pick up, in this session
Get-ChildItem Env: | Where-Object Name -match 'API_KEY|LLM_'

# remove one
Remove-Item Env:\OPENAI_API_KEY
```

That last listing is the fastest way to find a stale `LLM_PROVIDER` from an
earlier experiment, which is the usual reason a run goes somewhere unexpected.

---

## macOS and Linux

```bash
# Gemini
export GEMINI_API_KEY=AIza...
export LLM_PROVIDER=gemini

# OpenAI
pip install "qikly[openai]"
export OPENAI_API_KEY=sk-proj-...
export LLM_PROVIDER=openai

# Anthropic
pip install "qikly[anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
export LLM_PROVIDER=anthropic

qikly --demo
```

Check it took without printing it:

```bash
echo "${#OPENAI_API_KEY} chars, ends ...${OPENAI_API_KEY: -4}"
env | grep -E 'API_KEY|LLM_' | sed 's/=.*/=<set>/'
```

To persist, add the `export` lines to `~/.zshrc` or `~/.bashrc`, or keep them
in a `.env` you source. Do not commit either.

---

## CI

**GitHub Actions.** Store the key as a repository secret, never in the
workflow file:

```yaml
- uses: gal-a/qikly@v0.4.0
  with:
    api-key: ${{ secrets.OPENAI_API_KEY }}
    provider: openai
    qikly-version: "qikly==0.3.0"
```

A secret is masked in logs. A literal is not, and a key pushed to a public repo
is compromised within minutes, whether or not the commit is later removed.

---

## Checking it worked

```bash
qikly --validate     # free, and will NOT catch a bad key: it opens no socket
qikly --demo         # one task, real calls, a few cents
```

`--demo` is the real test. It reports the provider, the model, the estimated
cost, and whether the task converged.

**What a wrong key looks like:**

```
OpenAI API rejected the request: Error code: 401 ...
If this looks like an auth error, check API_KEY for typos/whitespace
```

Whitespace is the usual culprit: a trailing space or newline copied along with
the key. Compare the length you printed above against the length on the
provider's console.

**What a wrong model looks like:**

```
The model `gemini-3.5-flash-lite` does not exist or you do not have access
```

That is a provider and model that disagree. Check `LLM_MODEL` is unset or
correct for the provider you chose.

---

## Cost, and how not to be surprised

Every run prints an estimate before it starts and the real usage afterwards.
The estimate comes from your own run history once you have some.

A single `--demo` on the default provider is a fraction of a cent. The same
demo on gpt-4o is roughly twenty times that, and it will be slower.

Three ways to bound it:

- `QIKLY_MAX_CALLS=50` stops a run dead after N model calls.
- `QIKLY_MAX_OUTPUT_TOKENS` caps Anthropic's per-reply budget, default 16384.
  It has to cover thinking as well as the answer: at 4096 claude-sonnet-5 spent
  the entire budget reasoning and returned no answer at all.
- Set a spend limit on the provider's own console. **This is the one that
  actually protects you**, because it applies whatever calls the API.
- On OpenAI, put the key in its own project and cap that project. Then a
  mistake here cannot spend what you budgeted for something else.

---

## If you rotate or revoke a key

Nothing in qikly stores a key. It reads the environment on every call, so
revoking on the provider's console and exporting a new value is the whole
procedure. There is no cache to clear and no config file to edit.
