"""Estimate the GA cookie-consent (opt-in) rate by comparing GA landing
sessions with Search Console clicks for the same pages.

Both measure Google arrivals — SC counts every click, GA only counts
users who accepted tracking. The ratio ga_landing / sc_clicks
approximates the consent rate.

Usage: python -m scripts.consent_rate
"""

import csv
import itertools
import re
import statistics
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
SC_FILE = _DATA / "console-clicks-apr-aug.csv"
GA_LANDING_FILE = _DATA / "ga-google-landing-apr-aug.csv"

_UUID_PART = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

SC_ONLY_MIN_CLICKS = 100
MIN_CLICKS = 10
MIN_BUCKET_PAGES = 3

_SC_RE = re.compile(rf"https://www\.data\.gov\.uk/dataset/({_UUID_PART})")
_GA_RE = re.compile(rf"/dataset/({_UUID_PART})")


def _read_sc() -> dict[str, int]:
    result: dict[str, int] = {}
    with SC_FILE.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            m = _SC_RE.match(row["Landing Page"])
            if not m:
                continue
            clicks = int(row["Url Clicks"])
            if clicks > 0:
                uid = m.group(1)
                result[uid] = result.get(uid, 0) + clicks
    return result


def _read_ga_landing() -> dict[str, int]:
    result: dict[str, int] = {}
    with GA_LANDING_FILE.open(encoding="utf-8", newline="") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                break
        for row in csv.DictReader(itertools.chain([line], f)):
            raw = row["Landing page"]
            if not raw:
                continue
            m = _GA_RE.search(raw)
            if not m:
                continue
            val = int(row["Sessions"])
            if val > 0:
                uid = m.group(1)
                result[uid] = result.get(uid, 0) + val
    return result


def _percentile(sorted_vals: list[float], p: int) -> float:
    idx = int(len(sorted_vals) * p / 100)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


def _bucket_label(lo: int, hi: int | None) -> str:
    if hi is None:
        return f"{lo}+"
    return f"{lo}-{hi - 1}"


def _print_bucket_table(sc: dict[str, int], ga: dict[str, int], overlap: set[str]) -> None:
    buckets: list[tuple[int, int | None]] = [
        (10, 50),
        (50, 200),
        (200, 1000),
        (1000, 5000),
        (5000, None),
    ]
    print(f"{'SC clicks':>12}  {'pages':>6}  {'median':>7}  {'p25':>7}  {'p75':>7}  {'stdev':>7}  {'rate':>7}")
    print(f"{'':>12}  {'':>6}  {'':>7}  {'':>7}  {'':>7}  {'':>7}  {'(agg)':>7}")
    print("-" * 70)
    for lo, hi in buckets:
        pairs = [(ga[uid], sc[uid]) for uid in overlap if sc[uid] >= lo and (hi is None or sc[uid] < hi)]
        if len(pairs) < MIN_BUCKET_PAGES:
            continue
        ratios = sorted(g / c for g, c in pairs)
        agg_ga = sum(g for g, _ in pairs)
        agg_sc = sum(c for _, c in pairs)
        print(
            f"{_bucket_label(lo, hi):>12}  "
            f"{len(pairs):>6}  "
            f"{_percentile(ratios, 50):>6.1%}  "
            f"{_percentile(ratios, 25):>6.1%}  "
            f"{_percentile(ratios, 75):>6.1%}  "
            f"{statistics.stdev(ratios):>6.1%}  "
            f"{agg_ga / agg_sc:>6.1%}",
        )


def _print_distribution(sc: dict[str, int], ga: dict[str, int], overlap: set[str]) -> None:
    ratios_all = sorted(ga[u] / sc[u] for u in overlap if sc[u] >= MIN_CLICKS)
    if not ratios_all:
        return
    print(f"Distribution of consent rate (pages with {MIN_CLICKS}+ SC clicks, n={len(ratios_all):,}):")
    print()
    band_pct = 2
    max_pct = 50
    n_bands = max_pct // band_pct
    counts = [0] * (n_bands + 1)
    for r in ratios_all:
        counts[min(int(r * 100) // band_pct, n_bands)] += 1
    max_count = max(counts)
    bar_width = 40
    for i, n in enumerate(counts):
        lo = i * band_pct / 100
        label = f"{lo:>5.0%}+     " if i == n_bands else f"{lo:>5.0%}-{lo + band_pct / 100:<5.0%}"
        bar_len = int(n / max_count * bar_width) if max_count else 0
        print(f"  {label}  {'█' * bar_len}  {n}")


def main() -> None:
    sc = _read_sc()
    ga = _read_ga_landing()
    overlap = ga.keys() & sc.keys()
    sc_only = {u for u in sc.keys() - ga.keys() if sc[u] > SC_ONLY_MIN_CLICKS}

    print(f"Datasets in Search Console:  {len(sc):,}")
    print(f"Datasets in GA landing:      {len(ga):,}")
    print(f"Datasets in both:            {len(overlap):,}")
    print(f"SC-only (>100 clicks):       {len(sc_only):,}  ({sum(sc[u] for u in sc_only):,} clicks)")
    print()

    # ── Overall (overlap only) ───────────────────────────────────────
    total_ga = sum(ga[u] for u in overlap)
    total_sc = sum(sc[u] for u in overlap)
    all_ratios = sorted(ga[u] / sc[u] for u in overlap if sc[u] >= MIN_CLICKS)
    print(f"Total GA landing sessions:   {total_ga:,}")
    print(f"Total SC clicks:             {total_sc:,}")
    print(f"Aggregate consent rate:      {total_ga / total_sc:.1%}")
    print(f"Median consent rate (10+):   {statistics.median(all_ratios):.1%}")

    # ── Including SC-only zeros (>100 clicks) ────────────────────────
    total_sc_incl = total_sc + sum(sc[u] for u in sc_only)
    ratios_incl = sorted(
        [ga[u] / sc[u] for u in overlap if sc[u] >= MIN_CLICKS] + [0.0] * len(sc_only),
    )
    print()
    print("Including SC-only >100 as 0% consent:")
    print(f"  Aggregate consent rate:    {total_ga / total_sc_incl:.1%}")
    print(f"  Median consent rate:       {statistics.median(ratios_incl):.1%}")
    print()

    # ── By volume bucket ─────────────────────────────────────────────
    _print_bucket_table(sc, ga, overlap)
    print()

    # ── Distribution ─────────────────────────────────────────────────
    _print_distribution(sc, ga, overlap)


if __name__ == "__main__":
    main()
