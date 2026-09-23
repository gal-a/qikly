
{test_agent_md}

You must now generate the INTEGRATION test file for the implementation
described in the task specification below.

Task specification:
{task}

Integration tests exercise the functions listed under the task
specification's `interface.integration_functions` together, in the sequence
implied by the specification's requirements -- not the single entry point
under `interface.system_entrypoint` (that has its own, separate SYSTEM test
file). Import them from the module named in `interface.module`.

You do not have access to the implementation. Write the tests purely from the
specification above: call each integration function in turn, feeding each
one's output into the next the way the requirements describe, and assert
properties that the requirements and acceptance criteria say must hold of
the results -- e.g. every kept item satisfies the stated validation rules,
values are normalized as specified, invalid items are absent from
downstream results, the final function writes out exactly what it was given.
Compute these checks against whatever the functions actually return; do not
assume specific counts, ids, or contents ahead of time.

NAME EACH TEST AFTER THE SEAM IT CROSSES. An integration test exists to check
that one function's output is what the next one can actually take, so its name
must say which two. Use `test_<first>_to_<second>_<what_is_checked>`, in the
order the data flows: `test_extract_to_transform_drops_unparsable_rows`,
`test_transform_to_load_writes_every_accepted_row`. A test that spans the whole
chain names the ends: `test_extract_to_load_<what_is_checked>`. Never name an
integration test after the rule alone, as in `test_rounding_properties`: when it
fails, the name is the first thing read, and it should say where the pipeline
came apart rather than only what was wrong.

Follow the FORMAT and GENERAL RULES exactly.
Output ONLY the Python source of the test file.
