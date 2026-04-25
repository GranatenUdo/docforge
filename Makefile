# docforge developer shortcuts.
#
# Windows users on Git Bash: install make once via
#   choco install make    # or
#   winget install GnuWin32.Make
#
# Most targets assume an active venv with `pip install -e ".[dev,entra]"`.

.PHONY: install test test-all lint format format-check build clean \
        microsite-install microsite-dev microsite-build help

help:
	@echo "Targets:"
	@echo "  install            pip install -e .[dev,entra]"
	@echo "  test               pytest -m 'not integration'"
	@echo "  test-all           pytest (includes integration)"
	@echo "  lint               ruff check src/docforge tests"
	@echo "  format             ruff format src/docforge tests"
	@echo "  format-check       ruff format --check src/docforge tests"
	@echo "  build              clean build of sdist + wheel"
	@echo "  clean              remove build artefacts"
	@echo "  microsite-install  pnpm install in microsite/"
	@echo "  microsite-dev      pnpm run dev in microsite/"
	@echo "  microsite-build    pnpm run build in microsite/"

install:
	pip install -e ".[dev,entra]"

test:
	pytest -m "not integration"

test-all:
	pytest

lint:
	ruff check src/docforge tests

format:
	ruff format src/docforge tests

format-check:
	ruff format --check src/docforge tests

build: clean
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .ruff_cache/

microsite-install:
	cd microsite && pnpm install

microsite-dev:
	cd microsite && pnpm run dev

microsite-build:
	cd microsite && pnpm run build
