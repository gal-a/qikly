from qikly.agent_api.prompts.template_loader import load_template


def build_fix_prompt(agent_md, task, failure_info, previous_ineffective_patch=None):
    ineffective_section = ""
    if previous_ineffective_patch:
        ineffective_section = load_template(
            "fix_prompt_ineffective_section.md",
            previous_ineffective_patch=previous_ineffective_patch,
        )

    return load_template(
        "fix_prompt.md",
        agent_md=agent_md,
        task=task,
        failure_info=failure_info,
        ineffective_section=ineffective_section,
    )
