"""Separator-agnostic name matching for service/container lookups.

Users type service names like 'agent_api' while the real container is
'marconi-agent-api'. Collapsing separator differences lets a lookup match
regardless of spelling.
"""

import re

_SEPARATORS = re.compile(r"[-_\s.]+")


def normalize(name: str) -> str:
    """Lowercase and strip separator chars: 'agent_api' == 'agent-api' == 'agentapi'."""
    return _SEPARATORS.sub("", str(name)).lower()
