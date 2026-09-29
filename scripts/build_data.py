#!/usr/bin/env python3
"""Build Parquet offline from the bundled official snapshot; --refresh fetches new data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import duckdb  # noqa: E402

from ofi.data import (  # noqa: E402
    BOE_URL,
    OGL,
    PARQUET,
    PROCESSED,
    RAW,
    SERIES,
    parse_boe,
    parse_ons,
)

SOURCES = {
    "boe.csv": BOE_URL,
    "ons_cpi.json": SERIES["cpi"]["source_url"] + "/data",
    "ons_unemployment.json": SERIES["unemployment"]["source_url"] + "/data",
}


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def refresh() -> None:
    """Validate the entire response set before replacing the local snapshot."""
    fetched = {}
    for filename, url in SOURCES.items():
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "OpenFinanceIntelligence/1.0 (educational open-data project)"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            fetched[filename] = response.read(5_000_001)
        if len(fetched[filename]) > 5_000_000:
            raise ValueError(f"Unexpected response size: {filename}")
    parse_boe(fetched["boe.csv"])
    parse_ons(fetched["ons_cpi.json"], "cpi")
    parse_ons(fetched["ons_unemployment.json"], "unemployment")
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "files": []}
    for filename, payload in fetched.items():
        (RAW / filename).write_bytes(payload)
        manifest["files"].append(
            {
                "path": filename,
                "url": SOURCES[filename],
                "sha256": sha256(payload),
                "bytes": len(payload),
            }
        )
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def build() -> dict:
    manifest = json.loads((RAW / "manifest.json").read_text())
    for entry in manifest["files"]:
        if sha256((RAW / entry["path"]).read_bytes()) != entry["sha256"]:
            raise ValueError(f"Snapshot integrity check failed: {entry['path']}")
    rows = parse_boe((RAW / "boe.csv").read_bytes())
    rows += parse_ons((RAW / "ons_cpi.json").read_bytes(), "cpi")
    rows += parse_ons((RAW / "ons_unemployment.json").read_bytes(), "unemployment")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    temporary = PARQUET.with_suffix(".tmp.parquet")
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE observations(series_id VARCHAR, date DATE, value DOUBLE, period_label VARCHAR)"
        )
        connection.executemany("INSERT INTO observations VALUES (?, ?, ?, ?)", rows)
        connection.execute(
            "COPY (SELECT * FROM observations ORDER BY series_id, date) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(temporary)],
        )
    temporary.replace(PARQUET)
    metadata = {
        "retrieved_at": manifest["retrieved_at"],
        "snapshot_sha256": sha256((RAW / "manifest.json").read_bytes()),
        "series": [],
    }
    for series_id, definition in SERIES.items():
        observations = sorted((r for r in rows if r[0] == series_id), key=lambda r: r[1])
        metadata["series"].append(
            {
                "id": series_id,
                **{k: v for k, v in definition.items() if k != "filename"},
                "first_date": observations[0][1],
                "latest_date": observations[-1][1],
                "latest_value": observations[-1][2],
                "latest_period_label": observations[-1][3],
                "observations": len(observations),
                "retrieved_at": manifest["retrieved_at"],
                "licence": "Open Government Licence v3.0",
                "licence_url": OGL,
                "attribution": "Source: Office for National Statistics, licensed under the Open Government Licence v3.0."
                if definition["source"] == "ONS"
                else "Source: Bank of England Database. Copyright the Governor and Company of the Bank of England, licensed under the Open Government Licence v3.0.",
            }
        )
    (PROCESSED / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Download latest official observations (network required)",
    )
    args = parser.parse_args()
    if args.refresh:
        refresh()
    result = build()
    print(
        json.dumps(
            {
                s["id"]: {"observations": s["observations"], "latest_date": s["latest_date"]}
                for s in result["series"]
            },
            indent=2,
        )
    )
