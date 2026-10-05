"""Unit tests for scripts/ingest_views.py (offline — no database).

Covers load_views_csv: the three-source combination logic, consent-rate
scaling, capping at 1.0, floor application, and missing-file handling.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/test-db")

import scripts.ingest_views as iv


def test_load_views_csv(tmp_path, monkeypatch):
    nope = tmp_path / "nope.csv"
    # missing files -> empty dict
    monkeypatch.setattr(iv, "VIEWS_FILE", nope)
    monkeypatch.setattr(iv, "GA_PAGE_VIEWS_FILE", nope)
    monkeypatch.setattr(iv, "GA_GOOGLE_LANDING_FILE", nope)
    assert iv.load_views_csv() == {}

    uid_a = "aaaaaaaa-1111-2222-3333-444444444444"  # overlap: consent rate scales
    uid_b = "bbbbbbbb-1111-2222-3333-444444444444"  # non-overlap: no GA landing
    uid_c = "cccccccc-1111-2222-3333-444444444444"  # consent rate > 1: capped

    # Search Console clicks
    sc_file = tmp_path / "sc.csv"
    sc_file.write_text(
        "Landing Page,Url Clicks\n"
        f"https://www.data.gov.uk/dataset/{uid_a}/slug,10\n"
        f"https://www.data.gov.uk/dataset/{uid_a}/slug,5\n"
        f"https://www.data.gov.uk/dataset/{uid_b}/other,3\n"
        f"https://www.data.gov.uk/dataset/{uid_c}/thing,10\n"
        "https://www.data.gov.uk/,100\n"  # homepage - skipped
        f"https://www.data.gov.uk/dataset/{uid_b}/other,0\n",  # zero - skipped
        encoding="utf-8",
    )
    # GA page views (with comment header)
    ga_views_file = tmp_path / "ga-views.csv"
    ga_views_file.write_text(
        "# comment\n"
        "\n"
        "Page path and screen class,Views\n"
        f"/dataset/{uid_a}/slug,20\n"
        f"/dataset/{uid_b}/other,6\n"
        f"/dataset/{uid_c}/thing,30\n"
        "/search,999\n",  # non-dataset - skipped
        encoding="utf-8",
    )
    # GA Google landing sessions
    ga_landing_file = tmp_path / "ga-landing.csv"
    ga_landing_file.write_text(
        "# comment\n"
        "\n"
        "Landing page,Sessions\n"
        f"/dataset/{uid_a}/slug,4\n"
        f"/dataset/{uid_c}/thing,15\n",  # 15 > 10 SC clicks: consent > 1
        encoding="utf-8",
    )
    monkeypatch.setattr(iv, "VIEWS_FILE", sc_file)
    monkeypatch.setattr(iv, "GA_PAGE_VIEWS_FILE", ga_views_file)
    monkeypatch.setattr(iv, "GA_GOOGLE_LANDING_FILE", ga_landing_file)
    result = iv.load_views_csv()
    # uid_a (overlap): consent_rate = 4/15 = 0.267, non_google = 20-4 = 16,
    #   scaled = round(16/0.267) = 60, total = 60 + 15 = 75
    assert result[uid_a] == 75
    # uid_b (non-overlap, no GA landing): 6 - 0 + 3 = 9
    assert result[uid_b] == 9
    # uid_c (consent > 1, capped at 1.0): non_google = 30-15 = 15,
    #   scaled = round(15/1.0) = 15, total = 15 + 10 = 25
    assert result[uid_c] == 25


def test_load_views_csv_consent_rate_floor(tmp_path, monkeypatch):
    """A low-sample page must not inflate its views without bound.

    Regression for F4 in docs/analytics-consent-plan.md: a tiny landing
    count against many SC clicks produced multipliers up to ~230x.
    """
    uid = "dddddddd-1111-2222-3333-444444444444"  # rate 5% -> floored to 10%

    sc_file = tmp_path / "sc.csv"
    sc_file.write_text(
        f"Landing Page,Url Clicks\nhttps://www.data.gov.uk/dataset/{uid}/slug,100\n",
        encoding="utf-8",
    )
    ga_views_file = tmp_path / "ga-views.csv"
    ga_views_file.write_text(
        f"Page path and screen class,Views\n/dataset/{uid}/slug,50\n",
        encoding="utf-8",
    )
    ga_landing_file = tmp_path / "ga-landing.csv"
    ga_landing_file.write_text(
        f"Landing page,Sessions\n/dataset/{uid}/slug,5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(iv, "VIEWS_FILE", sc_file)
    monkeypatch.setattr(iv, "GA_PAGE_VIEWS_FILE", ga_views_file)
    monkeypatch.setattr(iv, "GA_GOOGLE_LANDING_FILE", ga_landing_file)

    result = iv.load_views_csv()
    # rate = 5/100 = 0.05, floored to 0.10; non_google = 50-5 = 45,
    #   scaled = round(45/0.10) = 450, total = 450 + 100 = 550
    # Without the floor this would be round(45/0.05) + 100 = 1,000.
    assert result[uid] == 550
