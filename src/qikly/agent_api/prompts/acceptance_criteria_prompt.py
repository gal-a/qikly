from qikly.agent_api.prompts.template_loader import load_template


def build_acceptance_criteria_prompt(task):
    return load_template("acceptance_criteria_prompt.md", task=task)
