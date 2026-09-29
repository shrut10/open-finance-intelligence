# Public data and lineage

The repository contains real downloads from the Office for National Statistics (ONS) and Bank of England Database, retrieved **29 September 2026**. No client, personal or synthetic observations are used. `data/raw/manifest.json` records the complete download URLs, UTC retrieval time, byte counts and SHA-256 hashes. `scripts/build_data.py` validates these hashes before producing Parquet.

| Internal ID | Official code | Measure | Snapshot coverage |
|---|---|---|---|
| `cpi` | ONS D7G7, MM23 | All-items CPI 12-month inflation rate, percent | Jan 1989–Aug 2026 |
| `bank_rate` | BoE IUMABEDR | Monthly average of official Bank Rate, percent | Jan 1988–Aug 2026 |
| `m4` | BoE LPMAUYM | MFI sterling M4 liabilities to private sector, £ million, not seasonally adjusted | Jan 1988–Aug 2026 |
| `unemployment` | ONS MGSX, LMS | Unemployment aged 16+, seasonally adjusted, percent | Jan 1988–Jun 2026 centre month |

The unemployment series is a **rolling three-month estimate**. For example the observation dated June 2026 describes May–July 2026 and was released in September. `period_label` preserves this distinction in the API. Displaying it as June's single-month unemployment would be wrong. Annual CPI is price change over twelve months, not month-on-month inflation. The Bank Rate series is a monthly average, not necessarily today's policy rate.

## Sources, access and reuse

- [ONS CPI series](https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23); append `/data` to obtain official JSON. ONS documents this [site-based time-series API](https://digitalblog.ons.gov.uk/2017/07/13/api-an-introduction/).
- [ONS unemployment series](https://www.ons.gov.uk/employmentandlabourmarket/peoplenotinwork/unemployment/timeseries/mgsx/lms); append `/data` for JSON.
- [Bank of England Database download documentation](https://www.bankofengland.co.uk/boeapps/database/help.asp) and [Bank Rate history](https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp). The recorded CSV request selects IUMABEDR and LPMAUYM explicitly.
- [ONS reuse terms](https://www.ons.gov.uk/help/terms-conditions) and [Bank of England Database reuse terms](https://www.bankofengland.co.uk/legal) permit these statistical datasets under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). This does **not** mean every BoE/FCA publication is OGL; the document corpus has separate provenance and reuse notes.

Attribution: **Source: Office for National Statistics, licensed under the Open Government Licence v3.0. Source: Bank of England Database, copyright the Governor and Company of the Bank of England, licensed under the Open Government Licence v3.0.** No endorsement is implied. The software licence does not replace the original data licences.

## Reproduce and refresh

```sh
python scripts/build_data.py             # offline, exact committed raw snapshot
python scripts/train.py                  # offline, recreate evaluation and forecast
python scripts/build_data.py --refresh   # download latest official observations
python scripts/train.py                  # must follow a refresh before deployment
```

Only `--refresh` makes network requests. All source URLs are fixed in code; user input cannot redirect ingestion. Responses are size-bounded, schema-checked, parsed as data and validated before replacing raw files. Missing values are excluded, never replaced with zero. Duplicated observations, wrong codes and non-finite values fail validation. A new date alone cannot create an invented value.

`data/processed/observations.parquet` is a small, typed, long-format table:

| Column | Type | Meaning |
|---|---|---|
| `series_id` | string | One of the four documented IDs |
| `date` | date | Reference month end; unemployment uses its centre month |
| `value` | double | Value in the source's units |
| `period_label` | string | Original reporting period label |

`data/processed/metadata.json` exposes series names, source codes, units, coverage, latest values, descriptions, attribution and snapshot identity. DuckDB reads Parquet for each parameterised query using a short-lived connection. API filters cannot inject SQL and requests never modify data. Runtime requires DuckDB, not pandas or scikit-learn.

## Availability and revisions

The snapshot is **latest available history**, not a vintage database of what a forecaster knew on each past date. ONS and BoE may revise observations, change definitions or report breaks. In particular, Labour Force Survey quality, response and reweighting issues limit interpretation; M4 stock changes may include reporting effects. The model's annual M4 stock growth is not the official flow-adjusted monetary growth series.

The model makes conservative reference-month lags, but those are an approximation to historical release calendars. Historical vintage reconstruction would be required for a true real-time evaluation. An observation's `date`, the source release date and the download date are separate concepts. Read the [model card](MODEL_CARD.md) before interpreting results.
