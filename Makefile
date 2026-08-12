.ONESHELL:
.PHONY: test run run_coverage report_coverage development-diff-cover uninstall build install setup deploy down link-cli clean

# Interpreter the .venv is built from. The dependency set requires 3.12 (pandas-ta needs
# >=3.12); override only if your 3.12 lives under a different name, e.g. PYTHON=python3.12.6
PYTHON ?= python3.12

# DYDX=1 adds the dydx_v4 connector's extra dependencies (replaces setup/environment_dydx.yml)
DYDX ?= 0

test:
	poetry run coverage run -m pytest \
 	--ignore="test/mock" \
 	--ignore="test/hummingbot/connector/exchange/ndax/" \
 	--ignore="test/hummingbot/connector/derivative/dydx_v4_perpetual/" \
 	--ignore="test/connector/utilities/oms_connector/" \
 	--ignore="test/hummingbot/strategy/amm_arb/" \
 	--ignore="test/hummingbot/strategy/cross_exchange_market_making/" \

run_coverage: test
	poetry run coverage report
	poetry run coverage html

report_coverage:
	poetry run coverage report
	poetry run coverage html

development-diff-cover:
	poetry run coverage xml
	poetry run diff-cover --compare-branch=origin/development coverage.xml

build:
	git clean -xdf && make clean && docker build -t hummingbot/hummingbot${TAG} -f Dockerfile .

clean:
	@./clean

uninstall:
	-poetry env remove --all
	rm -rf .venv
	@./clean

install:
	@if ! command -v poetry >/dev/null 2>&1; then \
		echo "Error: Poetry is not found in PATH."; \
		echo "Install it with: curl -sSL https://install.python-poetry.org | python3 -"; \
		exit 1; \
	fi
	@mkdir -p logs
	@# The Cython extensions need a C++ toolchain, and a few deps have no aarch64 wheel
	@# (safe-pysha3, crcmod) so they compile from source on ARM — hence python3-dev too.
	@if [ "$$(uname)" = "Linux" ] && command -v dpkg >/dev/null 2>&1; then \
		missing=""; \
		for p in build-essential python3-dev; do \
			dpkg -s $$p >/dev/null 2>&1 || missing="$$missing $$p"; \
		done; \
		if [ -n "$$missing" ]; then \
			echo "Installing missing build dependencies:$$missing"; \
			sudo apt-get update && sudo apt-get install -y $$missing; \
		fi; \
	fi
	poetry env use $(PYTHON)
	poetry install --no-root --with dev $(if $(filter 1,$(DYDX)),--with dydx,)
	@# Editable install: compiles the Cython/C++ extensions in place and puts the `hbot`
	@# console script in .venv/bin. --no-build-isolation reuses the cython/numpy/setuptools
	@# already resolved in the lock instead of downloading a second, unlocked copy.
	poetry run pip install -e . --no-build-isolation --no-deps
	poetry run pre-commit install
	@echo "Done. Run: source .venv/bin/activate && hbot --help"

link-cli:
	@src="$(CURDIR)/bin/hbot-host"; dir="$${HBOT_BIN:-}"; \
	if [ -z "$$dir" ]; then \
		for d in /usr/local/bin "$$HOME/.local/bin"; do \
			if [ -w "$$d" ] || { [ ! -e "$$d" ] && mkdir -p "$$d" 2>/dev/null; }; then dir="$$d"; break; fi; \
		done; \
	fi; \
	if [ -z "$$dir" ]; then \
		echo "No writable bin dir found (tried /usr/local/bin, ~/.local/bin)."; \
		echo "Set HBOT_BIN to a writable dir on your PATH and retry, e.g.  make link-cli HBOT_BIN=\$$HOME/.local/bin"; \
		exit 1; \
	fi; \
	mkdir -p "$$dir"; ln -sf "$$src" "$$dir/hbot"; \
	echo "Linked $$dir/hbot -> bin/hbot-host"; \
	case ":$$PATH:" in *":$$dir:"*) ;; *) echo "NOTE: add $$dir to your PATH to run 'hbot'." ;; esac; \
	echo "Now 'hbot <command>' dispatches to your source .venv or the docker container."

run:
	poetry run ./bin/hummingbot_quickstart.py $(ARGS)

setup:
	@read -r -p "Include Gateway? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		echo "COMPOSE_PROFILES=gateway" > .compose.env; \
		echo "Gateway will be included."; \
	else \
		echo "COMPOSE_PROFILES=" > .compose.env; \
		echo "Gateway will NOT be included."; \
	fi

deploy:
	@if [ -f ./.compose.env ]; then set -a; . ./.compose.env; set +a; fi; \
	docker compose up -d

down:
	docker compose --profile gateway down
