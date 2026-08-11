# Kairos-2

[![License](https://img.shields.io/badge/License-Apache%202.0-informational.svg)](./LICENSE)

**Kairos-2** is a market making trading client for **Binance**. It is a stripped-down fork of
[Hummingbot](https://github.com/hummingbot/hummingbot), reduced to a single exchange and a single
class of strategy so there is far less surface to read, build, and reason about.

## What's in this fork

**Exchanges — Binance only**

| Connector | Type | ID |
|---|---|---|
| Binance | Spot | `binance` |
| Binance | Perpetual futures | `binance_perpetual` |
| Binance | Paper trading (simulated) | `binance_paper_trade` |

**Strategies — market making only**

* **[V2 controllers](./controllers/market_making)** — the modern framework: `pmm_simple`,
  `pmm_dynamic`, `dman_maker_v2`, plus [`pmm_v1`](./controllers/generic/pmm_v1.py). Configs can be
  backtested and tuned live while the bot runs.
* **[V1 `pure_market_making`](./kairos/strategy/pure_market_making)** — the classic PMM strategy.
* **[V1 `avellaneda_market_making`](./kairos/strategy/avellaneda_market_making)** — market making
  with the Avellaneda–Stoikov model (spreads driven by inventory and volatility).
* **[Scripts](./scripts)** — single-file Python strategies, e.g.
  [`simple_pmm.py`](./scripts/simple_pmm.py).

**Executors** still available to controllers: position, DCA, grid, order, and TWAP.

### What was removed

Relative to upstream Hummingbot: all non-Binance connectors (25 spot exchanges, 18 perpetual
venues), the Gateway/DEX layer and every AMM/CLOB-DEX integration, and all non-market-making
strategies (arbitrage, XEMM, hedge, liquidity mining, directional trading, grid/LP controllers).
Candles feeds and rate-oracle sources were narrowed to Binance, CoinGecko, and CoinCap.

## Getting started

Requires Python 3.12+ and a C++ compiler (`gcc`/`g++`) to build the Cython extensions.
[Poetry](https://python-poetry.org) is the dependency installer — `make install` installs it
automatically (isolated from the project's own venv) if it isn't already on your PATH.

```bash
git clone https://github.com/Acaua-Rangel/Kairos-2.git
cd Kairos-2

make install            # install Poetry if needed, create .venv/, build the Cython extensions, expose `hbot`
make link-cli            # put `hbot` on your PATH
hbot --help
```

The CLI command is still named `hbot`, and so are the exchange order-id prefixes — see
[Naming](#naming) below.

### Paper trading first

`binance_paper_trade` simulates fills against live Binance market data, so no API keys are needed:

```bash
hbot create simple_pmm --name conf_paper_bot.yml \
     --set exchange=binance_paper_trade --set trading_pair=BTC-USDT
hbot start conf_paper_bot.yml
hbot status
hbot stop
```

### Live trading

```bash
hbot connect binance                                   # store API keys (encrypted at rest)
hbot create pmm_simple --name conf_my_bot.yml \
     --set connector_name=binance --set trading_pair=BTC-USDT --set total_amount_quote=100
hbot start conf_my_bot.yml
```

On first use `hbot` prompts for a keystore password that encrypts your API keys. Set
`HBOT_PASSWORD` or pass `--password-stdin` to run non-interactively.

Full command reference: **[hbot CLI guide](kairos/cli/README.md)**.

### Podman

Requires [Podman](https://podman.io/docs/installation) and
[podman-compose](https://github.com/containers/podman-compose).

```bash
git clone https://github.com/Acaua-Rangel/Kairos-2.git
cd Kairos-2
make setup
make deploy           # start the container
make link-cli         # put `hbot` on the host PATH (dispatches into the container)
```

Or use the interactive full-screen client with `podman attach kairos-2`.

### Deploying on a small cloud VM (e.g. AWS `t4g.small`)

Tested on a 2GB-RAM ARM64 Ubuntu instance. `make install` (no container) is the lightest path
here, but still needs a compiler toolchain to build the Cython extensions, and a swapfile is
cheap insurance on a 2GB instance.

```bash
# 1. system dependencies
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev gcc g++ git make

# 2. swap (recommended on 2GB instances)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 3. clone and install (note: the branch, not master)
git clone -b kairos-2 https://github.com/Acaua-Rangel/Kairos-2.git
cd Kairos-2
make install
make link-cli
# open a new shell (or `source ~/.bashrc`) to pick up the updated PATH

# 4. sanity check
hbot doctor

# 5. paper trade — no API keys needed
hbot create simple_pmm --name conf_paper_bot.yml \
     --set exchange=binance_paper_trade --set trading_pair=BTC-USDT
hbot start conf_paper_bot.yml
hbot status
hbot logs -f
```

If the VM reboots, run `hbot start conf_paper_bot.yml` again — nothing here wires the bot to
auto-restart. If `make install` fails partway through on a low-RAM instance, grow the
swapfile (`sudo swapoff /swapfile && sudo fallocate -l 8G /swapfile && sudo mkswap /swapfile &&
sudo swapon /swapfile`) and re-run `make install`; it picks up where it left off.

Prefer an isolated container instead? See [Podman](#podman) above — same VM prep (steps 1-2 apply
to `python3-venv`/`gcc`/`g++`/`make` only; swap out the package list for `podman podman-compose`).

## Naming

The Python package is `kairos`; the distribution is `kairos-2`; the container image is
`kairos-2`. Two upstream names were deliberately **kept**:

* **`hbot`** — the CLI command name, so muscle memory and existing scripts keep working.
* **`hbot` order-id prefixes** (`kairos/connector/utils.py`) — these are part of Binance's broker
  program. Changing them would silently alter how orders are attributed, so they are untouched.

## Legal

Kairos-2 is a fork of Hummingbot and remains licensed under [Apache 2.0](./LICENSE). The original
copyright of the Hummingbot Foundation is retained in `LICENSE` as that license requires.

Anonymous usage metrics inherited from upstream still report a `hummingbot-client` source string
and can be disabled via `anonymized_metrics_mode` in the client config.
