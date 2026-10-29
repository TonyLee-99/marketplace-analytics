# End-to-end rebuild from the raw CSV files:  make all
# Every target is idempotent. PY runs inside the uv-managed Python 3.12 venv.
SHELL := /bin/bash
PY    := PYTHONPATH=src .venv/bin/python -W ignore
DBT   := cd dbt && ../.venv/bin/dbt
export DBT_PROFILES_DIR := $(CURDIR)/dbt

.PHONY: all setup download ingest dbt freshness docs dq metrics analyses results voc voc-relabel \
        dashboard screenshots test lint clean

all: ingest dbt freshness docs metrics analyses voc results dashboard screenshots test lint
	@echo "make all: OK"

setup:            ## create the venv with pinned dependencies
	uv venv --python 3.12 && uv pip install -r requirements.lock

download:         ## fetch raw files from the pinned mirrors (if missing)
	$(PY) -m marketplace.ingest --download

ingest:           ## verify sha256/row counts/headers and land raw.* in DuckDB
	$(PY) -m marketplace.ingest --download

dbt:              ## seeds, snapshot, models, tests (fails on any test error)
	$(DBT) build

freshness:
	$(DBT) source freshness

docs:
	$(DBT) docs generate

dq:               ## re-count every data-quality issue listed in docs/DATA_QUALITY.md
	$(PY) -m marketplace.dq

metrics:          ## governed metrics -> metrics.metric_values, docs/metrics_catalog.md
	$(PY) -m marketplace.metrics
	$(PY) -m marketplace.metric_conflicts

analyses: dq
	$(PY) -m marketplace.analysis.delivery_impact
	$(PY) -m marketplace.analysis.review_value
	$(PY) -m marketplace.analysis.growth
	$(PY) -m marketplace.analysis.cohorts
	$(PY) -m marketplace.analysis.sellers
	$(PY) -m marketplace.analysis.anomalies
	$(PY) -m marketplace.analysis.root_cause
	$(PY) -m marketplace.analysis.promise_policy

results:          ## memo + recommendations.json + docs/RESULTS.md (every headline number with its source)
	$(PY) -m marketplace.memo
	$(PY) -m marketplace.results

voc:              ## report from cached LLM labels (artifacts/), no LLM needed
	$(PY) -m marketplace.analysis.voc report

voc-relabel:      ## re-run the zero-shot labelling with local Ollama qwen2.5:7b (~1 h)
	rm -f artifacts/voc_llm_labels.csv
	$(PY) -m marketplace.analysis.voc sample
	$(PY) -m marketplace.analysis.voc label
	$(PY) -m marketplace.analysis.voc report

dashboard:
	$(PY) -m marketplace.dashboard.build

screenshots:      ## headless Chrome: screenshots + console-error + filter checks
	$(PY) -m marketplace.dashboard.screenshots

test:
	$(PY) -m pytest -q

lint:
	.venv/bin/ruff check src tests

clean:
	rm -rf dbt/target dbt/logs reports/*.json reports/*.csv dashboard/index.html data/warehouse.duckdb
