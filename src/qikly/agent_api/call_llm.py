from qikly.agent_api.providers.router import route_model
from qikly.agent_api.retry import with_retry

def call_llm(mode, prompt, seed=None):
    """
    Unified entry point for all LLM calls. Every mode is sent to the single
    provider configured via LLM_PROVIDER (see agent_api/providers/router.py).
    mode: "fix", "patch", "test_integration", "test_system", or "test_unit"
    prompt: fully constructed prompt string
    seed: optional int for best-effort reproducible output
    """
    # Transport failures are retried here; bad answers are not. A rate limit
    # or a gateway error says nothing about the task, and letting it through
    # spends an attempt from the stage budget on a problem the model never
    # saw. A refusal that retrying cannot fix, a depleted balance or a bad
    # key, is raised immediately with its own message intact.
    return with_retry(lambda: route_model(mode, prompt, seed=seed))
