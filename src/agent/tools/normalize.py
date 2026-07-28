"""Separator-agnostic name matching for service/container lookups.

Users type service names like 'agent_api' while the real container is
'marconi-agent-api'. These helpers collapse separator differences so a lookup
matches regardless of spelling.
"""

import re

_SEPARATORS = re.compile(r"[-_\s.]+")


def normalize(name: str) -> str:
    """Lowercase and strip separator chars: 'agent_api' == 'agent-api' == 'agentapi'."""
    return _SEPARATORS.sub("", str(name)).lower()


def regex_parts(name: str) -> str:
    """Build a separator-agnostic regex fragment: 'agent_api' -> 'agent.*api'.

    Each token is regex-escaped so special characters match literally; the
    separators between tokens become '.*' so the fragment matches regardless
    of how the target splits its name.
    """
    parts = [re.escape(p) for p in _SEPARATORS.split(str(name)) if p]
    return ".*".join(parts)
