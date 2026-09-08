from qikly.agent_api.prompts.template_loader import load_template


def build_system_test_prompt(test_agent_md, task):
    return load_template("system_test_prompt.md", test_agent_md=test_agent_md, task=task)
