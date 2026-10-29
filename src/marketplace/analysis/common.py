"""Shared helpers for analyses: DB connection, JSON output, analysis window."""

from __future__ import annotations

import json
import math

import duckdb
import numpy as np
import pandas as pd

from marketplace.paths import REPORTS, WAREHOUSE

# Olist order capture is sparse before Jan-2017 (Sep/Oct 2016 pilot, Nov 2016 missing) and
# stops abruptly after Aug-2018. Analyses default to this reliable window.
WINDOW_START = "2017-01-01"
WINDOW_END = "2018-08-31"


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE), read_only=True)


def df(sql: str, con=None) -> pd.DataFrame:
    own = con is None
    con = con or connect()
    try:
        return con.execute(sql).df()
    finally:
        if own:
            con.close()


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [_clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating | float):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, pd.DataFrame):
        return _clean(o.to_dict(orient="records"))
    if isinstance(o, pd.Series):
        return {str(k): _clean(v) for k, v in o.items()}
    return o


def write_report(name: str, payload: dict) -> None:
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{name}.json").write_text(json.dumps(_clean(payload), indent=2, default=str))
    print(f"wrote reports/{name}.json")


def read_report(name: str) -> dict:
    return json.loads((REPORTS / f"{name}.json").read_text())
