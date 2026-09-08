"""
Reading acceptance criteria straight out of a Jira issue.

`--criteria-from` already reads a ticket you saved to a file, and that is the
version with no moving parts. This is the same thing without the copy and
paste, for teams whose criteria live in Jira and always will.

## The shape, and why it is shaped that way

Three pieces, deliberately separated, because this is the only part of qikly
that talks to somebody else's server and that is a maintenance liability worth
containing:

  `parse_issue(payload)`   pure. A dict in, criteria out. No network.
  `fetch_issue(...)`       the only function here that opens a socket.
  `criteria_for(key)`      wires the two together for the CLI.

Everything interesting lives in `parse_issue`, so the behaviour that can be
wrong is tested offline against recorded payloads, and the part that can break
because Atlassian changed something is four lines that do one GET.

## Where criteria actually live in a Jira issue

There is no standard field, which is the whole difficulty. Three cases, checked
in order:

1. **A custom field literally called something like "Acceptance Criteria".**
   Common in mature Jira projects, and unambiguous when present. Found by
   reading the field *names* from the issue's own metadata rather than by
   hardcoding a `customfield_10038` id, because those ids differ per instance
   and a hardcoded one is wrong everywhere except where it was written.
2. **A heading inside the description.** The common case in practice.
3. **The description as a bare list**, when it is nothing but criteria.

Cases 2 and 3 are handled by the same parser `--criteria-from` uses, so a
ticket pasted into a file and a ticket fetched over the API produce identical
output. That is worth more than it sounds: it means the risky path is only ever
transport, and the parsing it feeds is already covered by tests.

## Atlassian Document Format

Modern Jira returns descriptions as ADF, a nested JSON tree, not text. The
flattener here walks it into plain text with list items as `- ` bullets, which
is what the existing parser expects. Plain-string descriptions from older
instances still work.
"""
import base64
import json
import os
import urllib.error
import urllib.request

from qikly.criteria_import import parse_criteria

ENV_BASE_URL = "JIRA_BASE_URL"
ENV_EMAIL = "JIRA_EMAIL"
ENV_TOKEN = "JIRA_API_TOKEN"

TIMEOUT_SECONDS = 20

# Field names that mean "acceptance criteria" in the wild. Matched
# case-insensitively against the issue's own field names.
CRITERIA_FIELD_NAMES = (
    "acceptance criteria", "acceptance_criteria", "acceptancecriteria",
    "criteria of acceptance", "definition of done",
)


def _flatten_adf(node, out, depth=0):
    """Atlassian Document Format into plain text, keeping list structure."""
    if isinstance(node, str):
        out.append(node)
        return
    if isinstance(node, list):
        for item in node:
            _flatten_adf(item, out, depth)
        return
    if not isinstance(node, dict):
        return

    kind = node.get("type")
    if kind == "text":
        out.append(node.get("text") or "")
        return
    if kind == "hardBreak":
        out.append("\n")
        return

    if kind == "listItem":
        out.append("\n- ")
        _flatten_adf(node.get("content") or [], out, depth + 1)
        return
    if kind in ("paragraph", "heading"):
        # Not when a bullet marker was just written. A newline here would leave
        # "- " alone on its own line, and the parser would read that as an
        # empty bullet followed by an unbulleted line, losing the criterion.
        if not (out and out[-1].endswith("- ")):
            out.append("\n")
        if kind == "heading":
            # Keep the heading marker so the parser can find a criteria
            # section, which is the whole reason this text is being rebuilt.
            out.append("#" * min(node.get("attrs", {}).get("level", 2), 6) + " ")
        _flatten_adf(node.get("content") or [], out, depth)
        out.append("\n")
        return

    _flatten_adf(node.get("content") or [], out, depth)


def adf_to_text(value):
    """A description field as text, whether it arrived as ADF or as a string."""
    if isinstance(value, str):
        return value
    if not value:
        return ""
    parts = []
    _flatten_adf(value, parts)
    return "".join(parts)


def parse_issue(payload, field_names=None):
    """
    Acceptance criteria from a Jira issue payload. Pure: no network.

    `field_names` maps field id to human name, as `/rest/api/3/field` returns
    it. Without it, only the description is read, which is the safe fallback:
    a custom field id means nothing on its own and guessing at one would read
    an arbitrary field's contents into somebody's acceptance bar.
    """
    fields = (payload or {}).get("fields") or {}

    # 1. A dedicated field, found by name rather than by hardcoded id.
    for field_id, value in fields.items():
        if not value:
            continue
        human = (field_names or {}).get(field_id, "")
        if human.strip().lower() in CRITERIA_FIELD_NAMES:
            found = parse_criteria(adf_to_text(value))
            if found:
                return found, human

    # 2 and 3. The description, through the same parser a saved file uses.
    text = adf_to_text(fields.get("description"))
    return parse_criteria(text), "description"


def _auth_header(email, token):
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _get(url, email, token):
    request = urllib.request.Request(url, headers={
        "Authorization": _auth_header(email, token),
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_issue(issue_key, base_url=None, email=None, token=None):
    """
    One issue and the instance's field names. The only function here that opens
    a socket, kept to four lines of real work for exactly that reason.
    """
    base_url = (base_url or os.environ.get(ENV_BASE_URL) or "").rstrip("/")
    email = email or os.environ.get(ENV_EMAIL)
    token = token or os.environ.get(ENV_TOKEN)
    missing = [name for name, value in
               ((ENV_BASE_URL, base_url), (ENV_EMAIL, email), (ENV_TOKEN, token))
               if not value]
    if missing:
        raise ValueError(
            f"Jira needs {', '.join(missing)}. Set them in your environment; "
            f"the token comes from id.atlassian.com under API tokens.")

    issue = _get(f"{base_url}/rest/api/3/issue/{issue_key}", email, token)
    try:
        fields = {f["id"]: f.get("name", "") for f in
                  _get(f"{base_url}/rest/api/3/field", email, token)}
    except (urllib.error.URLError, ValueError, KeyError, TypeError):
        # Field names are an optimisation, not a requirement. Without them the
        # description path still works, and a run should not fail because a
        # secondary lookup did.
        fields = {}
    return issue, fields


def criteria_for(issue_key, base_url=None, email=None, token=None):
    """Returns (criteria, where_they_came_from)."""
    issue, field_names = fetch_issue(issue_key, base_url, email, token)
    return parse_issue(issue, field_names)
