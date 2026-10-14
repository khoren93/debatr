# AI Debates (Debatr) — shortcuts for the commands in CLAUDE.md. `make` lists them.

COMPOSE      := docker compose
DEV_COMPOSE  := docker compose -f docker-compose.dev.yml
DEPLOY_HOST  ?= hetzner-ai-debates
DEPLOY_DIR   ?= ~/apps/ai-debates
s            ?=

.DEFAULT_GOAL := help
.PHONY: help install dev-up dev-down api worker media-worker web migrate migration \
	lint format typecheck test check build up down restart logs ps deploy server-logs ssh

help: ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Native development ---------------------------------------------------------------

install: ## Install backend (uv) and frontend (npm) dependencies
	cd backend && uv sync
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

web: ## Run the Vite dev server on :5173
	cd frontend && npm run dev

migrate: ## Apply database migrations
	cd backend && uv run alembic upgrade head

migration: ## Create a migration: make migration m="describe change"
	@test -n "$(m)" || (echo 'Usage: make migration m="describe change"' && exit 1)
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

# --- Quality --------------------------------------------------------------------------

lint: ## Ruff + eslint
	cd backend && uv run ruff check .
	cd frontend && npm run lint

format: ## Ruff format + autofix
	cd backend && uv run ruff check --fix . && uv run ruff format .

typecheck: ## Pyright + tsc
	cd backend && uv run pyright
	cd frontend && npm run typecheck

test: ## Backend tests
	cd backend && uv run pytest -q

check: ## Everything CI runs (lint, format check, types, tests, build)
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q
	cd frontend && npm run check && npm run build

build: ## Production frontend build
	cd frontend && npm run build

# --- Local Docker stack ---------------------------------------------------------------

up: ## Build and start the full stack on http://localhost
	$(COMPOSE) up -d --build

down: ## Stop the full stack
	$(COMPOSE) down

restart: ## Rebuild and restart one service or all: make restart s=worker
	$(COMPOSE) up -d --build $(s)

logs: ## Follow logs: make logs s=api
	$(COMPOSE) logs -f --tail=200 $(s)

ps: ## Container status
	$(COMPOSE) ps

# --- Production -----------------------------------------------------------------------

deploy: ## Pull and rebuild on the server (runs deploy.sh over SSH)
	ssh $(DEPLOY_HOST) 'cd $(DEPLOY_DIR) && ./deploy.sh'

server-logs: ## Follow server logs: make server-logs s=worker
	ssh -t $(DEPLOY_HOST) 'cd $(DEPLOY_DIR) && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=200 $(s)'

ssh: ## Open a shell in the project dir on the server
	ssh -t $(DEPLOY_HOST) 'cd $(DEPLOY_DIR) && exec $$SHELL -l'
