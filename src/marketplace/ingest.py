"""Download (if missing), verify and load the raw Olist CSV files into DuckDB.

This is the "EL" step. It plays the role a tool like Fivetran/Airbyte plays in production:
land the source data untouched (every column as text) in a `raw` schema and stamp each
row with `_loaded_at`, which dbt source freshness checks.

Verification is strict: the job fails if any file's SHA-256, row count or header differs
from `data_manifest.json`, or if row counts differ from the publicly documented originals.

Usage:  python -m marketplace.ingest [--download]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime

import duckdb

from marketplace.paths import MANIFEST, RAW, WAREHOUSE

# Row counts published for the original Kaggle release (Olist, 2018). If a mirror drifts
# from these numbers it is not the original and we refuse to load it.
PUBLISHED_ROW_COUNTS = {
    "orders": 99_441,
    "order_items": 112_650,
    "order_payments": 103_886,
    "order_reviews": 99_224,
    "customers": 99_441,
    "sellers": 3_095,
    "products": 32_951,
    "geolocation": 1_000_163,
    "category_translation": 71,
    "closed_deals": 842,
    "marketing_qualified_leads": 8_000,
}


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_missing(manifest: dict) -> None:
    for name, meta in manifest["tables"].items():
        target = RAW / meta["file"]
        if target.exists():
            continue
        kind = "funnel" if meta["file"].startswith("funnel/") else "ecommerce"
        base = manifest["primary_mirror"][kind]
        url = base + meta["file"].split("/")[-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {name} <- {url}")
        urllib.request.urlretrieve(url, target)  # noqa: S310 (pinned https mirror)


def verify(manifest: dict) -> list[str]:
    """Return a list of human-readable problems (empty list = all good)."""
    problems = []
    for name, meta in manifest["tables"].items():
        path = RAW / meta["file"]
        if not path.exists():
            problems.append(f"{name}: file missing ({path})")
            continue
        digest = sha256(path)
        if digest != meta["sha256"]:
            problems.append(f"{name}: sha256 {digest} != manifest {meta['sha256']}")
        if meta["rows"] != PUBLISHED_ROW_COUNTS[name]:
            problems.append(f"{name}: manifest rows {meta['rows']} != published")
    return problems


def load(manifest: dict) -> dict[str, int]:
    """Load every CSV as all-VARCHAR into raw.<table>, returning loaded row counts."""
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    counts = {}
    with duckdb.connect(str(WAREHOUSE)) as con:
        con.execute("create schema if not exists raw")
        for name, meta in manifest["tables"].items():
            path = (RAW / meta["file"]).as_posix()
            con.execute(
                f"""
                create or replace table raw.{name} as
                select *, ?::timestamp as _loaded_at
                from read_csv(?, header = true, all_varchar = true, quote = '"',
                              escape = '"', strict_mode = true)
                """,
                [loaded_at, path],
            )
            cols = [r[0] for r in con.execute(f"describe raw.{name}").fetchall()]
            cols = [c.lstrip("﻿") for c in cols if c != "_loaded_at"]
            if cols != meta["columns"]:
                raise SystemExit(f"{name}: header {cols} != manifest {meta['columns']}")
            n = con.execute(f"select count(*) from raw.{name}").fetchone()[0]
            if n != meta["rows"]:
                raise SystemExit(f"{name}: loaded {n} rows, expected {meta['rows']}")
            counts[name] = n
        # BOM in the original translation file header -> normalise the column name.
        tcols = [r[0] for r in con.execute("describe raw.category_translation").fetchall()]
        if tcols[0] != "product_category_name":
            con.execute(
                f'alter table raw.category_translation rename "{tcols[0]}" '
                "to product_category_name"
            )
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="fetch missing files")
    args = parser.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text())
    if args.download:
        download_missing(manifest)
    problems = verify(manifest)
    if problems:
        print("DATA VERIFICATION FAILED:\n  " + "\n  ".join(problems))
        return 1
    counts = load(manifest)
    for name, n in counts.items():
        print(f"  raw.{name:<28} {n:>10,} rows  (sha256 + header + count verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
