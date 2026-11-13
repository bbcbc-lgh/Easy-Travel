"""Places the traveller insists on, matched tolerantly but checked strictly.

The user types "西湖"; the data layer returns "西湖风景名胜区". Exact matching
would declare the trip unsatisfying when it actually contains the place asked for,
so matching allows one name to contain the other. What is *not* tolerant is the
requirement itself: a must-visit that the plan omits is a defect, and every check
in the pipeline uses this module so they cannot disagree about it.
"""

from collections.abc import Iterable


def normalize(name: str) -> str:
    return "".join(name.split()).lower()


def matches(query: str, candidate: str) -> bool:
    """Whether ``candidate`` is the place the user asked for by ``query``."""
    left = normalize(query)
    right = normalize(candidate)
    if not left or not right:
        return False
    if left == right:
        return True
    # "西湖" vs "西湖风景名胜区": one containing the other is the same place in
    # practice. The two-character floor stops a single shared character matching.
    return len(left) >= 2 and len(right) >= 2 and (left in right or right in left)


def missing(queries: Iterable[str], placed: Iterable[str]) -> list[str]:
    """The queries that no placed name satisfies, in the order they were asked for."""
    placed_names = list(placed)
    return [query for query in queries if not any(matches(query, name) for name in placed_names)]


def duplicated(queries: Iterable[str], placed: Iterable[str]) -> list[str]:
    """The queries satisfied by more than one placed name."""
    placed_names = list(placed)
    return [query for query in queries if sum(1 for name in placed_names if matches(query, name)) > 1]
