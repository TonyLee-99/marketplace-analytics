# Reproducible build of the whole pipeline (data download -> dbt -> metrics -> analyses ->
# dashboard). Screenshots use Playwright's bundled Chromium inside the container.
# Build:  docker build -t marketplace-analytics .
# Run:    docker run --rm -v "$PWD/out:/app/dashboard" marketplace-analytics
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PLAYWRIGHT_CHANNEL=""
RUN apt-get update && apt-get install -y --no-install-recommends make curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install uv==0.9.*

WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.lock \
    && .venv/bin/playwright install --with-deps chromium

COPY . .
# The LLM step is not run in the container: VoC uses the committed label cache in artifacts/.
CMD ["make", "all"]
