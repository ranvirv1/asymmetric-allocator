"""NinjaTrader execution bridge — webhook and NinjaScript integration (§2).

Sends bracket orders to NinjaTrader for broker-side execution. The webhook bridge
translates signals into NinjaTrader-compatible order commands. Bracket orders
ensure stops fire even if the bot disconnects.

Auto-reconnect with exponential backoff on disconnect.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import requests

from .orders import BracketOrder
from .signals import Direction

logger = logging.getLogger("futures_bot.execution")


class ExecutionError(Exception):
    pass


class NinjaTraderBridge:
    def __init__(self, cfg: dict):
        exec_cfg = cfg["execution"]
        self.webhook_url = exec_cfg.get("webhook_url", "")
        self.webhook_secret = exec_cfg.get("webhook_secret", "")
        self.mode = exec_cfg.get("mode", "webhook")
        self.connected = False
        sess_cfg = cfg.get("session", {})
        self.max_retries = sess_cfg.get("reconnect_max_retries", 10)
        self.backoff = sess_cfg.get("reconnect_backoff_seconds", 5)

    def connect(self) -> bool:
        if self.mode == "webhook":
            if not self.webhook_url:
                logger.warning("No webhook URL configured — running in dry-run mode")
                self.connected = False
                return False
            self.connected = True
            logger.info("NinjaTrader webhook bridge ready: %s", self.webhook_url[:30] + "...")
            return True
        logger.warning("NinjaScript mode not yet implemented — use webhook mode")
        return False

    def submit_bracket(self, order: BracketOrder) -> dict:
        """Submit a bracket order (entry + stop + target) to NinjaTrader."""
        payload = {
            "action": "BRACKET",
            "instrument": order.instrument,
            "direction": "BUY" if order.direction == Direction.LONG else "SELL",
            "contracts": order.contracts,
            "entry_price": order.entry_price,
            "stop_price": order.stop_price,
            "target_price": order.target_price,
            "order_id": order.order_id,
        }

        if not self.connected or not self.webhook_url:
            logger.info("DRY RUN — would submit: %s", json.dumps(payload))
            return {"status": "dry_run", "order_id": order.order_id}

        return self._send(payload)

    def flatten_all(self) -> dict:
        """Kill switch — flatten all open positions immediately (§6)."""
        payload = {"action": "FLATTEN_ALL"}
        logger.warning("KILL SWITCH — flattening all positions")
        if not self.connected or not self.webhook_url:
            logger.info("DRY RUN — would flatten all")
            return {"status": "dry_run", "action": "FLATTEN_ALL"}
        return self._send(payload)

    def cancel_order(self, order_id: str) -> dict:
        payload = {"action": "CANCEL", "order_id": order_id}
        if not self.connected or not self.webhook_url:
            return {"status": "dry_run", "action": "CANCEL", "order_id": order_id}
        return self._send(payload)

    def _send(self, payload: dict) -> dict:
        for attempt in range(self.max_retries):
            try:
                headers = {"Content-Type": "application/json"}
                if self.webhook_secret:
                    body = json.dumps(payload, sort_keys=True)
                    sig = hmac.new(
                        self.webhook_secret.encode(), body.encode(), hashlib.sha256
                    ).hexdigest()
                    headers["X-Signature"] = sig

                resp = requests.post(
                    self.webhook_url, json=payload, headers=headers, timeout=10,
                )
                resp.raise_for_status()
                logger.info("Order submitted: %s", resp.text[:200])
                return resp.json() if resp.text else {"status": "ok"}
            except requests.exceptions.RequestException as e:
                wait = self.backoff * (2 ** attempt)
                logger.warning("Webhook attempt %d/%d failed: %s — retrying in %ds",
                               attempt + 1, self.max_retries, e, wait)
                time.sleep(wait)

        raise ExecutionError(
            f"Failed to submit order after {self.max_retries} attempts"
        )
