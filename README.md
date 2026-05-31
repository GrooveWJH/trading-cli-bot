# Trading CLI Bot

Standalone local trading CLI extracted from `ArbitrageStation/services/trading_gateway`.

It can:

- read balances, positions, and open orders for `binance / okx / gate / mexc`
- create dry-run trade plans without placing orders
- run live single-leg, pair, and transfer operations only after explicit confirmation
- plan, place, list, and cancel OKX reduce-only TP/SL trigger orders
- start a localhost-only daemon required by live mutation commands

## Safety Model

- Default planning commands are read-only.
- Real order commands require the daemon plus an exact `confirm_phrase`.
- API keys are read from local `.env`; they are not printed by the CLI.
- Keep withdrawal permission disabled on every exchange API key.
- Prefer small quote sizes until every route is verified.

## Setup

```bash
cd trading-cli-bot
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

This extraction already copied the original local `.env` into `trading-cli-bot/.env` when it existed. The file is gitignored.

## Read-Only Checks

```bash
../tbot --help
../tbot summary
../tbot balance okx perp
../tbot positions okx
../tbot orders okx perp BTC/USDT
../tbot risk orders okx --json
```

## Dry-Run Planning

Dry-run planning with a static price does not need network access or credentials:

```bash
../tbot trade plan \
  --exchange okx \
  --market perp \
  --symbol BTC/USDT \
  --side buy \
  --quote-usdt 10 \
  --last-price 70000 \
  --json
```

Live-style planning with exchange market data:

```bash
../tbot trade plan \
  --exchange okx \
  --market perp \
  --symbol BTC/USDT \
  --side buy \
  --quote-usdt 10
```

## Live Execution

Start the local daemon first:

```bash
../tbot daemon start
../tbot daemon status
```

Then plan, copy the exact confirmation phrase, and run:

```bash
../tbot trade smoke \
  --exchange okx \
  --market perp \
  --symbol BTC/USDT \
  --side buy \
  --quote-usdt 10 \
  --live \
  --confirm "LIVE_ORDER:okx:perp:BTC/USDT:10"
```

If the daemon is not healthy, the live route fails before placing an order.

## OKX TP/SL Trigger Orders

Risk commands manage OKX server-side conditional algo orders. Planning is dry-run:

```bash
../tbot risk plan okx BTC-USDT-SWAP long 2.56 \
  --take-profit 76000 \
  --stop-loss 72900 \
  --json
```

For a long position, the generated orders are reduce-only `sell` triggers. For a short
position, they are reduce-only `buy` triggers. The default `--order-px -1` asks OKX to
send a market order after the trigger fires.

Live placement requires the exact phrase emitted by the plan:

```bash
../tbot risk bracket okx BTC-USDT-SWAP long 2.56 \
  --take-profit 76000 \
  --stop-loss 72900 \
  --live \
  --confirm "LIVE_BRACKET:okx:BTC-USDT-SWAP:long:2.56:TP_76000:SL_72900"
```

List pending OKX conditional algo orders:

```bash
../tbot risk orders okx --json
../tbot risk orders okx BTC-USDT-SWAP --json
```

Cancel pending algo orders with an explicit confirmation phrase:

```bash
../tbot risk cancel okx BTC-USDT-SWAP 3609646938838437888 \
  --confirm "LIVE_CANCEL_ALGOS:okx:BTC-USDT-SWAP:3609646938838437888"
```

OKX net-position conditional orders are created as separate TP and SL algos rather
than one combined request, so both sides remain visible and cancellable.

## Config

- Config: `config.toml`
- Secrets: `.env`
- Runtime files: `var/run`
- Wallet cache: `var/cache`
- Pair journals: `var/pair_journal`

The inherited public market names are `spot` and `perp`.
