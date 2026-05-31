from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
