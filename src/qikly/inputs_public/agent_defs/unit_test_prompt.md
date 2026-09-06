
{test_agent_md}

You must now generate the UNIT test file for the implementation described in
the task specification below.

Task specification:
{task}

Current implementation (outputs/agent_src/code/), verbatim -- this is the one
exception where you may see the implementation directly, so you can target
its actual functions and helpers by name:
{codebase_text}

Unit tests exercise individual functions in isolation, with small,
hand-constructed inputs you build inside the test itself (dicts, lists,
strings) -- do not read any file listed in the task specification's
`inputs:` list and do not call the system entry point end-to-end. Test each
function's contract against the
specification's requirements above, not merely whatever the current
implementation happens to do: if the requirements clearly call for handling
a case the code doesn't cover, still assert the spec-correct behavior rather
than mirroring a bug.

Follow the FORMAT and GENERAL RULES exactly.
Output ONLY the Python source of the test file.
