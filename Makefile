.ONESHELL:
.PHONY: test run run_coverage report_coverage development-diff-cover uninstall build install setup deploy down link-cli

VENV_DIR := $(CURDIR)/.venv
KAIROS_STATE_DIR := $(HOME)/.local/share/kairos-2

test:
	coverage run -m pytest \
 	--ignore="test/mock" \
 	--ignore="test/kairos/connector/exchange/ndax/" \
 	--ignore="test/kairos/connector/derivative/dydx_v4_perpetual/" \
 	--ignore="test/connector/utilities/oms_connector/" \
 	--ignore="test/kairos/strategy/amm_arb/" \
 	--ignore="test/kairos/strategy/cross_exchange_market_making/" \

run_coverage: test
	coverage report
	coverage html

report_coverage:
	coverage report
	coverage html

development-diff-cover:
	coverage xml
	diff-cover --compare-branch=origin/development coverage.xml

build:
	git clean -xdf && make clean && podman build --format docker -t kairos-2${TAG} -f Dockerfile .


uninstall:
	rm -rf "$(VENV_DIR)"
	rm -f "$(KAIROS_STATE_DIR)/source-path"

install:
	@mkdir -p logs
	@if ! command -v python3 >/dev/null 2>&1; then \
		echo "Error: python3 is not found in PATH."; \
		exit 1; \
	fi
	@if [ "$$(uname)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then \
		if ! (command -v gcc >/dev/null 2>&1 && command -v g++ >/dev/null 2>&1) \
		     || ! python3 -m venv --help >/dev/null 2>&1; then \
			echo "Compiler toolchain or python3-venv missing, installing..."; \
			sudo apt-get update && sudo apt-get install -y build-essential python3-venv python3-dev; \
		fi; \
	fi
	python3 -m venv "$(VENV_DIR)"
	"$(VENV_DIR)/bin/pip" install --upgrade pip setuptools wheel
	"$(VENV_DIR)/bin/pip" install Cython "numpy>=2.2.6"
	"$(VENV_DIR)/bin/pip" install -r setup/requirements.txt
	"$(VENV_DIR)/bin/pip" install --no-deps -r setup/pip_packages.txt > logs/pip_install.log 2>&1
	"$(VENV_DIR)/bin/pip" install pre-commit
	"$(VENV_DIR)/bin/pre-commit" install
	"$(VENV_DIR)/bin/python3" setup.py build_ext --inplace -j$$(nproc 2>/dev/null || echo 4)
	ln -sf "$(CURDIR)/bin/hbot" "$(VENV_DIR)/bin/hbot"
	@mkdir -p "$(KAIROS_STATE_DIR)"
	@echo "$(CURDIR)" > "$(KAIROS_STATE_DIR)/source-path"
	@echo "Done. Run: $(VENV_DIR)/bin/python3 bin/hbot --help  (or 'make link-cli' then 'hbot --help')"

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
	echo "Now 'hbot <command>' dispatches to your source install or the podman container."

run:
	"$(VENV_DIR)/bin/python3" ./bin/kairos_quickstart.py $(ARGS)

setup:
	@echo "COMPOSE_PROFILES=" > .compose.env

deploy:
	@if [ -f ./.compose.env ]; then set -a; . ./.compose.env; set +a; fi; \
	podman compose up -d

down:
	podman compose down
