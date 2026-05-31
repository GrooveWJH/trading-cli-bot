from __future__ import annotations

import os
from pathlib import Path

from trading_gateway.domain.models import ExchangeCreds, normalize_exchange

from .loader import load_config_file
from .schema import GatewayConfig


DEFAULT_ENV_FILE = Path(".env")
DEFAULT_CONFIG_FILE = Path("config.toml")

_ACTIVE_CONFIG: GatewayConfig | None = None


def load_gateway_config(path: str | Path = DEFAULT_CONFIG_FILE) -> GatewayConfig:
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = load_config_file(Path(path))
    return _ACTIVE_CONFIG


def get_gateway_config() -> GatewayConfig:
    return _ACTIVE_CONFIG or load_gateway_config()


def load_dotenv_file(path: str | Path) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_exchange_creds(exchange: str) -> ExchangeCreds:
    name = normalize_exchange(exchange)
    spec = get_gateway_config().credential_envs[name]
    key = (os.getenv(spec.key_env) or "").strip()
    secret = (os.getenv(spec.secret_env) or "").strip()
    password = (os.getenv(spec.password_env) or "").strip() if spec.password_env else ""
    return ExchangeCreds(api_key=key, api_secret=secret, password=password or None)


def require_exchange_creds(exchange: str) -> ExchangeCreds:
    creds = read_exchange_creds(exchange)
    if not creds.api_key or not creds.api_secret:
        raise ValueError(f"{exchange} API key/secret missing in env")
    return creds
