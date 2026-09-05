"""Numeric-count bucket helpers shared by the count-bucket facets.

The publishers page (/organisations) buckets publishers by how many
datasets each has (the Datasets facet over package_count), the /datasets
page buckets datasets by how many links each has (the Links facet over
resource_count), and /harvesters applies the same buckets to per-source
dataset counts. All three start from the one edge list below, so bucket
keys, labels, membership ranges and SQL CASE boundaries can't drift
apart — a "1-10" filter means the same range everywhere.

A bucket list is: 0 on its own, then inclusive ranges [1, e1],
[e1+1, e2], …, open-ended above the last edge. Publishers and datasets
are both heavily skewed small, so the low end is fine-grained and the
tail is coarse.
"""

from collections.abc import Callable

BUCKET_EDGES = (0, 10, 50, 100, 500, 1000)


def bucket_pairs(edges: tuple[int, ...] = BUCKET_EDGES) -> list[tuple[str, str]]:
    """(key, label) pairs — the facet master list. Keys double as the
    ?facet= query values and the SQL CASE bucket keys."""
    buckets: list[tuple[str, str]] = [("0", "0")]
    lo = 1
    for hi in edges[1:]:
        buckets.append((f"{lo}-{hi}", f"{lo:,}-{hi:,}"))
        lo = hi + 1
    top = edges[-1]
    buckets.append((f"{top}+", f"{top:,}+"))
    return buckets


def bucket_ranges(edges: tuple[int, ...] = BUCKET_EDGES) -> dict[str, tuple[int, int | None]]:
    """Inclusive [lo, hi] per bucket key (hi=None for the open-ended top)
    — the boundary source for both the Python membership tests and the
    SQL clauses."""
    ranges: dict[str, tuple[int, int | None]] = {}
    for value, _ in bucket_pairs(edges):
        if value == "0":
            ranges[value] = (0, 0)
        elif value.endswith("+"):
            ranges[value] = (int(value[:-1]) + 1, None)
        else:
            lo, hi = value.split("-")
            ranges[value] = (int(lo), int(hi))
    return ranges


def bucket_tests(edges: tuple[int, ...] = BUCKET_EDGES) -> dict[str, Callable[[int], bool]]:
    """The bucket membership predicates — the reference semantics the SQL
    bucket clauses must match. Consumed by the facet-pool reference tests
    and the /harvesters page's bucket helper."""
    tests: dict[str, Callable[[int], bool]] = {}
    for value, (lo, hi) in bucket_ranges(edges).items():
        if hi is None:

            def _above(n: int, lo: int = lo) -> bool:
                return n > lo

            tests[value] = _above
        else:

            def _between(n: int, lo: int = lo, hi: int = hi) -> bool:
                return lo <= n <= hi

            tests[value] = _between
    return tests


def bucket_case(column: str, edges: tuple[int, ...] = BUCKET_EDGES) -> str:
    """CASE expression mapping `column` to its bucket key — generated from
    the same ranges so the SQL boundaries can't drift. `column` is the
    caller's column expression (each page's alias differs), already
    COALESCE'd to 0 to mirror the Python `or 0`."""
    top = bucket_pairs(edges)[-1][0]
    return (
        "CASE "
        + " ".join(
            f"WHEN {column} > {lo} THEN '{value}'"
            if hi is None
            else f"WHEN {column} BETWEEN {lo} AND {hi} THEN '{value}'"
            for value, (lo, hi) in bucket_ranges(edges).items()
        )
        + f" ELSE '{top}' END"
    )
