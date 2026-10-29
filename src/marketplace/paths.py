"""Central place for file paths so every script agrees on where things live."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
WAREHOUSE = DATA / "warehouse.duckdb"
MANIFEST = ROOT / "data_manifest.json"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
IMG = DOCS / "img"
METRICS_YAML = ROOT / "metrics" / "metrics.yml"
DASHBOARD_DIR = ROOT / "dashboard"
