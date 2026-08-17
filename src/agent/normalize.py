"""Separator-agnostic name matching for service/container lookups.

Users type service names like 'agent_api' while the real container is
'marconi-agent-api'. Collapsing separator differences lets a lookup match
regardless of spelling. ``resolve_one`` is the single matching rule every
lookup goes through, so partial names behave the same everywhere.
"""

import re
from collections.abc import Callable, Iterable

_SEPARATORS = re.compile(r"[-_\s.]+")


class AmbiguousName(LookupError):
    """A partial name matched more than one candidate."""

    def __init__(self, name: str, matches: list[str], kind: str = "names"):
        self.name = name
        self.matches = matches
        super().__init__(
            f"'{name}' matches {len(matches)} {kind}: {', '.join(matches)}"
            " - use one of these exact names"
        )


def normalize(name: str) -> str:
    """Lowercase and strip separator chars: 'agent_api' == 'agent-api' == 'agentapi'."""
    return _SEPARATORS.sub("", str(name)).lower()


def resolve_one[T](
    name: str,
    candidates: Iterable[T],
    key: Callable[[T], str] = str,
    kind: str = "names",
) -> T | None:
    """The one candidate a (possibly partial) name refers to. None if no match.

    An exact name always wins, so a container literally called `agent_api` beats
    `marconi-agent-api-worker`. A partial name that matches several candidates
    raises instead of returning whichever came first — silently picking one
    reports the wrong thing under the name the caller asked for.
    """
    needle = normalize(name)
    matches = [c for c in candidates if needle in normalize(key(c))]
    for candidate in matches:
        if normalize(key(candidate)) == needle:
            return candidate
    if len(matches) > 1:
        raise AmbiguousName(name, sorted(key(c) for c in matches), kind)
    return matches[0] if matches else None
