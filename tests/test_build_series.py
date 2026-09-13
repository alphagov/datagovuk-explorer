"""Unit tests for scripts/build_series.py (offline — no database).

Covers the deterministic algorithmic core:
- strip_date: all 5 DATE_PATTERNS, first-match-wins ordering, empty-root
  rejection, re.ASCII faithfulness (fullwidth digits don't match
  the ASCII digit class)
- build_all_series: template vs timeseries typing, date-suffix clusters,
  root-length cutoff, Phase 1/Phase 2 overlap, counts, insertion order

The DB write path (_write_series) is covered by tests/test_build_series_db.py,
which runs it against a scratch migrated database.
Run with: uv run pytest tests/test_build_series.py
"""

import os

# The module-level guard fires on import if DATABASE_URL is unset — tests
# never connect, so give it a dummy URL.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import scripts.build_series as bs


def row(id_, title, org="council-a", org_name="Council A"):
    return {
        "id": id_,
        "title": title,
        "org_slug": org,
        "org_display_name": org_name,
    }


def test_strip_date_patterns():
    # 1: 2020/21, 2020-21, 2020-2021 (with and without spaces)
    assert bs.strip_date("Planning Applications 2020/21") == {
        "root": "Planning Applications",
        "date": "2020/21",
    }
    assert bs.strip_date("Planning Applications 2020-21") == {
        "root": "Planning Applications",
        "date": "2020-21",
    }
    assert bs.strip_date("Planning Applications 2020-2021") == {
        "root": "Planning Applications",
        "date": "2020-2021",
    }
    assert bs.strip_date("Planning Applications 2020 / 21") == {
        "root": "Planning Applications",
        "date": "2020 / 21",
    }
    # 2: Q-prefix quarters (optional /YY suffix)
    assert bs.strip_date("Quarterly Report Q4 2020") == {
        "root": "Quarterly Report",
        "date": "Q4 2020",
    }
    # first-match-wins: pattern 1 eats the trailing " 2020/21" before
    # pattern 2 gets a look — root keeps the Q1 prefix
    assert bs.strip_date("Quarterly Report Q1 2020/21") == {
        "root": "Quarterly Report Q1",
        "date": "2020/21",
    }
    # 3: month names
    assert bs.strip_date("Statistics January 2020") == {
        "root": "Statistics",
        "date": "January 2020",
    }
    assert bs.strip_date("Statistics December 2024") == {
        "root": "Statistics",
        "date": "December 2024",
    }
    # 4: plain year, optional parens; 19xx/20xx only
    assert bs.strip_date("Report 2020") == {"root": "Report", "date": "2020"}
    assert bs.strip_date("Report (2020)") == {"root": "Report", "date": "(2020)"}
    assert bs.strip_date("Report 1999") == {"root": "Report", "date": "1999"}
    assert bs.strip_date("Report 2100") is None  # outside 19xx/20xx
    # 5: year in parens at the very end
    assert bs.strip_date("Something (2020)") == {"root": "Something", "date": "(2020)"}
    # date string is trimmed: trailing spaces after the year are stripped
    assert bs.strip_date("Report 2020  ") == {"root": "Report", "date": "2020"}


def test_strip_date_rejects():
    # no date-like suffix at all
    assert bs.strip_date("Planning Applications") is None
    # year is not at the end
    assert bs.strip_date("2020 Annual Report") is None
    # three-digit year
    assert bs.strip_date("Report 999") is None
    # empty root -> None
    assert bs.strip_date(" 2020") is None
    assert bs.strip_date("(2020)") is None
    # misspelled month: pattern 3 skips, but pattern 4 still catches the
    # plain " 2020" at the end
    assert bs.strip_date("Report Januarry 2020") == {
        "root": "Report Januarry",
        "date": "2020",
    }
    # no date at the end at all
    assert bs.strip_date("Januarry 2020 Report") is None
    # Q0 / Q5 not valid quarters — and no bare year at the end to catch
    assert bs.strip_date("Report Q5 2020 onwards") is None


def test_strip_date_ascii():
    # re.ASCII: fullwidth digits must NOT match \d (the regex is ASCII-only).
    # ２０２０ is U+FF10..U+FF13 — Python \d without the flag would match it.
    assert bs.strip_date("Report ２０２０") is None
    assert bs.strip_date("Report ２０２０/２１") is None
    # real ASCII digits still match
    assert bs.strip_date("Report 2020") == {"root": "Report", "date": "2020"}


def test_exact_duplicates():
    rows = [
        row("a1", "Planning Applications", "council-a", "Council A"),
        row("a2", "Planning Applications", "council-a", "Council A"),
        row("a3", "Planning Applications", "council-b", "Council B"),
        row("b1", "Unique Title", "council-a", "Council A"),
    ]
    series, exact, date = bs.build_all_series(rows)
    # two exact groups of 2+: "Planning Applications" (2 orgs -> template)
    # and... "Unique Title" has 1 -> skipped
    assert exact == 1
    assert date == 0
    assert len(series) == 1
    s = series[0]
    assert s["root_title"] == "Planning Applications"
    assert s["type"] == "template"  # two orgs
    assert [d["id"] for d in s["datasets"]] == ["a1", "a2", "a3"]
    assert "date" not in s["datasets"][0]  # Phase 1 rows carry no date


def test_single_org_timeseries():
    rows = [
        row("a1", "Planning Applications 2020"),
        row("a2", "Planning Applications 2021"),
        row("a3", "Planning Applications 2022"),
    ]
    series, exact, date = bs.build_all_series(rows)
    assert exact == 0
    assert date == 1
    s = series[0]
    assert s["root_title"] == "Planning Applications"
    assert s["type"] == "timeseries"  # all same org
    dates = [d["date"] for d in s["datasets"]]
    assert dates == ["2020", "2021", "2022"]
    # original (untrimmed) titles preserved in the junction rows
    assert [d["title"] for d in s["datasets"]] == [
        "Planning Applications 2020",
        "Planning Applications 2021",
        "Planning Applications 2022",
    ]


def test_exact_duplicates_single_org_timeseries():
    # same title, all one org -> timeseries, not template
    rows = [
        row("a1", "Weekly Report", "council-a"),
        row("a2", "Weekly Report", "council-a"),
    ]
    series, exact, _ = bs.build_all_series(rows)
    assert exact == 1
    assert series[0]["type"] == "timeseries"


def test_root_length_cutoff():
    # root shorter than 5 chars is skipped in Phase 2
    rows = [
        row("a1", "R 2020"),
        row("a2", "R 2021"),
    ]
    series, exact, date = bs.build_all_series(rows)
    assert exact == 0
    assert date == 0
    assert series == []
    # single-word roots are also skipped (MIN_WORDS=2): "Stats 2020" /
    # "Stats 2021" are too vague to be a series
    rows = [
        row("a1", "Stats 2020"),
        row("a2", "Stats 2021"),
    ]
    _, _, date = bs.build_all_series(rows)
    assert date == 0
    # a two-word root of the same length passes
    rows = [
        row("a1", "Farm Stats 2020"),
        row("a2", "Farm Stats 2021"),
    ]
    _, _, date = bs.build_all_series(rows)
    assert date == 1


def test_range_patterns():
    # year ranges: "1990 to 2018" is stripped whole, no dangling "to"
    assert bs.strip_date("River Water Quality Monitoring 1990 to 2018") == {
        "root": "River Water Quality Monitoring",
        "date": "1990 to 2018",
    }
    # month ranges: "January 2009 to December 2009" stripped whole
    assert bs.strip_date(
        "Birth registrations by month since January 2009 to December 2009",
    ) == {
        "root": "Birth registrations by month",
        "date": "January 2009 to December 2009",
    }
    rows = [
        row("a1", "River Water Quality Monitoring 1990 to 2018"),
        row("a2", "River Water Quality Monitoring 2000 to 2010"),
    ]
    series, _, date = bs.build_all_series(rows)
    assert date == 1
    assert series[0]["root_title"] == "River Water Quality Monitoring"


def test_connector_trimming():
    # trailing connectors left by date stripping are trimmed from the root
    assert bs.strip_date("UK Public Procurement Notices - April 2021") == {
        "root": "UK Public Procurement Notices",
        "date": "April 2021",
    }
    assert bs.strip_date("NHS Kent and Medway CCG Expenditure for 2020/21") == {
        "root": "NHS Kent and Medway CCG Expenditure",
        "date": "2020/21",
    }
    assert bs.strip_date("LCHS Spend Over 25K as of 2020") == {
        "root": "LCHS Spend Over 25K",
        "date": "2020",
    }


def test_punct_normalize_phase1():
    # case/punctuation variants of the same title group together; the series
    # root shows the dominant natural spelling, not the first-seen variant
    rows = [
        row("a1", "Conservation Areas", "council-a", "Council A"),
        row("a2", "CONSERVATION AREAS", "council-b", "Council B"),
        row("a3", "conservation_areas", "council-c", "Council C"),
        row("b1", "Tree Preservation Orders", "council-d", "Council D"),
    ]
    series, exact, date = bs.build_all_series(rows)
    assert exact == 1
    assert date == 0
    assert len(series) == 1
    s = series[0]
    assert s["type"] == "template"
    assert s["root_title"] == "Conservation Areas"  # natural spelling wins
    assert [d["id"] for d in s["datasets"]] == ["a1", "a2", "a3"]

    # the dominant spelling wins over a first-seen snake_case one
    rows = [
        row("a1", "air_quality_management_areas", "council-a", "Council A"),
        row("a2", "Air Quality Management Areas", "council-b", "Council B"),
        row("a3", "Air Quality Management Areas", "council-c", "Council C"),
    ]
    series, _, _ = bs.build_all_series(rows)
    assert series[0]["root_title"] == "Air Quality Management Areas"


def test_filename_rejection_phase2():
    # snake_case / filename roots are not date-cluster series
    rows = [
        row("a1", "BGS_multibeam 2009"),
        row("a2", "BGS_multibeam 2010"),
    ]
    series, exact, date = bs.build_all_series(rows)
    assert exact == 0
    assert date == 0
    assert series == []
    # a bare dot is NOT filename evidence ("No.", "£25,000 per transaction.")
    rows = [
        row("a1", "TSE Surveillance No. of Cattle 2009"),
        row("a2", "TSE Surveillance No. of Cattle 2010"),
    ]
    _, _, date = bs.build_all_series(rows)
    assert date == 1


def test_timeseries_growth():
    # a decent timeseries seed (>=4 datasets, 2+ word root) pulls in
    # residual datasets whose titles contain the root AND a year token
    rows = [
        row("a1", "Planning Applications 2019", "wigan", "Wigan Council"),
        row("a2", "Planning Applications 2020", "wigan", "Wigan Council"),
        row("a3", "Planning Applications 2021", "wigan", "Wigan Council"),
        row("a4", "Planning Applications 2022", "wigan", "Wigan Council"),
        # residual: contains root + year, but no recognised date suffix
        row("b1", "Allerdale Planning Applications from 2000", "allerdale", "Allerdale"),
        row("b2", "London Borough of Harrow Planning Applications 2014", "harrow", "Harrow"),
        # residual WITHOUT a year must NOT join
        row("c1", "Planning Applications Guidance", "some-org", "Some Org"),
        # already in an exact group (template) must NOT be grown — not
        # date-strippable either, so it would otherwise be a candidate
        row("e1", "Camden Planning Applications (2014 data)", "camden", "Camden"),
        row("e2", "Camden Planning Applications (2014 data)", "westminster", "Westminster"),
    ]
    series, exact, _ = bs.build_all_series(rows)
    assert exact == 1  # e1/e2 template
    ts = [s for s in series if s["type"] == "timeseries"]
    assert len(ts) == 1
    ids = {d["id"] for d in ts[0]["datasets"]}
    assert ids == {"a1", "a2", "a3", "a4", "b1", "b2"}
    grown = {d["id"]: d["date"] for d in ts[0]["datasets"] if d["id"] in ("b1", "b2")}
    assert grown["b1"] == "2000"
    assert grown["b2"] == "2014"


def test_timeseries_growth_overlap():
    # a dataset can be both an exact-duplicate template member AND part of a
    # date-cluster timeseries ("Planning Applications 2023" by two councils
    # is in the template AND Wigan's year-by-year series) — existing overlap
    # behaviour, unchanged by growth
    rows = [
        row("a1", "Planning Applications 2019", "wigan", "Wigan Council"),
        row("a2", "Planning Applications 2020", "wigan", "Wigan Council"),
        row("a3", "Planning Applications 2021", "wigan", "Wigan Council"),
        row("a4", "Planning Applications 2022", "wigan", "Wigan Council"),
        row("d1", "Planning Applications 2023", "wigan", "Wigan Council"),
        row("d2", "Planning Applications 2023", "other", "Other Council"),
    ]
    series, exact, _ = bs.build_all_series(rows)
    assert exact == 1  # d1/d2 template
    ts = [s for s in series if s["type"] == "timeseries"]
    assert {d["id"] for d in ts[0]["datasets"]} == {"a1", "a2", "a3", "a4", "d1", "d2"}


def test_timeseries_growth_seed_threshold():
    # a 3-dataset timeseries is not a decent seed — nothing grows
    rows = [
        row("a1", "Monthly Report 2020", "org-a"),
        row("a2", "Monthly Report 2021", "org-a"),
        row("a3", "Monthly Report 2022", "org-a"),
        row("b1", "Monthly Report June 2020 edition", "org-b"),
    ]
    series, _, _ = bs.build_all_series(rows)
    ts = [s for s in series if s["type"] == "timeseries"]
    assert len(ts) == 1
    assert {d["id"] for d in ts[0]["datasets"]} == {"a1", "a2", "a3"}


def test_year_tail():
    assert bs._year_tail("TAUNTON AND SOMERSET NHS PUBLICATION OF SPEND OVER £25K JANUARY 2017") == ("JANUARY 2017")
    assert bs._year_tail("UK (2011-2013)") == "(2011-2013)"
    assert bs._year_tail("Flower counts 2017-2020 version 2") == "2017-2020 version 2"
    assert bs._year_tail("No year here") is None


def test_grown_date():
    # year-prefixed titles carry the root in the tail; it's stripped out
    assert bs._grown_date("2019 Hazardous Waste Interrogator", "hazardous waste interrogator") == "2019"
    assert (
        bs._grown_date(
            "TAUNTON AND SOMERSET NHS PUBLICATION OF SPEND OVER £25K JANUARY 2017",
            "taunton and somerset nhs publication of spend over 25k",
        )
        == "JANUARY 2017"
    )
    assert bs._grown_date("UK (2011-2013)", "sulphur data for the uk") == "(2011-2013)"
    assert bs._grown_date("No year", "some root") is None


def test_phase_overlap():
    # "Planning Applications" is BOTH an exact
    # template across many councils AND a single council's year-by-year
    # timeseries. Overlap is intentional — separate series entries.
    rows = [
        # exact-duplicate template: same title, 3 councils
        row("t1", "Planning Applications", "council-a", "Council A"),
        row("t2", "Planning Applications", "council-b", "Council B"),
        row("t3", "Planning Applications", "council-c", "Council C"),
        # Wigan year-by-year: date suffix, same org
        row("w1", "Planning Applications 2020", "wigan", "Wigan Council"),
        row("w2", "Planning Applications 2021", "wigan", "Wigan Council"),
        row("w3", "Planning Applications 2022", "wigan", "Wigan Council"),
    ]
    series, exact, date = bs.build_all_series(rows)
    assert exact == 1
    assert date == 1
    assert len(series) == 2
    # Phase 1 first, then Phase 2 (insertion order — fixes SERIAL ids)
    assert series[0]["root_title"] == "Planning Applications"
    assert series[0]["type"] == "template"
    assert series[1]["root_title"] == "Planning Applications"
    assert series[1]["type"] == "timeseries"
    assert [d["id"] for d in series[1]["datasets"]] == ["w1", "w2", "w3"]


def test_order_and_counts():
    rows = [
        row("a1", "Beta Report 2020"),
        row("a2", "Beta Report 2021"),
        row("a3", "Alpha"),  # inserted after Beta rows, but exact group sorts first
        row("a4", "Alpha"),
        row("c1", "Gamma Report 2020"),
        row("c2", "Gamma Report 2021"),
    ]
    series, exact, date = bs.build_all_series(rows)
    assert exact == 1  # Alpha
    assert date == 2  # Beta Report, Gamma Report
    # Phase 1 groups first (exact_groups insertion order), then Phase 2
    # (root_groups insertion order): Alpha, Beta Report, Gamma Report
    assert [s["root_title"] for s in series] == [
        "Alpha",
        "Beta Report",
        "Gamma Report",
    ]
    assert [s["type"] for s in series] == ["timeseries", "timeseries", "timeseries"]
