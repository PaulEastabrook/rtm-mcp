.PHONY: naming install dev lint format test test/coverage fingerprints run clean help

# Every target resolves to ~/.venvs/rtm-mcp, NEVER an in-repo .venv.
#
# Two reasons, and the second is the serious one. (1) It matches production: the Claude
# Desktop launch entry sets exactly this, so `make test` exercises the interpreter the server
# actually runs on. (2) `~/Documents/Code` is **iCloud-synced**, and an in-repo `.venv` there
# gets corrupted two distinct ways — conflict copies (`lib 2/`, `pyvenv 2.cfg`) and files
# evicted to `dataless`; and, measured 2026-07-30, `fileproviderd` sets `UF_HIDDEN` on any
# dot-prefixed directory under ~/Documents within ~2s, while **Python silently skips a hidden
# `.pth`** — so the editable install is present, byte-correct, and ignored, and every import
# fails with `ModuleNotFoundError`. `chflags nohidden` is a two-second reprieve, not a cure.
# A bare `uv sync` creates precisely that venv, which is what `make dev` used to be: a bare
# sync wearing a safe-looking name.
#
# `?=` so an explicit environment override still wins (CI calls `uv` directly and never sees
# this, which is why the pin is safe here).
export UV_PROJECT_ENVIRONMENT ?= $(HOME)/.venvs/rtm-mcp

help:
	@echo "RTM MCP Server - Development Commands"
	@echo ""
	@echo "  make install      Install dependencies"
	@echo "  make dev          Install with dev dependencies"
	@echo "  make lint         Run linting (ruff + pyright)"
	@echo "  make format       Format code with ruff"
	@echo "  make test         Run tests"
	@echo "  make test/coverage Run tests with coverage"
	@echo "  make fingerprints Regenerate tool-fingerprints.json (run when tool schemas change)"
	@echo "  make run          Run the MCP server"
	@echo "  make setup        Run auth setup script"
	@echo "  make inspect      Run MCP Inspector"
	@echo "  make clean        Clean build artifacts"

install:
	uv sync

dev:
	uv sync --all-extras

lint:
	uv run python scripts/check-tool-naming.py --strict
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run pyright src

format:
	uv run ruff format src tests
	uv run ruff check --fix src tests

test:
	uv run pytest

test/coverage:
	uv run pytest --cov=src/rtm_mcp --cov-report=term-missing --cov-report=html

naming:
	uv run python scripts/check-tool-naming.py --strict

fingerprints:
	uv run python scripts/dump-tool-fingerprints.py

run:
	uv run rtm-mcp

setup:
	uv run rtm-setup

inspect:
	npx @modelcontextprotocol/inspector uv run rtm-mcp

clean:
	rm -rf .ruff_cache .pytest_cache .coverage htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
