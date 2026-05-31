from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import typer


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "tbot.py"
CONFIG = ROOT / "config.toml"


class StandaloneCliTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_default_config_uses_local_env_file(self) -> None:
        from trading_gateway.app.config import load_gateway_config

        config = load_gateway_config(CONFIG)

        self.assertEqual(Path(config.dotenv_path), Path(".env"))

    def test_trade_plan_with_static_price_is_dry_run_json(self) -> None:
        result = self.run_cli(
            "trade",
            "plan",
            "--exchange",
            "okx",
            "--market",
            "perp",
            "--symbol",
            "BTC/USDT",
            "--side",
            "buy",
            "--quote-usdt",
            "10",
            "--last-price",
            "70000",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["exchange"], "okx")
        self.assertEqual(payload["market"], "perp")
        self.assertEqual(payload["symbol"], "BTC/USDT")
        self.assertIn("live_confirm_phrase", payload)
        self.assertEqual(payload["live_confirm_phrase"], "LIVE_ORDER:okx:perp:BTC/USDT:10")

    def test_live_smoke_rejects_bad_confirm_before_exchange_access(self) -> None:
        result = self.run_cli(
            "trade",
            "smoke",
            "--exchange",
            "okx",
            "--market",
            "perp",
            "--symbol",
            "BTC/USDT",
            "--side",
            "buy",
            "--quote-usdt",
            "10",
            "--last-price",
            "70000",
            "--live",
            "--confirm",
            "wrong",
            "--json",
        )

        combined_output = f"{result.stdout}\n{result.stderr}"
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirmation mismatch", combined_output)
        self.assertNotIn("IP whitelist", combined_output)
        self.assertNotIn("www.okx.com", combined_output)

    def test_positions_reports_private_api_failure_instead_of_empty_positions(self) -> None:
        from trading_gateway.interfaces.cli import wallet

        snapshot = {
            "exchange": "okx",
            "status": "partial_error",
            "warnings": ["okx perp PermissionDenied: IP whitelist"],
            "perp": {
                "positions": [],
                "status": "okx perp PermissionDenied: IP whitelist",
            },
        }

        with patch.object(wallet, "fetch_exchange_snapshot", return_value=snapshot):
            with self.assertRaises(typer.BadParameter) as raised:
                wallet.wallet_positions("okx")

        self.assertIn("IP whitelist", str(raised.exception))

    def test_orders_reports_redacted_exchange_failure_without_traceback(self) -> None:
        from trading_gateway.interfaces.cli import wallet

        error = RuntimeError("okx PermissionDenied: API key secret-api-key is not in IP whitelist")

        with patch.dict(os.environ, {"OKX_API_KEY": "secret-api-key"}):
            with patch.object(wallet, "_wallet_snapshot", side_effect=error):
                with self.assertRaises(typer.BadParameter) as raised:
                    wallet.wallet_orders("okx", "perp", "BTC/USDT")

        text = str(raised.exception)
        self.assertIn("IP whitelist", text)
        self.assertIn("<redacted>", text)
        self.assertNotIn("secret-api-key", text)

    def test_okx_bracket_plan_for_long_uses_sell_reduce_only_algos(self) -> None:
        from trading_gateway.application.risk.okx_algo import build_okx_bracket_plan

        plan = build_okx_bracket_plan("okx", "BTC-USDT-SWAP", "long", 2.56, take_profit=76000, stop_loss=72900)

        self.assertEqual(plan["mode"], "plan")
        self.assertEqual(plan["confirm_phrase"], "LIVE_BRACKET:okx:BTC-USDT-SWAP:long:2.56:TP_76000:SL_72900")
        self.assertEqual([order["kind"] for order in plan["algo_orders"]], ["take_profit", "stop_loss"])
        for order in plan["algo_orders"]:
            payload = order["payload"]
            self.assertEqual(payload["instId"], "BTC-USDT-SWAP")
            self.assertEqual(payload["tdMode"], "cross")
            self.assertEqual(payload["side"], "sell")
            self.assertEqual(payload["sz"], "2.56")
            self.assertEqual(payload["ordType"], "conditional")
            self.assertEqual(payload["reduceOnly"], "true")
        self.assertEqual(plan["algo_orders"][0]["payload"]["tpTriggerPx"], "76000")
        self.assertEqual(plan["algo_orders"][0]["payload"]["tpOrdPx"], "-1")
        self.assertEqual(plan["algo_orders"][1]["payload"]["slTriggerPx"], "72900")
        self.assertEqual(plan["algo_orders"][1]["payload"]["slOrdPx"], "-1")

    def test_okx_bracket_plan_for_short_uses_buy_reduce_only_algos(self) -> None:
        from trading_gateway.application.risk.okx_algo import build_okx_bracket_plan

        plan = build_okx_bracket_plan("okx", "INTC-USDT-SWAP", "short", 0.3, take_profit=108.16, stop_loss=121.13)

        self.assertEqual(plan["confirm_phrase"], "LIVE_BRACKET:okx:INTC-USDT-SWAP:short:0.3:TP_108.16:SL_121.13")
        self.assertEqual({order["payload"]["side"] for order in plan["algo_orders"]}, {"buy"})

    def test_okx_bracket_plan_requires_take_profit_or_stop_loss(self) -> None:
        from trading_gateway.application.risk.okx_algo import build_okx_bracket_plan

        with self.assertRaises(ValueError):
            build_okx_bracket_plan("okx", "BTC-USDT-SWAP", "long", 2.56)

    def test_risk_plan_cli_outputs_confirmation_phrase(self) -> None:
        result = self.run_cli(
            "risk",
            "plan",
            "okx",
            "BTC-USDT-SWAP",
            "long",
            "2.56",
            "--take-profit",
            "76000",
            "--stop-loss",
            "72900",
            "--json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["confirm_phrase"], "LIVE_BRACKET:okx:BTC-USDT-SWAP:long:2.56:TP_76000:SL_72900")
        self.assertEqual(len(payload["algo_orders"]), 2)

    def test_risk_bracket_rejects_bad_live_confirm_before_exchange_access(self) -> None:
        result = self.run_cli(
            "risk",
            "bracket",
            "okx",
            "BTC-USDT-SWAP",
            "long",
            "2.56",
            "--take-profit",
            "76000",
            "--stop-loss",
            "72900",
            "--live",
            "--confirm",
            "wrong",
            "--json",
        )

        combined_output = f"{result.stdout}\n{result.stderr}"
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirmation mismatch", combined_output)
        self.assertNotIn("IP whitelist", combined_output)
        self.assertNotIn("www.okx.com", combined_output)

    def test_risk_bracket_live_places_two_okx_algo_orders_after_confirm(self) -> None:
        from trading_gateway.interfaces.cli import risk

        class FakeClient:
            def __init__(self) -> None:
                self.payloads: list[dict] = []
                self.closed = False

            def privatePostTradeOrderAlgo(self, payload: dict) -> dict:
                self.payloads.append(payload)
                return {"code": "0", "data": [{"algoId": str(len(self.payloads))}]}

            def close(self) -> None:
                self.closed = True

        client = FakeClient()
        output = StringIO()

        with patch.object(risk, "build_ccxt_client", return_value=client) as build_client:
            with redirect_stdout(output):
                risk.risk_bracket(
                    "okx",
                    "BTC-USDT-SWAP",
                    "long",
                    2.56,
                    take_profit=76000,
                    stop_loss=72900,
                    live=True,
                    confirm="LIVE_BRACKET:okx:BTC-USDT-SWAP:long:2.56:TP_76000:SL_72900",
                    json_output=True,
                )

        build_client.assert_called_once_with("okx", "swap", require_private=True)
        self.assertEqual(json.loads(output.getvalue())["status"], "live")
        self.assertTrue(client.closed)
        self.assertEqual(len(client.payloads), 2)
        self.assertEqual(client.payloads[0]["tpTriggerPx"], "76000")
        self.assertEqual(client.payloads[1]["slTriggerPx"], "72900")

    def test_risk_cancel_rejects_bad_confirm_before_exchange_access(self) -> None:
        from trading_gateway.interfaces.cli import risk

        with patch.object(risk, "build_ccxt_client") as build_client:
            with self.assertRaises(typer.BadParameter) as raised:
                risk.risk_cancel(
                    "okx",
                    "BTC-USDT-SWAP",
                    ["123", "456"],
                    confirm="wrong",
                    json_output=True,
                )

        build_client.assert_not_called()
        self.assertIn("LIVE_CANCEL_ALGOS:okx:BTC-USDT-SWAP:123,456", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
