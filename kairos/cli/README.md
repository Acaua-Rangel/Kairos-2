# `hbot` — Kairos-2 command-line interface

`hbot` runs, controls, and monitors **one Kairos-2 bot per install**. It is fully
non-interactive and scriptable: every command emits compact **Markdown** (tables for lists,
key-value for records — readable by humans and agents alike) and returns a **stable exit code**;
the run/observe commands also take **`--json`** for machine-readable output. No MQTT broker, no
interactive prompts required.

```bash
hbot --help          # top-level commands
hbot --version
hbot <command> -h    # full help for one command (detail lives here, not in the menu)
```

> One bot per install. To run several bots, use several installs/containers. Starting a second bot
> in the same install fails unless you pass `--replace`.

---

## Mental model

**Three config kinds**, one per source folder. The CLI calls these *types*:

| type | lives in | what it is |
|---|---|---|
| `v1-strategy` | `conf/strategies/` | a classic V1 strategy config |
| `v2-script` | `conf/scripts/` | a V2 script config |
| `controller` | `conf/controllers/` | a V2 controller config (its fields can be tuned live) |

Config **file names are unique across the three folders**, so a bare filename is unambiguous — you
almost never type a type flag. `import` / `start` / `config` all detect the type from the
folder that holds the file; a `--v1-strategy` / `--v2-script` / `--controller` flag is only needed to
disambiguate a legacy name that exists under more than one folder.

**The loaded strategy.** Like the interactive client, `hbot` keeps a *currently loaded* config.
`create <strategy>` and `import <file>` both load one (without starting it); `start <file>` loads and
runs it. Once loaded, `hbot config` shows/edits it, and `hbot start` with no argument runs it. The
pointer lives in `data/bot/loaded.json`; a running bot's own config always takes precedence.

**`config` — one command, two scopes.** `hbot config` shows **global** client settings (rate source,
log level, timeouts — `conf/conf_client.yml`, not encrypted) and, when a strategy is loaded, that
**strategy's** config too. `config <key> <value>` edits whichever scope the key belongs to (global
keys win). This is the v1 CLI's *only* config surface — there is no separate `settings` command.

**Controllers** can't run standalone, so `start` generates a tiny V2 loader script for them
automatically; the loader's name becomes the bot's trades-DB and log name. You don't manage the
loader — just `start` the controller config.

---

## Command ontology

The v1 surface mirrors the interactive Kairos-2 client's commands. Flat
— no sub-commands — and every menu is alphabetical.

```
hbot
│
├─ ── set up (funds) ──
│  └─ balance [connector]        balances + USD value (perps: positions + net value)
│
├─ ── create, load & configure ──
│  ├─ create <strategy>          create a strategy config (--set k=v, or --with-defaults to scaffold)
│  ├─ import <config>            load an existing config as the current strategy
│  └─ config [key] [value]       global client settings + the loaded strategy's config
│
├─ ── run & control ──
│  ├─ deploy <target>            one-shot: create/load a config and start it (--set k=v)
│  ├─ start [config]             start a bot (defaults to the imported config); --replace to swap
│  └─ stop                       stop gracefully (cancels orders); --force to kill
│
└─ ── observe & maintain ([name] = a past/stopped bot) ──
   ├─ status                     run state, live status, recent errors
   ├─ logs [name]                tail the log (-f to follow)
   ├─ history [name]             PnL, fees, volume per market
   ├─ doctor                     health check: credentials, clock skew, disk, stale state (exit 0 = healthy)
   └─ update                     update hbot itself to the branch's latest (--check to preview)
```

`doctor` runs the checks whose failures otherwise surface one at a time as confusing runtime
errors: install/extensions sanity, missing Binance credentials in `.env`, **clock skew** vs
internet time (signed exchange requests reject drifted clocks), free disk for the trades DB and
logs, stale `bot.pid`, and a dangling loaded-config pointer. Any `fail` row exits 1; warns are
advisories and exit 0.

`update` updates **the software**, per install type: a source checkout fast-forwards its branch
and rebuilds the Cython extensions only when compiled sources changed; inside a container it fails
fast with the host-side commands (`podman compose pull && podman compose up -d`) — a container
can't replace its own image. It refuses while a bot is running and refuses to guess on a
diverged branch.

See [Roadmap](#roadmap) for commands intentionally left out of v1 (`ticker`, `rate`, `positions`,
`rules`, `book`, `connectors`, `trades`, config `clone`/`list`/`show`).

---

## Walkthrough

```bash
# 1. set your Binance API keys in .env (cp .env.example .env, then fill it in)
hbot balance                                          # confirm funds

# 2. create a strategy config (agents: fill required fields in one shot)
hbot create pmm_simple --name conf_eth.yml \
     --set connector_name=binance_perpetual --set trading_pair=ETH-USDT
#   ...or scaffold it and fill fields afterwards:
hbot create pmm_simple --name conf_eth.yml --with-defaults   # defaults + blanks, and loads it
hbot config                                                  # review global + this strategy's fields
hbot config total_amount_quote 250                           # fill / adjust a field before launch

#   (already have a .yml? skip create and load it:  hbot import conf_eth.yml)

# 3. run it
hbot start                                             # runs the loaded config (or: hbot start conf_eth.yml)
hbot status                                            # is it healthy?
hbot logs -f                                           # watch live (Ctrl-C to stop)

# 4. tune, observe, stop
hbot config buy_spreads 0.001                          # live for controllers (~10s)
hbot history                                           # PnL, fees, volume
hbot stop                                              # graceful, cancels orders

# 5. review a stopped bot later, by name
hbot history conf_eth
```

> **create → config → start.** `create` scaffolds a config from a strategy and *loads* it; `config`
> shows and fills its fields; `start` runs the loaded config. Two ways to fill on create: give every
> required field with `--set key=value` / `--values-stdin` for a **ready-to-run** config (agents), or
> `--with-defaults` to write a **scaffold** (defaults + blank required fields) and finish it with
> `config` (humans). Running `create <strategy>` with a missing required field lists exactly what's
> needed — which also serves as field discovery. Already have a `.yml` (dashboard, API, an example)?
> `import` it instead.

### `deploy` — the one-shot

`deploy` bundles the whole "config → running bot" flow into a single command, for agents and
scripts that don't need the intermediate steps:

```bash
# existing config file → (optional --set edits) → running bot
hbot deploy conf_eth.yml
hbot deploy conf_eth.yml --set total_amount_quote=500

# strategy/controller/script name → create a ready-to-run config → running bot
hbot deploy pmm_simple --set connector_name=binance_perpetual --set trading_pair=ETH-USDT
```

The target is resolved config-file-first (config names are unique across types); anything else must
be a creatable strategy name, with every required field supplied via `--set` / `--values-stdin`
(deploy's contract is a *running* bot, so there is no `--with-defaults`). `--replace`,
`--foreground`, `--timeout`, and `--json` behave exactly as on `start`.

---

## Strategy examples

Every `create`/`deploy` command below is a complete, ready-to-run config (no leftover
`required_remaining` fields) — copy one as-is or swap in your own `market`/`trading_pair`. Amounts
are kept deliberately tiny; scale them up once you've watched a config run and are happy with it.
Two are shown against `binance_paper_trade` since that's what they default to and there's no reason
to risk funds while trying the shape of a config out; swap `exchange`/`connector_name` for `binance`
(spot, no leverage) to run for real. `pmm_dynamic` and `dman_maker_v2` default to
`binance_perpetual` with 20x leverage — halve or zero that before running either live.

**`pure_market_making`** (V1 strategy, `conf/strategies/`) — the classic single-pair market maker.
Not live-tunable; changing a spread means editing the file and restarting.

```bash
hbot create pure_market_making --name conf_pmm.yml \
    --set exchange=binance --set market=BTC-USDT \
    --set bid_spread=0.5 --set ask_spread=0.5 \
    --set order_refresh_time=30 --set order_amount=0.0001
hbot start
```

**`avellaneda_market_making`** (V1 strategy) — Avellaneda–Stoikov inventory-risk model instead of
fixed spreads. `execution_timeframe_mode=infinite` runs until stopped; the alternative is a
date-bounded or daily-time-window run (see `avellaneda_market_making_config_map_pydantic.py` for
the other two modes' fields).

```bash
hbot create avellaneda_market_making --name conf_avellaneda.yml \
    --set exchange=binance --set market=BTC-USDT \
    --set execution_timeframe_mode=infinite \
    --set order_amount=0.0001 --set order_refresh_time=30
hbot start
```

**`pmm_simple`** (V2 controller, `controllers/market_making/`) — fixed spreads on the V2 executor
framework. Fields are live-tunable (`hbot config buy_spreads 0.01,0.02`, ~10s to apply) without a
restart.

```bash
hbot deploy pmm_simple \
    --set connector_name=binance_paper_trade --set trading_pair=BTC-USDT \
    --set total_amount_quote=100 --set buy_spreads=0.01,0.02 --set sell_spreads=0.01,0.02
```

**`pmm_dynamic`** (V2 controller) — spreads widen/narrow with NATR volatility and a MACD-signaled
price shift, instead of staying fixed. Reads candles from the same pair by default
(`candles_connector`/`candles_trading_pair` left blank).

```bash
hbot deploy pmm_dynamic \
    --set connector_name=binance_perpetual --set trading_pair=BTC-USDT \
    --set total_amount_quote=100 --set leverage=1
```

**`dman_maker_v2`** (V2 controller) — market-making quotes plus a DCA ladder (`dca_spreads`/
`dca_amounts`) that averages into a position as price moves against it.

```bash
hbot deploy dman_maker_v2 \
    --set connector_name=binance_perpetual --set trading_pair=BTC-USDT \
    --set total_amount_quote=100 --set leverage=1
```

**`pmm_v1`** (V2 controller, `controllers/generic/`) — the legacy `pure_market_making` algorithm
(multi-level spreads, inventory skew, price bands) re-hosted on the V2 executor framework, so it
gets live-tunable fields and backtesting where the V1 strategy has neither.

```bash
hbot deploy pmm_v1 \
    --set connector_name=binance --set trading_pair=BTC-USDT \
    --set order_amount=0.0001 --set buy_spreads=0.01 --set sell_spreads=0.01
```

**`simple_pmm`** (V2 script, `conf/scripts/`) — the smallest possible market maker, one file, no
controller indirection. This is what `conf_fdusd_paper.yml` in the walkthrough above actually runs.

```bash
hbot create simple_pmm --name conf_simple.yml \
    --set exchange=binance_paper_trade --set trading_pair=BTC-FDUSD \
    --set order_amount=0.001 --set bid_spread=0.001 --set ask_spread=0.001 \
    --set order_refresh_time=15
hbot start
```

---

## Running & observing

- **One bot per install.** `start` fails if one is already running; pass `--replace` to stop it
  first and start the new one. The config's type is auto-detected from its folder.
- `config key value` writes the running bot's config file; controllers apply live-updatable fields
  within ~10s, other fields (and v1/v2 scripts) take effect on next start — the reply says which.
- `status` reports run state, the strategy's live status, and a count of **recent errors** (a bot can
  be alive *and* erroring — check it). `stop` is graceful and cancels open orders.
- `logs` / `history` accept a bot **name** (a config stem from a previous `start`) to inspect a
  past/stopped bot. `history` also fetches live balances, so it's the slowest.
- `logs -f` follows until interrupted — bound it (e.g. a timeout) if you're scripting. Plain `logs`
  returns immediately.

---

## Roadmap

v1 is a **faithful subset of the interactive Kairos-2 client's commands** — the goal is to give
existing source/Podman users the commands they already know, non-interactively. Some commands the
previous CLI shipped are intentionally deferred so v1 stays close to the client's surface. They'll
return in later versions:

| deferred | what it did | v1 alternative |
|---|---|---|
| config `list` / `show` | list creatable strategies; preview a strategy's fields | `create <strategy>` (missing-required error lists fields); `create --with-defaults` + `config` reveals them all |
| config `clone <config>` | copy a config to a new name, tweak fields | `create` a fresh one, or copy the `.yml` by hand |
| `positions <connector>` | open perp positions, standalone | shown inline under `balance` for perp connectors |
| `ticker <connector> <pair>` | best bid/ask/mid + last price | the exchange's public API; a running bot's prices show under `status` |
| `rate <pair>` | rate-oracle conversion rate | the oracle still runs inside the engine; for a spot price use public data |
| `rules <connector> <pair>` | trading rules (min size/notional, tick/step) | — |
| `book <connector> <pair>` | order-book depth | the exchange's public API |
| `connectors` | list available connectors | `hbot doctor` reports whether Binance credentials are set |
| `trades [name]` | recorded fills table | `history` for PnL/fees/volume |

Removing these is not a capability loss in the engine — only in the CLI surface — and each is tracked
to come back once the core client parity is solid.

### Future UX (proposed, beyond client parity)

Commands the interactive client never had, aimed at first-run experience and operability:

| proposed | what it would do | why |
|---|---|---|
| `bots` | list past/stopped bot runs (name, config, last run, quick PnL) | `logs`/`history <name>` already work by name, but nothing *lists* the names |
| `start --paper` | run any config against paper-trade connectors | try a strategy with zero risk before funding it |
| `backtest <config>` | run a controller config through the backtesting engine, report the same PnL table as `history` | the engine ships a backtester; the CLI can't reach it |
| `status --watch` | re-render status every few seconds until interrupted (like `logs -f`) | agents poll; humans want a live panel without the interactive client |
| `export [name]` | trades/orders as CSV to stdout | spreadsheets and tax tools; today it means opening the sqlite DB |
| shell completion | re-enable typer's completion install | discoverability for humans |

---

## Output & exit codes

Every command emits compact **Markdown** by default — a table for a list of records, a `- key: value`
block for a single record — on stdout. Errors print to stderr as `Error: <message> (code N)`. The
run/observe commands (`deploy`, `start`, `stop`, `status`, `logs`, `config`, `balance`) also take
**`--json`** to emit a machine-readable object with raw values (e.g. `hbot status --json` →
`{"running": true, "pid": …, "errors": {…}, …}`). Either way, the machine contract for *outcomes* is
the **exit code** — branch on it, not on the text:

| code | name | meaning |
|---|---|---|
| 0 | SUCCESS | ok |
| 1 | ERROR | generic failure |
| 2 | NOT_FOUND | the bot/config/file doesn't exist |
| 3 | NOT_RUNNING | the bot exists but its process isn't alive |
| 4 | CONFIG_ERROR | bad/missing config or value |
| 5 | TIMEOUT | operation didn't finish in time |

## Credentials

Binance API keys are read from a `.env` file at the repo root — copy `.env.example` to `.env` and
fill in `BINANCE_API_KEY` / `BINANCE_API_SECRET` (used for both `binance` and `binance_perpetual`).
Not needed for `binance_paper_trade`. `hbot doctor` reports whether they're set; a live connector
started without them fails fast with exit code 4.

---

## Paper trade: what it does and does not simulate

`binance_paper_trade` runs your strategy against the **real, live Binance order book and trade feed**
with simulated balances. Nothing is sent to the exchange, so nothing is at risk — but for the same
reason, a profitable paper run is evidence, not proof.

What is simulated:

- **Real fees.** If Binance credentials are configured, paper trade fetches *your account's* actual
  per-pair maker/taker rates in the background and books fills at those — including promos like
  FDUSD's 0% maker. Without credentials it falls back to the exchange's published default schedule.
- **Queue position.** A limit order records the volume already resting at its price level and has to
  wait behind it. It only fills against volume that actually trades at that price, and it can fill
  **partially**, staying on the book with the remainder.
- **Latency.** Sending and cancelling an order both take a configurable round trip. A cancel in
  flight leaves the order fillable, which is what makes *adverse selection* show up — the price runs
  against you, you pull the quote, and you get filled anyway on the way out.

What is **not** simulated, and cannot be:

- **Market impact.** Your order never enters the real book, so it never pushes anyone away or draws
  anyone in, and nobody reacts to it. Sizes small relative to the level you rest on are barely
  affected; sizes that would visibly move the book are not trustworthy here at any setting.

Settings live under `paper_trade` in `conf/conf_client.yml`:

| setting | default | what it does |
|---|---|---|
| `paper_trade_fill_model` | `queue_position` | `optimistic` restores the old behaviour — any print through your price fills the whole order regardless of volume, and the order also fills whenever the book merely reaches its price with nothing having traded. Useful only as an A/B baseline; it flatters results. |
| `paper_trade_latency_ms` | `100` | round trip applied to sending and cancelling |
| `paper_trade_market_order_delay` | `5.0` | seconds a market order waits before executing |
| `paper_trade_account_balance` | see file | starting simulated balances |

Latency resolution is bounded by whatever advances the simulation: on a clock tick that is
`tick_size` (1s by default, floor 0.1s), but on a trade print it is the print's own timestamp, so
sub-tick values still take effect. That is the case that matters — whether an order sat on the book
between two prints makes no difference when nothing could have filled in between.

A useful sanity check is to run the same config twice, once with `paper_trade_fill_model:
optimistic`. If the results are identical, the queue model is not biting — most likely your quotes
sit at prices where nothing is resting, so there is no queue to wait behind.

---

## Running in Podman

> **Recommended for automated/agent-driven setup.** The image ships with the venv and compiled
> Cython extensions prebuilt, so there's no compiler toolchain, no multi-minute extension compile —
> just `make deploy && make link-cli`. Reach for the source install only when you're building or
> modifying the code.

`hbot` works the same in Podman as from source — same commands, same flow. By default `make deploy`
brings up the `kairos-2` container running the classic **interactive client** (`podman attach
kairos-2` to use it). To dedicate the container to `hbot` instead, opt in to the **idle "hbot
host"** mode — the container just stays up and every `hbot` command execs into it — by uncommenting
one line in `docker-compose.yml`:

```bash
# docker-compose.yml, under the kairos-2 service, uncomment:
#   command: tail -f /dev/null

make deploy        # start the container (an idle hbot host)
make link-cli      # install the host `hbot` command (-> podman exec into the container)

hbot import conf_my_bot.yml       # load a config you've placed in conf/ (set BINANCE_API_KEY/
                                   # BINANCE_API_SECRET in .env first for live connectors)
hbot start conf_my_bot.yml
hbot status ; hbot logs -f ; hbot stop
```

The wrapper (`bin/hbot-host`) auto-detects where to run: standing inside a compose project whose
`kairos-2` container is running → `podman exec` into it (the `conf`/`data`/`logs` dirs there are
bind mounts owned by the container's user, so the host CLI couldn't write them anyway); else a
source-install venv (from `make install`) → run there; else a running `kairos-2` container →
`podman exec` into it. So one `hbot <command>` works regardless of how you installed, and
`HBOT_PREFER=container` forces the container on machines that have both. (Without the wrapper,
`podman exec -it kairos-2 hbot <command>` does the same thing.)

> The idle-host container must run a real init (the compose file sets `init: true`) so the bot
> process — which reparents to PID 1 after the `podman exec` that started it returns — gets **reaped**
> on exit. A bare `tail` PID 1 won't reap it, leaving a zombie that makes `hbot stop` wait its full
> timeout. If you `podman run` your own idle host, pass `--init`.

### One dedicated bot per container

For orchestration (one container = one bot, restart policies), make the bot the container's main
process with `hbot start --foreground` — then `podman stop` sends SIGTERM and the bot shuts down
gracefully (cancelling orders):

```yaml
services:
  bot:
    image: kairos-2
    environment: [BINANCE_API_KEY, BINANCE_API_SECRET]
    volumes:
      - ./conf:/home/kairos/conf
      - ./data:/home/kairos/data
      - ./logs:/home/kairos/logs
    command: hbot start conf_my_bot.yml --foreground   # the bot IS the container's PID 1
```

(Without `--foreground`, `hbot start` launches the bot *detached* and returns — fine on a host, but
as a container's command it would exit immediately and stop the container.) Either way, don't run
`hbot` *and* the interactive client in the same container — that's two bots fighting over one
`conf`/`data`/`logs`.

---

## Files & state

```
conf/strategies/   conf/scripts/   conf/controllers/   # your config files (.yml), by type
conf/conf_client.yml                                   # global settings (hbot config)
data/bot/                                              # current bot: meta.json, bot.pid, status.json, bot.log, loaded.json
data/<name>.sqlite                                     # a bot's trades DB (name = config stem)
logs/logs_<name>.log                                   # a bot's structured log
```

`status` reads `data/bot/status.json` (a snapshot the running bot writes every few seconds);
`history` reads the SQLite DB; `logs` tails `logs/logs_<name>.log`; `import` / `start` record the
loaded config in `data/bot/loaded.json`. Because the DB and log are named by the config stem, a
stopped bot's logs/history stay viewable **by name** indefinitely.

Stale state never masquerades as live: the snapshot (markets/orders/balances) is only rendered
while the bot is running, a recorded pid is only trusted if it is actually a Kairos-2 engine
process (an abruptly killed bot — `kill -9`, container restart — can leave `bot.pid` pointing at a
dead or reused pid), and a config imported after the last run supersedes the stopped bot's record
in `status` (shown as `imported, not started`, with the previous run as `last_run`).
