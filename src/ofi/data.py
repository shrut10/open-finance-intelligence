"""Versioned official data, strict parsing, and parameterised DuckDB queries."""

from __future__ import annotations

import calendar
import csv
import io
import json
import math
from datetime import date, datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PARQUET = PROCESSED / "observations.parquet"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
BOE_URL = (
    "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?"
    "csv.x=yes&Datefrom=01/Jan/1988&Dateto=now&SeriesCodes=IUMABEDR,LPMAUYM"
    "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
)
SERIES = {
    "cpi": {
        "name": "CPI inflation",
        "unit": "% year on year",
        "source": "ONS",
        "source_code": "D7G7",
        "frequency": "monthly",
        "filename": "ons_cpi.json",
        "source_url": "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23",
        "description": "All-items Consumer Prices Index annual rate; not monthly price growth.",
    },
    "bank_rate": {
        "name": "Bank Rate (monthly average)",
        "unit": "%",
        "source": "Bank of England",
        "source_code": "IUMABEDR",
        "frequency": "monthly",
        "filename": "boe.csv",
        "source_url": "https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp",
        "description": "Monthly average of official Bank Rate; may differ from today's policy rate.",
    },
    "m4": {
        "name": "M4 money stock",
        "unit": "£ million",
        "source": "Bank of England",
        "source_code": "LPMAUYM",
        "frequency": "monthly",
        "filename": "boe.csv",
        "source_url": BOE_URL,
        "description": "MFI sterling M4 liabilities to the private sector, not seasonally adjusted. The model uses 12-month growth in this stock, not an official flow-adjusted growth series.",
    },
    "unemployment": {
        "name": "Unemployment rate",
        "unit": "%",
        "source": "ONS",
        "source_code": "MGSX",
        "frequency": "monthly, rolling three-month estimate",
        "filename": "ons_unemployment.json",
        "source_url": "https://www.ons.gov.uk/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms",
        "description": "Aged 16+, seasonally adjusted. Date is the CENTRE month of a rolling three-month period; this is not a single-month estimate. Labour Force Survey estimates are subject to quality limitations and revisions.",
    },
}


def month_end(year: int, month: int) -> str:
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def _number(value: str) -> float | None:
    if value.strip() in {"", "..", "...", "n/a", "NA"}:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite official observation")
    return number


def parse_ons(payload: bytes, series_id: str) -> list[tuple[str, str, float, str]]:
    """Read months only; preserve the ONS period label (important for MGSX)."""
    document = json.loads(payload)
    if document.get("description", {}).get("cdid", "").upper() != SERIES[series_id]["source_code"]:
        raise ValueError(f"Unexpected ONS series for {series_id}")
    rows = []
    for item in document["months"]:
        number = _number(item["value"])
        if number is None:
            continue
        period = datetime.strptime(item["date"], "%Y %b")
        if period.year >= 1988:
            rows.append(
                (
                    series_id,
                    month_end(period.year, period.month),
                    number,
                    item.get("label", item["date"]),
                )
            )
    return _validate_rows(rows)


def parse_boe(payload: bytes) -> list[tuple[str, str, float, str]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    if not {"DATE", "IUMABEDR", "LPMAUYM"}.issubset(set(reader.fieldnames or [])):
        raise ValueError("Unexpected Bank of England CSV columns")
    rows = []
    for item in reader:
        period = datetime.strptime(item["DATE"].strip(), "%d %b %Y")
        for series_id in ("bank_rate", "m4"):
            number = _number(item[SERIES[series_id]["source_code"]])
            if number is not None:
                rows.append((series_id, month_end(period.year, period.month), number, item["DATE"]))
    return _validate_rows(rows)


def _validate_rows(rows: list[tuple[str, str, float, str]]) -> list[tuple[str, str, float, str]]:
    keys = [(row[0], row[1]) for row in rows]
    if not rows or len(keys) != len(set(keys)):
        raise ValueError("Empty or duplicate observations")
    return sorted(rows)


def list_series() -> list[dict]:
    return json.loads((PROCESSED / "metadata.json").read_text())["series"]


def query_series(series_id: str, start: str | None = None, end: str | None = None) -> list[dict]:
    if series_id not in SERIES:
        raise KeyError(series_id)
    for value in (start, end):
        if value is not None:
            date.fromisoformat(value)
    if start and end and start > end:
        raise ValueError("start must be before or equal to end")
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(
            "SELECT date, value, period_label FROM read_parquet(?) WHERE series_id = ? "
            "AND (? IS NULL OR date >= CAST(? AS DATE)) AND (? IS NULL OR date <= CAST(? AS DATE)) ORDER BY date",
            [str(PARQUET), series_id, start, start, end, end],
        ).fetchall()
    return [
        {"date": d.isoformat(), "value": value, "period_label": label} for d, value, label in result
    ]
