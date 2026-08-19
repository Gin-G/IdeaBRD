"""Fractional ranks: ordering keys that keep a reorder down to one file.

Board order has to live in git without a manifest, so it lives in the ideas
themselves. A dense integer ``position`` would defeat the point — inserting a
tile at the top renumbers every file below it, and two phones doing that from
the same commit then conflict on every one of those files.

A fractional rank is a base-36 string compared lexicographically, with the one
property that matters: there is always room to name a key strictly between any
two others. Moving a tile rewrites that tile's file and nothing else, so two
devices reordering different tiles merge without touching each other.

    between(None, None)  -> "i"     first tile on an empty board
    between("i", None)   -> "r"     append after it
    between("i", "r")    -> "m"     drop one in between
    between("a", "b")    -> "ai"    no digit left in the gap, so the key grows

Keys lengthen only when the space between two neighbours is exhausted, which
takes repeatedly dropping tiles into the same slot. Ranks are compared as
plain strings, never parsed as numbers, so ``"z" < "za"`` holds everywhere the
board is read — Postgres, Python and the phone alike.
"""

from __future__ import annotations

from collections.abc import Sequence

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE = len(DIGITS)
_INDEX = {c: i for i, c in enumerate(DIGITS)}

# Rank of the first tile on an empty board, kept as the midpoint of the space
# so there is equal room to prepend and to append.
FIRST = DIGITS[BASE // 2]


class InvalidRank(ValueError):
    """The string is not a usable rank."""


def is_rank(value: str) -> bool:
    """Whether a string can be compared as a rank.

    Deliberately lenient about trailing zeros: ``between`` never emits one, but
    a hand-edited file may hold one and it still orders correctly, so rejecting
    it would throw away a working position for a cosmetic reason.
    """
    return bool(value) and all(c in _INDEX for c in value)


def _digits(value: str | None) -> list[int]:
    return [_INDEX[c] for c in value] if value else []


def _render(digits: list[int]) -> str:
    return "".join(DIGITS[d] for d in digits)


def between(lo: str | None = None, hi: str | None = None) -> str:
    """A rank strictly between ``lo`` and ``hi``; None means the open end.

    Raises InvalidRank if the bounds aren't ordered, since a caller that passes
    a stale pair would otherwise get a key that silently sorts somewhere else.
    """
    for bound in (lo, hi):
        if bound is not None and not is_rank(bound):
            raise InvalidRank(f"Not a rank: {bound!r}")
    if lo is not None and hi is not None and lo >= hi:
        raise InvalidRank(f"Bounds out of order: {lo!r} >= {hi!r}")

    low = _digits(lo)
    high: list[int] | None = _digits(hi) if hi is not None else None
    out: list[int] = []
    i = 0
    while True:
        # Past the end of lo, the smallest digit still keeps us above it: any
        # continuation of a prefix sorts after the prefix itself.
        x = low[i] if i < len(low) else 0
        y = high[i] if high is not None and i < len(high) else BASE
        if y - x > 1:
            out.append((x + y) // 2)
            return _render(out)
        out.append(x)
        if y - x == 1:
            # Now strictly below hi on this digit, so hi constrains nothing
            # further — "a…" sorts before "b" whatever follows the "a".
            high = None
        i += 1


def initial(count: int) -> list[str]:
    """``count`` ranks in ascending order, spread evenly across the space.

    Used to give an existing board its first ranks. Spacing them evenly rather
    than chaining ``between`` leaves room to insert anywhere without lengthening
    a key on the first move.
    """
    if count <= 0:
        return []
    width = 1
    while BASE**width < (count + 1) * 2:  # headroom keeps the keys distinct
        width += 1
    span = BASE**width
    ranks = []
    for i in range(1, count + 1):
        value = span * i // (count + 1)
        digits = []
        for _ in range(width):
            digits.append(value % BASE)
            value //= BASE
        digits.reverse()
        # Trailing zeros carry no order, and dropping them keeps keys short
        # without changing where any of them sorts.
        ranks.append(_render(digits).rstrip(DIGITS[0]) or DIGITS[1])
    return ranks


def _spread(lo: str | None, hi: str | None, count: int) -> list[str]:
    """``count`` ranks strictly between the bounds, bisecting so they stay short."""
    if count <= 0:
        return []
    half = count // 2
    mid = between(lo, hi)
    return _spread(lo, mid, half) + [mid] + _spread(mid, hi, count - half - 1)


def repair(ranks: Sequence[str | None]) -> list[str]:
    """Ranks for the order given, rewriting as few of them as possible.

    ``ranks`` is the board in the order it should end up, holding each idea's
    current rank or None for one that has never had a rank. The result is
    strictly increasing, and every rank that was already consistent with the
    order is returned untouched — so publishing after a single tile moved
    rewrites a single file, which is the entire reason ranks are fractional.

    Keeping the most ranks means keeping a longest strictly increasing
    subsequence of the ones already set. That is quadratic here, which is the
    right trade for a board of tiles: it is obviously correct, and n is the
    number of ideas one person can look at on a screen.
    """
    n = len(ranks)
    if n == 0:
        return []

    # Longest strictly increasing run of existing ranks, tracked by predecessor.
    best = [0] * n
    prev = [-1] * n
    for i in range(n):
        if ranks[i] is None:
            continue
        best[i] = 1
        for j in range(i):
            if ranks[j] is not None and ranks[j] < ranks[i] and best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                prev[i] = j
    keep: set[int] = set()
    end = max(range(n), key=lambda i: best[i], default=-1)
    while end != -1 and best[end] > 0:
        keep.add(end)
        end = prev[end]

    out: list[str | None] = [ranks[i] if i in keep else None for i in range(n)]
    # Fill each run of gaps between the anchors that bracket it.
    i = 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        lo = out[i - 1] if i > 0 else None
        hi = out[j] if j < n else None
        for offset, value in enumerate(_spread(lo, hi, j - i)):
            out[i + offset] = value
        i = j
    return [r for r in out if r is not None]
