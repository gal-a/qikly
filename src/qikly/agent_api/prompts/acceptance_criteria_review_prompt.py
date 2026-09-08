from qikly.agent_api.prompts.template_loader import load_template


def build_acceptance_criteria_review_prompt(task, criteria, implementation_code):
    criteria_text = "\n".join(f'- "{c}"' for c in criteria)
    return load_template(
        "acceptance_criteria_review_prompt.md",
        task=task,
        criteria=criteria_text,
        implementation_code=implementation_code,
    )
