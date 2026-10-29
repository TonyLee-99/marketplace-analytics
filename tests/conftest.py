import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from marketplace.paths import REPORTS, WAREHOUSE  # noqa: E402

needs_warehouse = pytest.mark.skipif(not WAREHOUSE.exists(), reason="run `make ingest dbt` first")
needs_reports = pytest.mark.skipif(
    not (REPORTS / "growth.json").exists(), reason="run `make analyses` first"
)
