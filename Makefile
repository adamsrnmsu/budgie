# The venv lives OUTSIDE the repo, alongside the other tools. Keeping it in-tree
# invites editors and cleanup scripts to touch it, and a .pth file that picks up
# macOS's UF_HIDDEN flag is silently skipped by site.py — the package installs
# fine and then won't import. Override with: make venv VENV=/some/other/path
VENV ?= $(HOME)/Documents/tools/budgie
BIN := $(VENV)/bin

.PHONY: help venv activate install lint format test docs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtualenv in $(VENV) and install budgie (editable) with dev and docs tools
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e '.[dev,docs]'

install: ## Reinstall the package into an existing venv
	$(BIN)/pip install -e '.[dev,docs]'

activate: ## Print the command to activate the venv (a target can't alter your shell)
	@echo "Run this in your shell:  source $(BIN)/activate"

lint: ## Lint with ruff
	$(BIN)/ruff check .

format: ## Sort imports (isort) and format (ruff)
	$(BIN)/isort .
	$(BIN)/ruff format .

test: ## Run the test suite
	$(BIN)/pytest

docs: ## Build the Sphinx site into docs/_build/html (warnings are errors)
	$(BIN)/sphinx-build -W --keep-going -b html docs docs/_build/html

clean: ## Remove caches and build artifacts
	rm -rf build *.egg-info .pytest_cache docs/_build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
