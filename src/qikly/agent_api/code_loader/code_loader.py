import os

from qikly.agent_api.code_loader.excerpt import excerpt_file, relevant_names

def load_codebase(code_dir="outputs/agent_src/code"):
    """
    Load every code file under code_dir and return a single text block, each
    file prefixed with a header so the agent can reference it. code_dir is
    already task-specific (see agent_src_code_path() in agent_interface.py),
    so this never crosses into another task's code -- callers that need the
    whole implementation in context (unit test generation, or PATCH when it
    can't tell which files it needs) use this; PATCH generation itself
    prefers load_target_files() below to avoid paying for files it isn't
    touching.
    """
    output = []

    for root, dirs, files in os.walk(code_dir):
        dirs[:] = [d for d in dirs if d != "old"]
        for filename in files:
            if filename.endswith(".py"):
                path = os.path.join(root, filename)
                # errors="replace" rather than strict. This reads code the
                # model wrote, and a stray byte in it must not end the run:
                # a decode error here killed one experiment pair outright.
                # The replacement character reaches the prompt, where the
                # FIX/PATCH loop can act on it, which is the whole point of
                # having that loop.
                with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                    content = f.read()
                output.append(f"\n# FILE: {path}\n{content}\n")

    return "\n".join(output)


def load_target_files(code_dir, target_files, context=None):
    """
    Load just the given files -- as printed in a FIX's target_files list,
    e.g. "outputs/agent_src/code/<task_id>/etl.py" -- instead of every file
    under code_dir. Used to scope the PATCH prompt to what the FIX actually
    said it would touch rather than the whole task codebase.

    target_files is LLM output, not trusted input: any path that doesn't
    resolve inside code_dir is silently skipped rather than read (no
    escaping the task's own code directory). A path naming a file that
    doesn't exist yet (a FIX about to create it for the first time) is also
    silently skipped -- there's nothing to show the model.

    `context` is the text that named this work: the FIX itself, and the
    failing test output. Any file over the size threshold is excerpted against
    the identifiers in it, so a large module contributes the definitions this
    failure is about plus a signature for everything else, rather than either
    filling the prompt or being unusable. Passing nothing means every file is
    loaded whole, which is the old behaviour and still right for small ones.
    """
    code_dir_abs = os.path.abspath(code_dir)
    # Names from the FIX and the failure text decide what survives an
    # excerpt. Without context nothing matches, which would collapse every
    # definition, so an empty context means load whole instead.
    wanted = relevant_names(context) if context else None
    output = []

    for rel_path in target_files:
        candidate = os.path.abspath(rel_path)
        try:
            inside = os.path.commonpath([candidate, code_dir_abs]) == code_dir_abs
        except ValueError:
            # On Windows commonpath raises for paths on different drives. A
            # model that names D:\tmp\x.py should have its suggestion
            # ignored, not end the run with a traceback.
            inside = False
        if not inside:
            continue
        if not os.path.isfile(candidate):
            continue
        if wanted:
            content = excerpt_file(candidate, wanted)
        else:
            # No names to match on, so excerpting would collapse every
            # definition in the file. "I was not told what matters" reads as
            # load it whole.
            with open(candidate, "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
        output.append(f"\n# FILE: {candidate}\n{content}\n")

    return "\n".join(output)