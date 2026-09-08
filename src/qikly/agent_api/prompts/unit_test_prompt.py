from qikly.agent_api.prompts.template_loader import load_template


def build_unit_test_prompt(test_agent_md, task, codebase_text):
    return load_template(
        "unit_test_prompt.md",
        test_agent_md=test_agent_md,
        task=task,
        codebase_text=codebase_text,
    )
