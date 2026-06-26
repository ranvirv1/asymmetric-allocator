"""Alert system — Telegram, email, and console notifications (§6).

Sends alerts on every fill, every error, and a daily P&L summary.
Fails gracefully if credentials are missing (logs a warning, doesn't crash).
"""
from __future__ import annotations

import json
import logging
import smtplib
from email.mime.text import MIMEText

import requests

logger = logging.getLogger("futures_bot.alerts")


def send_alert(message: str, cfg: dict, level: str = "info") -> None:
    """Route an alert to all configured channels."""
    alerts = cfg.get("alerts", {})

    _console(message, level)

    if alerts.get("telegram", {}).get("enabled"):
        _telegram(message, alerts["telegram"])

    if alerts.get("email", {}).get("enabled"):
        _email(message, alerts["email"], level)


def send_fill_alert(trade_summary: str, cfg: dict) -> None:
    if cfg.get("alerts", {}).get("on_fill"):
        send_alert(f"FILL: {trade_summary}", cfg)


def send_error_alert(error_msg: str, cfg: dict) -> None:
    if cfg.get("alerts", {}).get("on_error"):
        send_alert(f"ERROR: {error_msg}", cfg, level="error")


def send_daily_summary(summary: dict, cfg: dict) -> None:
    if cfg.get("alerts", {}).get("daily_summary"):
        lines = [
            f"Daily Summary — {summary.get('date', 'today')}",
            f"Trades: {summary['trades']}  |  P&L: ${summary['pnl']:,.2f}",
            f"Winners: {summary['winners']}  |  Losers: {summary['losers']}",
            f"Win Rate: {summary.get('win_rate', 0):.1f}%",
            f"Signals: {summary.get('signals', 0)}  |  Errors: {summary.get('errors', 0)}",
        ]
        send_alert("\n".join(lines), cfg)


def _console(message: str, level: str) -> None:
    if level == "error":
        logger.error(message)
    else:
        logger.info(message)


def _telegram(message: str, tg_cfg: dict) -> None:
    token = tg_cfg.get("bot_token", "")
    chat_id = tg_cfg.get("chat_id", "")
    if not token or not chat_id:
        logger.warning("Telegram alert skipped — missing bot_token or chat_id")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
    except Exception as e:
        logger.warning("Telegram alert failed: %s", e)


def _email(message: str, email_cfg: dict, level: str) -> None:
    sender = email_cfg.get("sender", "")
    recipient = email_cfg.get("recipient", "")
    if not sender or not recipient:
        logger.warning("Email alert skipped — missing sender or recipient")
        return
    try:
        msg = MIMEText(message)
        msg["Subject"] = f"[FuturesBot] {level.upper()}: Alert"
        msg["From"] = sender
        msg["To"] = recipient
        with smtplib.SMTP(email_cfg.get("smtp_host", ""), email_cfg.get("smtp_port", 587)) as s:
            s.starttls()
            pwd = email_cfg.get("smtp_password", "")
            if pwd:
                s.login(sender, pwd)
            s.send_message(msg)
    except Exception as e:
        logger.warning("Email alert failed: %s", e)
