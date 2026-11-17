from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class Oracle(Protocol):
    def core(self, active: frozenset[str]) -> frozenset[str] | None: ...


@dataclass(frozen=True)
class Conflicts:
    mus: tuple[tuple[str, ...], ...]
    mcs: tuple[tuple[str, ...], ...]
    complete: bool


def shrink(oracle: Oracle, core: frozenset[str]) -> frozenset[str]:
    kept = core
    for member in sorted(core):
        if member not in kept:
            continue
        smaller = oracle.core(kept - {member})
        if smaller is not None:
            kept = smaller if smaller <= kept - {member} else kept - {member}
    return kept


def enumerate_conflicts(
    oracle: Oracle, hard: frozenset[str], levers: frozenset[str], max_sets: int, max_depth: int
) -> Conflicts:
    muses: list[frozenset[str]] = []
    corrections: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()
    frontier: list[frozenset[str]] = [frozenset()]
    complete = True
    while frontier:
        if len(muses) >= max_sets:
            complete = False
            break
        removed = frontier.pop(0)
        if removed in seen or any(found <= removed for found in corrections):
            continue
        seen.add(removed)
        core = oracle.core(hard - removed)
        if core is None:
            corrections = [found for found in corrections if not removed < found]
            corrections.append(removed)
            continue
        minimal = shrink(oracle, core)
        if minimal not in muses:
            muses.append(minimal)
        if len(removed) >= max_depth:
            complete = False
            continue
        frontier.extend(removed | {member} for member in sorted(minimal) if member in levers)
    smallest = [found for found in corrections if not any(other < found for other in corrections)]
    return Conflicts(
        tuple(tuple(sorted(found)) for found in muses),
        tuple(sorted((tuple(sorted(found)) for found in smallest), key=lambda found: (len(found), found))),
        complete,
    )


def flips(points: Sequence[tuple[int, str]]) -> list[dict[str, object]]:
    return [
        {"from": before[0], "to": after[0], "status_from": before[1], "status_to": after[1]}
        for before, after in zip(points, points[1:], strict=False)
        if (before[1] == "infeasible") != (after[1] == "infeasible")
    ]
