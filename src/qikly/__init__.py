"""
qikly -- generates a test suite from acceptance criteria, then converges code
against it with an agent that never sees those criteria.

The subpackages here (orchestrator, agent_api, agent_tools) were top-level
until they were nested under this one. They are generic enough names that
installing them at the top level of site-packages would eventually collide
with somebody else's `orchestrator`.
"""
__version__ = "0.4.1"
