import json

import pytest

from ofi.data import list_series, month_end, parse_boe, parse_ons, query_series


def ons_payload(items, code="D7G7"):
    return json.dumps({"description": {"cdid": code}, "months": items}).encode()


def test_ons_uses_monthly_rows_and_preserves_labour_period():
    payload = ons_payload([{"date": "2026 JUN", "value": "4.9", "label": "2026 MAY-JUL"}], "MGSX")
    assert parse_ons(payload, "unemployment") == [
        ("unemployment", "2026-06-30", 4.9, "2026 MAY-JUL")
    ]
    assert month_end(2024, 2) == "2024-02-29"


def test_missing_value_is_not_zero_and_unknown_series_fails():
    payload = ons_payload([{"date": "2026 JUN", "value": ".."}, {"date": "2026 JUL", "value": "0"}])
    assert parse_ons(payload, "cpi") == [("cpi", "2026-07-31", 0.0, "2026 JUL")]
    with pytest.raises(ValueError, match="Unexpected ONS"):
        parse_ons(payload, "unemployment")


def test_duplicate_and_nonfinite_observations_fail_closed():
    item = {"date": "2026 JUN", "value": "3"}
    with pytest.raises(ValueError, match="duplicate"):
        parse_ons(ons_payload([item, item]), "cpi")
    with pytest.raises(ValueError, match="Non-finite"):
        parse_ons(ons_payload([{"date": "2026 JUN", "value": "NaN"}]), "cpi")


def test_boe_schema_and_blank_cells():
    rows = parse_boe(b"DATE,IUMABEDR,LPMAUYM\r\n31 Jan 2026,3.75,100\r\n28 Feb 2026,3.75,\r\n")
    assert len(rows) == 3
    assert ("m4", "2026-01-31", 100.0, "31 Jan 2026") in rows
    with pytest.raises(ValueError, match="CSV columns"):
        parse_boe(b"<html>upstream error</html>")


def test_bundled_series_have_lineage_and_nonempty_ordered_observations():
    for series in list_series():
        rows = query_series(series["id"])
        assert len(rows) == series["observations"]
        assert rows[-1]["value"] == series["latest_value"]
        assert rows[-1]["date"] == series["latest_date"]
        assert [row["date"] for row in rows] == sorted(set(row["date"] for row in rows))
        assert series["source_url"].startswith("https://")
        assert series["licence"] == "Open Government Licence v3.0"


def test_queries_bound_dates_and_do_not_interpolate_sql():
    rows = query_series("cpi", "2020-01-01", "2020-12-31")
    assert len(rows) == 12
    with pytest.raises(KeyError):
        query_series("cpi' OR 1=1 --")
    with pytest.raises(ValueError):
        query_series("cpi", "2022-01-01", "2020-01-01")
    with pytest.raises(ValueError):
        query_series("cpi", "2020-01-01'; DROP TABLE observations")
