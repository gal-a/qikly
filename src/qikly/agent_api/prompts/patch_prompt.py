from qikly.agent_api.prompts.template_loader import load_template


def build_patch_prompt(agent_md, task, fix, codebase_text, previous_patch=None, previous_patch_error=None,
                        previous_patch_too_large=False):
    retry_section = ""
    if previous_patch_too_large and previous_patch:
        retry_section = load_template(
            "patch_prompt_retry_after_too_large.md",
            previous_patch_error=previous_patch_error,
            previous_patch=previous_patch,
        )
    elif previous_patch_error and previous_patch:
        retry_section = load_template(
            "patch_prompt_retry_after_apply_failure.md",
            previous_patch_error=previous_patch_error,
            previous_patch=previous_patch,
        )
    elif previous_patch_error:
        retry_section = load_template(
            "patch_prompt_retry_after_generation_failure.md",
            previous_patch_error=previous_patch_error,
        )

    return load_template(
        "patch_prompt.md",
        agent_md=agent_md,
        task=task,
        fix=fix,
        codebase_text=codebase_text,
        retry_section=retry_section,
    )
