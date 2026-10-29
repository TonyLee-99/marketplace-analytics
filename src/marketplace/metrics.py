"""Governed metrics layer: compile metric definitions in metrics/metrics.yml to SQL.

Consumers never write KPI formulas themselves; they call `compute()` (or read the
materialised `metrics.metric_values` table) and get the same number everywhere.

    from marketplace.metrics import MetricsLayer
    ml = MetricsLayer.load()
    df = ml.compute(["gmv", "aov"], grain="month", where={"customer_state": "SP"})

Run as a script to materialise monthly/daily/all-time values and the metrics catalog:
    python -m marketplace.metrics
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field

import duckdb
import pandas as pd
import yaml

from marketplace.paths import DOCS, METRICS_YAML, REPORTS, WAREHOUSE

GRAINS = {"day", "week", "month", "quarter", "year", "all"}
AGGS = {"sum", "count", "count_distinct", "avg"}


def _measure_sql(m: dict) -> str:
    agg, expr, flt = m["agg"], m["expr"], m.get("filter", "true")
    if agg not in AGGS:
        raise ValueError(f"unknown agg {agg}")
    if agg == "count_distinct":
        core = f"count(distinct {expr})"
    elif agg == "count":
        core = f"count({expr})"
    else:
        core = f"{agg}({expr})"
    return f"{core} filter (where {flt})"


@dataclass
class MetricsLayer:
    spec: dict
    db_path: str = str(WAREHOUSE)
    _con: duckdb.DuckDBPyConnection | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path=METRICS_YAML, db_path=None) -> MetricsLayer:
        spec = yaml.safe_load(open(path))
        layer = cls(spec=spec, db_path=str(db_path or WAREHOUSE))
        layer.validate()
        return layer

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._con = duckdb.connect(self.db_path, read_only=True)
        return self._con

    @property
    def metrics(self) -> dict[str, dict]:
        return {m["name"]: m for m in self.spec["metrics"]}

    def validate(self) -> None:
        required = {"name", "label", "type", "unit", "owner", "grain", "definition", "caveats"}
        for m in self.spec["metrics"]:
            missing = required - m.keys()
            if missing:
                raise ValueError(f"metric {m.get('name')} missing {missing}")
            if m["type"] in {"simple", "ratio", "concentration"} and m["model"] not in self.spec[
                "models"
            ]:
                raise ValueError(f"metric {m['name']} uses unknown model {m['model']}")
            if m["type"] == "derived":
                for dep in re.findall(r"[a-z_][a-z0-9_]*", m["formula"]):
                    if dep not in self.metrics:
                        raise ValueError(f"derived metric {m['name']} references {dep}")

    # ---------------------------------------------------------------- compiling
    def _where_sql(self, model: dict, where: dict | None, start=None, end=None) -> str:
        clauses = ["true"]
        for dim, value in (where or {}).items():
            if dim not in model["dimensions"]:
                raise ValueError(f"dimension {dim} not available on {model['table']}")
            col = model["dimensions"][dim]
            values = value if isinstance(value, list | tuple) else [value]
            quoted = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
            clauses.append(f"{col} in ({quoted})")
        if start:
            clauses.append(f"{model['time_dimension']} >= date '{start}'")
        if end:
            clauses.append(f"{model['time_dimension']} <= date '{end}'")
        return " and ".join(clauses)

    def _period_sql(self, model: dict, grain: str) -> str:
        if grain not in GRAINS:
            raise ValueError(f"grain must be one of {GRAINS}")
        if grain == "all":
            return "date '1900-01-01'"
        return f"cast(date_trunc('{grain}', {model['time_dimension']}) as date)"

    def compile(self, name: str, grain="month", where=None, start=None, end=None) -> str:
        """Return SQL producing columns (period, value) for a non-derived metric."""
        m = self.metrics[name]
        model = self.spec["models"][m["model"]]
        period = self._period_sql(model, grain)
        w = self._where_sql(model, where, start, end)
        t = model["table"]
        if m["type"] == "simple":
            value = _measure_sql(m["measure"])
            return f"select {period} as period, {value} as value from {t} where {w} group by 1"
        if m["type"] == "ratio":
            num, den = _measure_sql(m["numerator"]), _measure_sql(m["denominator"])
            return (
                f"select {period} as period, ({num})::double / nullif({den}, 0) as value "
                f"from {t} where {w} group by 1"
            )
        if m["type"] == "concentration":
            ent, meas = m["entity"], _measure_sql(m["measure"])
            per_entity = (
                f"select {period} as period, {ent} as entity, {meas} as v "
                f"from {t} where {w} group by 1, 2"
            )
            if m["method"] == "hhi":
                agg = "sum(pow(100.0 * v / tot, 2))"
                return (
                    f"with e as ({per_entity}), s as (select *, sum(v) over (partition by period)"
                    f" as tot from e where v > 0) select period, {agg} as value from s group by 1"
                )
            if m["method"] == "top_share":
                frac = float(m["top_fraction"])
                return (
                    f"with e as ({per_entity}), r as (select *, "
                    f"row_number() over (partition by period order by v desc, entity) as rk, "
                    f"count(*) over (partition by period) as n, "
                    f"sum(v) over (partition by period) as tot from e where v > 0) "
                    f"select period, sum(v) filter (where rk <= ceil({frac} * n)) / any_value(tot)"
                    f" as value from r group by 1"
                )
        raise ValueError(f"cannot compile metric type {m['type']} for {name}")

    # ---------------------------------------------------------------- computing
    def compute(self, names, grain="month", where=None, start=None, end=None) -> pd.DataFrame:
        """Wide DataFrame: one row per period, one column per metric."""
        names = [names] if isinstance(names, str) else list(names)
        needed: list[str] = []

        def add(n):
            m = self.metrics[n]
            if m["type"] == "derived":
                for dep in re.findall(r"[a-z_][a-z0-9_]*", m["formula"]):
                    add(dep)
            if n not in needed:
                needed.append(n)

        for n in names:
            add(n)
        frames = []
        for n in needed:
            if self.metrics[n]["type"] == "derived":
                continue
            sql = self.compile(n, grain, where, start, end)
            frames.append(self.con.execute(sql).df().set_index("period")["value"].rename(n))
        out = pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()
        for n in needed:
            m = self.metrics[n]
            if m["type"] == "derived":
                out[n] = out.eval(m["formula"])
        out = out[names].astype(float)
        out.index.name = "period"
        return out

    def value(self, name: str, where=None, start=None, end=None) -> float:
        """Single all-time (or windowed) value."""
        v = self.compute([name], grain="all", where=where, start=start, end=end)[name]
        return float(v.iloc[0]) if len(v) else math.nan

    # ------------------------------------------------------------ catalog docs
    def catalog_markdown(self) -> str:
        lines = [
            "# Metrics catalog",
            "",
            "_Generated from `metrics/metrics.yml` by `python -m marketplace.metrics`. "
            "Do not edit by hand._",
            "",
            "| Metric | Definition | Owner | Grain | Target |",
            "|---|---|---|---|---|",
        ]
        for m in self.spec["metrics"]:
            tgt = m.get("target", {}).get("basis", "-")
            lines.append(
                f"| **{m['label']}** (`{m['name']}`) | {m['definition'].strip()} | {m['owner']} "
                f"| {m['grain']} | {tgt} |"
            )
        lines += ["", "## Caveats per metric", ""]
        for m in self.spec["metrics"]:
            lines.append(f"### {m['label']} (`{m['name']}`)")
            lines.append(f"- Type: `{m['type']}`; unit: {m['unit']}")
            if m["type"] == "derived":
                lines.append(f"- Formula: `{m['formula']}`")
            elif m["type"] in {"simple", "ratio", "concentration"}:
                lines.append("- Compiled SQL (monthly):")
                lines.append("")
                lines.append("  ```sql")
                lines.append("  " + self.compile(m["name"], "month"))
                lines.append("  ```")
            for c in m["caveats"]:
                lines.append(f"- {c}")
            for alt in m.get("rejected_alternatives", []):
                a = self.spec["rejected_alternatives"][alt]
                lines.append(f"- Rejected alternative `{alt}`: {a['why_rejected']}")
            lines.append("")
        return "\n".join(lines)


def materialise(layer: MetricsLayer) -> pd.DataFrame:
    """Compute every metric at day/month/all grain into a long table + CSV."""
    names = list(layer.metrics)
    rows = []
    for grain in ("day", "month", "all"):
        wide = layer.compute(names, grain=grain)
        long = wide.reset_index().melt(id_vars="period", var_name="metric", value_name="value")
        long["grain"] = grain
        rows.append(long)
    out = pd.concat(rows, ignore_index=True)[["metric", "grain", "period", "value"]]
    return out


def main() -> int:
    layer = MetricsLayer.load()
    values = materialise(layer)
    layer.con.close()
    layer._con = None
    with duckdb.connect(str(WAREHOUSE)) as con:
        con.execute("create schema if not exists metrics")
        con.register("v", values)
        con.execute("create or replace table metrics.metric_values as select * from v")
        defs = pd.DataFrame(
            [
                {k: (str(v) if not isinstance(v, str) else v) for k, v in m.items()}
                for m in layer.spec["metrics"]
            ]
        )
        con.register("d", defs)
        con.execute("create or replace table metrics.metric_definitions as select * from d")
    REPORTS.mkdir(exist_ok=True)
    values[values.grain == "month"].to_csv(REPORTS / "metrics_monthly.csv", index=False)
    (DOCS / "metrics_catalog.md").write_text(layer.catalog_markdown())
    allv = values[values.grain == "all"].set_index("metric")["value"]
    for k, v in allv.items():
        print(f"  {k:<28} {v:,.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
