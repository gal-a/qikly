
{test_agent_md}

You must now generate the SYSTEM test file for the implementation described
in the task specification below.

Task specification:
{task}

System tests exercise the single entry point named in the task
specification's `interface.system_entrypoint`, imported from the module
named in `interface.module`, end-to-end -- treat everything behind it as a
black box. Do not call the individual functions under
`interface.integration_functions` (those have their own, separate
INTEGRATION test file).

You do not have access to the implementation. Write the tests purely from
the specification above: call the entry point using the inputs/outputs the
specification describes (e.g. into a tempfile.TemporaryDirectory() if it
writes a file, or using its return value if it doesn't), then assert
properties that the requirements and acceptance criteria say must hold of
the result -- e.g. structure and field constraints, normalization rules, no
duplicates. Compute these checks against whatever the entry point actually
produces; do not assume specific counts, ids, or contents ahead of time.

Follow the FORMAT and GENERAL RULES exactly.
Output ONLY the Python source of the test file.
