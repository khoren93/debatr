# AI Debates (Debatr) — shortcuts for the commands in CLAUDE.md. `make` lists them.

COMPOSE      := docker compose
DEV_COMPOSE  := docker compose -f docker-compose.dev.yml
PROD_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.prod.yml
s            ?=
f            ?=

.DEFAULT_GOAL := help
.PHONY: help install dev-up dev-down api worker media-worker scheduler trending web migrate migration \
	lint format typecheck test check build cli screenshots up down restart logs ps deploy prod-logs prod-ps \
	backup backup-check

help: ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Native development ---------------------------------------------------------------

install: ## Install backend (uv), CLI (uv) and frontend (npm) dependencies
	cd backend && uv sync
	cd cli && uv sync
	cd frontend && npm install

dev-up: ## Start Postgres + Redis for native dev
	$(DEV_COMPOSE) up -d

dev-down: ## Stop the dev Postgres + Redis
	$(DEV_COMPOSE) down

api: ## Run the API with reload on :8000
	cd backend && uv run uvicorn app.main:app --reload

worker: ## Run the RQ worker for both queues
	cd backend && RQ_SIMPLE_WORKER=true uv run python -m app.worker

media-worker: ## Run a media-only worker (needs ffmpeg)
	cd backend && uv run python -m app.worker --queues media

scheduler: ## Run the periodic jobs (hourly trending-topics check)
	cd backend && uv run python -m app.scheduler

trending: ## Build a fresh batch of trending topics now
	cd backend && uv run python -m app.scheduler --refresh-trending

web: ## Run the Vite dev server on :5173
	cd frontend && npm run dev

migrate: ## Apply database migrations
	cd backend && uv run alembic upgrade head

migration: ## Create a migration: make migration m="describe change"
	@test -n "$(m)" || (echo 'Usage: make migration m="describe change"' && exit 1)
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

cli: ## Run the CLI from the repo against the local stack: make cli a="run 'Tabs or spaces?'"
	cd cli && uv run debatr --url $${DEBATR_URL:-http://localhost} $(a)

screenshots: ## Shoot the README images from the local stack into scripts/screenshots/out (account: DEBATR_EMAIL/DEBATR_PASSWORD or scripts/screenshots/.env)
	cd scripts/screenshots && npm install --no-audit --no-fund && npm run capture

# --- Quality --------------------------------------------------------------------------

lint: ## Ruff + eslint
	cd backend && uv run ruff check .
	cd cli && uv run ruff check .
	cd frontend && npm run lint

format: ## Ruff format + autofix
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd cli && uv run ruff check --fix . && uv run ruff format .

typecheck: ## Pyright + tsc
	cd backend && uv run pyright
	cd cli && uv run pyright
	cd frontend && npm run typecheck

test: ## Backend and CLI tests
	cd backend && uv run pytest -q
	cd cli && uv run pytest -q

check: ## Everything CI runs (lint, format check, types, tests, build)
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
	cd cli && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
	cd frontend && npm run check && npm run build

build: ## Production frontend build
	cd frontend && npm run build

# --- Local Docker stack ---------------------------------------------------------------

up: ## Build and start the full stack on http://localhost
	GIT_SHA=$$(git rev-parse --short HEAD) $(COMPOSE) up -d --build

down: ## Stop the full stack
	$(COMPOSE) down

restart: ## Rebuild and restart one service or all: make restart s=worker
	GIT_SHA=$$(git rev-parse --short HEAD) $(COMPOSE) up -d --build $(s)

logs: ## Follow logs: make logs s=api
	$(COMPOSE) logs -f --tail=200 $(s)

ps: ## Container status
	$(COMPOSE) ps

# --- Production (run these on the server, in the project dir) ---------------------------

deploy: ## Pull latest main and rebuild the production stack (deploy.sh)
	./deploy.sh

prod-logs: ## Follow production logs: make prod-logs s=worker
	$(PROD_COMPOSE) logs -f --tail=200 $(s)

prod-ps: ## Production container status
	$(PROD_COMPOSE) ps

backup: ## Dump Postgres into ./backups and prune old dumps (scripts/backup-db.sh; cron on the server)
	./scripts/backup-db.sh

backup-check: ## Restore the newest dump into a scratch database and compare row counts: make backup-check f=FILE
	./scripts/backup-db.sh --check $(f)
