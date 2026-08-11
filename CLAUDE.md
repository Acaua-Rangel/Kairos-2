# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kairos-2 is a Binance-only, market-making-only fork of [Hummingbot](https://github.com/hummingbot/hummingbot).
It strips upstream down to a single exchange (`binance`, `binance_perpetual`, `binance_paper_trade`) and a
single strategy class (market making), to cut the surface area to read and reason about. The Python package
is `kairos`; the CLI command is still named `hbot` (kept for muscle memory and because Binance's broker-program
order-id prefixes in `kairos/connector/utils.py` are named `hbot` and must not change).

## Build & install

Requires Python 3.12+ and a C++ compiler (Cython extensions). Poetry is the dependency manager.

```bash
make install       # installs Poetry if missing, creates .venv/, builds Cython extensions, symlinks hbot into .venv
make link-cli       # puts `hbot` on PATH (host symlink to bin/hbot-host, which dispatches to venv or Podman)
make uninstall      # removes .venv and local state
```

Podman is the alternative install path (`make setup && make deploy`), useful when avoiding a local compiler
toolchain — see the README's Podman section for the idle-host mode used for scripted `hbot` access.

After editing any `.pyx`/`.pxd` file under `kairos/`, rebuild extensions with `make install` (full) or, for a
fast rebuild without a full `poetry install`, use what `hbot update` does internally:
`python build.py build_ext --inplace -j <n>`.

## Testing

```bash
make test                        # full suite via coverage run -m pytest, with the excludes below
make run_coverage                # test + coverage report + html
make development-diff-cover      # coverage.xml + diff-cover against origin/development
```

`make test` permanently excludes connector/strategy trees that were removed from this fork but whose tests
weren't deleted yet: `test/mock`, `test/kairos/connector/exchange/ndax/`,
`test/kairos/connector/derivative/dydx_v4_perpetual/`, `test/connector/utilities/oms_connector/`,
`test/kairos/strategy/amm_arb/`, `test/kairos/strategy/cross_exchange_market_making/`.

Run a single test directly with the venv's pytest (not `make test`, which always runs the full suite):

```bash
.venv/bin/pytest test/kairos/strategy_v2/executors/position_executor/test_position_executor.py
.venv/bin/pytest test/kairos/cli/test_status.py::TestStatus::test_running_bot -v
```

Async tests use `pytest-asyncio` (function-scoped loop by default, see `pyproject.toml`). Tests are killed
after 120s each via `pytest-timeout` (`signal` method) so one hang doesn't stall the whole run.

Minimum 80% diff-coverage is expected on PRs (see `CONTRIBUTING.md`); UI components are exempt.

## Linting

flake8 (config in `.flake8`, 120-char lines) and isort (`pyproject.toml`, 120-char lines) run via
pre-commit (`.pre-commit-config.yaml`), which also runs autopep8 in fixer mode, eslint for any `.js/.ts`
files, and secret-detection hooks. `.pyx`/`.pxd` files are exempted from several flake8 checks (E225, E226,
E251, E999) since Cython syntax trips the Python-syntax linter.

## Architecture

### Two coexisting strategy generations

- **V1** (`kairos/strategy/`) — classic strategy classes: `pure_market_making`,
  `avellaneda_market_making` (Avellaneda–Stoikov). Configs live in `conf/strategies/`.
- **V2** (`kairos/strategy_v2/` + top-level `controllers/`) — the modern framework. `kairos/strategy_v2/`
  holds the generic machinery: `executors/` (position, DCA, grid, order, TWAP — each a self-contained
  state machine for one open position/order lifecycle), `controllers/` (base controller classes),
  `backtesting/` (including `executors_simulator/`), `models/`, `utils/`. The actual strategy logic
  users run lives in the top-level `controllers/market_making/` (`pmm_simple.py`, `pmm_dynamic.py`,
  `dman_maker_v2.py`) and `controllers/generic/pmm_v1.py`. V2 controller configs (`conf/controllers/`)
  can be backtested and have their fields tuned live while the bot runs (~10s propagation); V1 configs
  cannot. `scripts/` holds single-file V2 script strategies (config kind `v2-script`, `conf/scripts/`).

Three config kinds, one per folder: `v1-strategy` (`conf/strategies/`), `v2-script` (`conf/scripts/`),
`controller` (`conf/controllers/`). File names are unique across all three, so the CLI infers the kind
from context in most cases.

### Package layout (`kairos/`)

- `cli/` — the `hbot` non-interactive CLI (see below). `cli/commands/` has one module per subcommand.
- `client/` — the interactive terminal client (`kairos_application.py` is the app shell; `command/`,
  `config/`, `tab/`, `ui/` support it). This is what `podman attach kairos-2` drops you into.
- `connector/` — exchange connectors, narrowed to Binance only: `exchange/binance` (spot),
  `derivative/binance_perpetual` (perp futures), `exchange/paper_trade` (simulated fills against live
  market data). `utilities/` and `test_support/` are shared connector helpers/mocks.
- `core/` — engine internals: `data_type/` (order book, trade, etc.), `event/` (event bus + typed
  events), `api_throttler/` (rate limiting), `rate_oracle/` (price conversion, narrowed to Binance/
  CoinGecko/CoinCap), `web_assistant/` (HTTP/WS helpers), `management/` (console/diagnostics),
  `cpp/` — the Cython/C++ extensions built by `build.py`.
- `data_feed/`, `model/` (DB/ORM for trades and market data), `logger/`, `notifier/`, `remote_iface/`
  (MQTT), `user/` (cross-exchange balance tracking), `templates/` (config YAML templates).

Note: `kairos/README.md` documents an older directory layout (`smart_components/`, `pmm_script/`) that
predates the current top-level `controllers/` and `kairos/strategy_v2/` split — treat the structure above
as authoritative.

### The `hbot` CLI

`hbot` runs one bot per install, fully non-interactively — every command emits Markdown by default
(or `--json` on run/observe commands) and returns a stable exit code (0 SUCCESS, 1 ERROR, 2 NOT_FOUND,
3 NOT_RUNNING, 4 CONFIG_ERROR, 5 TIMEOUT). Full reference: `kairos/cli/README.md`. Entry point:
`bin/hbot` → `kairos.cli.main:main`. Command modules live in `kairos/cli/commands/`, one file per verb
(`create.py`, `deploy.py`, `start.py`, `status.py`, `config.py`, `doctor.py`, etc.) plus shared logic in
`_common.py`.

Key flow: `create <strategy>` (or `import <file>`) loads a config without starting it → `config` inspects/
edits the loaded config → `start` runs it. `deploy` bundles create-or-load + start into one call for
scripts/agents. Controllers can't run standalone, so `start` generates a small V2 loader script for them
automatically. State lives under `data/bot/` (`meta.json`, `bot.pid`, `status.json`, `loaded.json`); a
bot's trades DB and log are named after its config stem (`data/<name>.sqlite`, `logs/logs_<name>.log`),
so a stopped bot's history stays inspectable by name.

`bin/hbot-host` is the host-side dispatcher used by `make link-cli`: it detects whether to exec into a
running Podman container or a local source venv, so the same `hbot <command>` works either way.

### Removed from upstream Hummingbot

All non-Binance connectors, the Gateway/DEX layer and AMM/CLOB-DEX integrations, and all non-market-making
strategies (arbitrage, XEMM, hedge, liquidity mining, directional trading, grid/LP controllers). Several
test directories for this removed code still exist but are excluded from `make test` (see Testing above)
rather than deleted outright.
