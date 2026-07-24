"""Telegram notifications - outbound only. This bot never reads Telegram
updates/commands, so a lightweight direct HTTP call to sendMessage is
enough; no need for the full python-telegram-bot framework."""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, message: str) -> bool:
        try:
            resp = requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": message},
                timeout=15,
            )
            if not resp.ok:
                logger.error("Gagal kirim notifikasi Telegram (%s): %s", resp.status_code, resp.text)
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - jangan biarkan error jaringan mematikan loop
            logger.error("Gagal kirim notifikasi Telegram: %s", exc)
            return False
