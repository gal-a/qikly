from qikly.paths import resolve_input


def load_template(filename, **kwargs):
    """
    Read a prompt template from agent_defs/<filename> and fill in its
    {placeholder} fields with kwargs. Reads your inputs_private/agent_defs/
    copy if you have written one, else the bundled default -- per file, so
    overriding one prompt doesn't mean copying all of them.
    """
    path = resolve_input(f"agent_defs/{filename}")
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()
    return template.format(**kwargs)
