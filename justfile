set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

bootstrap:
  python3 -m venv .venv
  .venv/bin/python -m pip install -r backend/requirements-dev.txt
  NPM_CONFIG_CACHE=.cache/npm npm --prefix frontend ci

lint:
  .venv/bin/ruff check backend
  npm --prefix frontend run lint

format:
  .venv/bin/ruff format backend
  npm --prefix frontend run format

format-check:
  .venv/bin/ruff format --check backend
  npm --prefix frontend run format:check

typecheck:
  .venv/bin/python -m compileall -q backend
  npm --prefix frontend run typecheck

test:
  .venv/bin/pytest -q
  npm --prefix frontend run test

compose-check:
  docker compose config --quiet

check: lint format-check typecheck test compose-check

run:
  docker compose up --build
