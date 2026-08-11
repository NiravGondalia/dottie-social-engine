# MiloAgent — common development & ops targets
# Usage: make help

.DEFAULT_GOAL := help

PYTHON   ?= python3
PIP      := $(PYTHON) -m pip
VENV     := .venv
VENV_BIN := $(VENV)/bin
MILO     := $(PYTHON) miloagent.py
PORT     ?= 8420
PROJECT  ?=

# Prefer venv python when present
ifneq (,$(wildcard $(VENV_BIN)/python))
  PYTHON := $(VENV_BIN)/python
  PIP    := $(VENV_BIN)/pip
  MILO   := $(VENV_BIN)/python miloagent.py
endif

.PHONY: help install venv deps playwright env \
	setup test login login-all status stats accounts \
	run run-web run-daemon dashboard stop \
	scan post engage learn insights \
	docker-up docker-down docker-logs docker-build docker-restart \
	deploy-setup deploy-up deploy-down deploy-update deploy-status deploy-logs \
	clean clean-pyc

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Setup ───────────────────────────────────────────────

venv: ## Create Python virtualenv at .venv
	$(PYTHON) -m venv $(VENV)
	@echo "Activate with: source $(VENV)/bin/activate"

deps: ## Install Python dependencies
	$(PIP) install -r requirements.txt

playwright: ## Install Playwright browsers (for Reddit login)
	$(PYTHON) -m playwright install chromium

install: venv ## Create venv + install deps (+ Playwright)
	$(VENV_BIN)/pip install -r requirements.txt
	-$(VENV_BIN)/python -m playwright install chromium
	@echo "Done. Run: source $(VENV)/bin/activate"

env: ## Copy .env.example → .env if missing
	@test -f .env || cp .env.example .env
	@echo ".env ready — edit credentials as needed"

setup: ## Interactive Milo setup wizard
	$(MILO) setup

# ── Agent ───────────────────────────────────────────────

test: ## Test connections (make test SERVICE=all|llm|reddit|…)
	$(MILO) test $(or $(SERVICE),all)

login: ## Browser login for cookies (PLATFORM=reddit)
	$(MILO) login $(or $(PLATFORM),reddit) $(if $(ACCOUNT),-a $(ACCOUNT),)

login-all: ## Login all enabled Reddit accounts
	$(MILO) login reddit --all-accounts

status: ## Show agent status
	$(MILO) status

stats: ## Show stats (HOURS=24)
	$(MILO) stats --hours $(or $(HOURS),24)

accounts: ## List configured accounts
	$(MILO) accounts

run: ## Start Milo (foreground)
	$(MILO) run

run-web: ## Start Milo with web dashboard (PORT=8420)
	$(MILO) run --web --web-port $(PORT)

run-daemon: ## Start Milo as background daemon
	$(MILO) run --daemon

dashboard: ## Terminal (TUI) dashboard
	$(MILO) dashboard

stop: ## Stop daemon
	$(MILO) stop

scan: ## Scan for opportunities (PROJECT=name PLATFORM=reddit)
	$(MILO) scan $(or $(PLATFORM),reddit) $(if $(PROJECT),-p $(PROJECT),)

post: ## Act on best opportunity (PROJECT=name; DRY=1 for dry-run)
	$(MILO) post $(or $(PLATFORM),reddit) -p $(PROJECT) $(if $(DRY),--dry-run,)

engage: ## Organic engagement pass
	$(MILO) engage $(or $(PLATFORM),reddit) $(if $(PROJECT),-p $(PROJECT),)

learn: ## Run learning cycle
	$(MILO) learn $(if $(PROJECT),-p $(PROJECT),)

insights: ## Show learning insights
	$(MILO) insights $(if $(PROJECT),-p $(PROJECT),)

# ── Docker ──────────────────────────────────────────────

docker-build: ## Build Docker image
	docker compose build

docker-up: ## Start via Docker Compose
	docker compose up -d

docker-down: ## Stop Docker Compose
	docker compose down

docker-restart: ## Restart Docker Compose
	docker compose restart

docker-logs: ## Tail Docker logs
	docker compose logs -f

# ── Deploy (VPS) ────────────────────────────────────────

deploy-setup: ## First-time VPS setup (Nginx + SSL + systemd)
	./deploy.sh --setup

deploy-up: ## Build & start on server
	./deploy.sh --up

deploy-down: ## Stop server services
	./deploy.sh --down

deploy-update: ## Pull, rebuild, restart
	./deploy.sh --update

deploy-status: ## Server health check
	./deploy.sh --status

deploy-logs: ## Tail server logs
	./deploy.sh --logs

# ── Cleanup ─────────────────────────────────────────────

clean-pyc: ## Remove __pycache__ and *.pyc
	find . -type d -name '__pycache__' -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.py[co]' -not -path './.venv/*' -delete 2>/dev/null || true

clean: clean-pyc ## Remove caches (keeps venv, data, .env)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
