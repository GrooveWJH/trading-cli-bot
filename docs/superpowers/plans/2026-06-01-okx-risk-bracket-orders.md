# OKX Risk Bracket Orders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe OKX take-profit / stop-loss trigger order management to `tbot` with dry-run planning, exact live confirmation, pending-order listing, and cancel support.

**Architecture:** Keep risk order logic separate from wallet and trade execution. A small domain/application layer builds OKX algo-order payloads and confirmation phrases; the CLI layer handles Typer validation, JSON output, client creation, and live/private API calls. Live mutation commands require exact confirmation and default to dry-run planning.

**Tech Stack:** Python 3.11+, Typer CLI, ccxt OKX private REST wrappers (`privatePostTradeOrderAlgo`, `privateGetTradeOrdersAlgoPending`, `privatePostTradeCancelAlgos`), unittest.

---

### Task 1: Risk Bracket Planning

**Files:**
- Create: `src/trading_gateway/application/risk/__init__.py`
- Create: `src/trading_gateway/application/risk/okx_algo.py`
- Test: `tests/test_standalone_cli.py`

- [x] **Step 1: Write failing tests**

Add tests that import `build_okx_bracket_plan`, verify long TP/SL payload side is `sell`, verify short TP/SL payload side is `buy`, verify confirmation phrase includes symbol, side, size, TP, and SL, and verify missing TP/SL is rejected.

- [x] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_standalone_cli.py -v`
Expected: import/function missing failures for risk planning.

- [x] **Step 3: Implement minimal planner**

Create `okx_algo.py` with `OkxBracketIntent`, `build_okx_bracket_plan`, `okx_bracket_confirm_phrase`, and validation helpers. Use two separate OKX `conditional` algo payloads, one TP and one SL, because OKX net mode conditional TP+SL has problematic semantics.

- [x] **Step 4: Run tests and verify GREEN**

Run the same unittest command. Expected: all tests pass.

### Task 2: Risk CLI Commands

**Files:**
- Create: `src/trading_gateway/interfaces/cli/risk.py`
- Modify: `src/trading_gateway/interfaces/cli/app.py`
- Modify: `src/trading_gateway/interfaces/cli/help.py`
- Test: `tests/test_standalone_cli.py`

- [x] **Step 1: Write failing CLI tests**

Add tests for `tbot risk plan okx BTC-USDT-SWAP long 2.56 --take-profit 76000 --stop-loss 72900 --json`, bad confirm rejection, and live call using mocked client methods.

- [x] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests/test_standalone_cli.py -v`
Expected: `risk` command missing.

- [x] **Step 3: Implement CLI**

Register `risk` Typer app with commands:
- `risk plan EXCHANGE SYMBOL SIDE SIZE --take-profit --stop-loss --trigger-px-type --order-px --margin-mode --json`
- `risk bracket ... --live --confirm --json`
- `risk orders EXCHANGE [SYMBOL] --json`
- `risk cancel EXCHANGE SYMBOL ALGO_ID... --json --confirm`

For v1, support only `exchange=okx`; unsupported exchanges return `BadParameter`.

- [x] **Step 4: Run tests and verify GREEN**

Run the same unittest command. Expected: all tests pass.

### Task 3: Docs and Real Read-Only Verification

**Files:**
- Modify: `README.md`
- Modify: `../README.md`

- [x] **Step 1: Update docs**

Document dry-run plan examples, live confirmation, pending algo order listing, and cancel semantics.

- [x] **Step 2: Run verification**

Run:
- `PYTHONPATH=src .venv/bin/python -m unittest tests/test_standalone_cli.py -v`
- `../tbot risk plan okx BTC-USDT-SWAP long 2.56 --take-profit 76000 --stop-loss 72900 --json`
- `../tbot risk orders okx --json`

Expected: tests pass, plan emits two order-algo payloads and confirmation phrase, orders returns OKX pending algo orders or a redacted exchange error.

- [x] **Step 3: Commit and push**

Run:
```bash
git add src/trading_gateway/application/risk src/trading_gateway/interfaces/cli tests/test_standalone_cli.py README.md ../README.md
git commit -m "Add OKX risk bracket orders"
git push
```
