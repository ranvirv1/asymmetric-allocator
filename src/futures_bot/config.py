"""Configuration loader for the futures trading bot."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config_futures.yaml"
DATA_DIR = PROJECT_ROOT / "data" / "futures"


def load_config(path: Path | str | None = None) -> dict:
    p = Path(path) if path else CONFIG_PATH
    with open(p) as f:
        cfg = yaml.safe_load(f)
    _apply_env_overrides(cfg)
    return cfg


def _apply_env_overrides(cfg: dict) -> None:
    """Inject secrets from environment / .env — never store credentials in YAML."""
    cfg.setdefault("execution", {})
    cfg["execution"]["webhook_url"] = os.getenv("NINJATRADER_WEBHOOK_URL", "")
    cfg["execution"]["webhook_secret"] = os.getenv("NINJATRADER_WEBHOOK_SECRET", "")
    alerts = cfg.setdefault("alerts", {})
    tg = alerts.setdefault("telegram", {})
    tg["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", "")
    email = alerts.setdefault("email", {})
    email["smtp_password"] = os.getenv("SMTP_PASSWORD", "")


def instrument_spec(cfg: dict, symbol: str) -> dict:
    """Return tick_size, tick_value, margin, commission for the given instrument."""
    spec = cfg["instruments"].get(symbol)
    if not spec:
        raise ValueError(f"Unknown instrument: {symbol}. Configure in config_futures.yaml.")
    return spec
