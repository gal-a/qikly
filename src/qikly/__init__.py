"""
qikly -- an autonomous coding agent that writes its own acceptance
criteria, and the tests that enforce them, then converges real code against
that bar.

The subpackages here (orchestrator, agent_api, agent_tools) were top-level
until they were nested under this one. They are generic enough names that
installing them at the top level of site-packages would eventually collide
with somebody else's `orchestrator`.
"""
__version__ = "0.3.3"
