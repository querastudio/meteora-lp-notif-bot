"""Load config.yaml + .env into a single typed Config object.

This module only reads configuration. It never reads or stores a private
key / seed phrase anywhere - only a public wallet address and Telegram
credentials for sending (not receiving) messages.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Thresholds:
    sl_percent: float
    tp_floor_lock: float
    tp_trailing_drawdown: float
    tp_fast_threshold: float
    idle_timeout_hours: float


@dataclass(frozen=True)
class Config:
    wallet_address: str
    rpc_url: str
    thresholds: Thresholds
    poll_interval_seconds: int
    price_api_base_url: str
    meteora_app_base_url: str
    utc_offset_hours: int
    node_reader_script: Path
    db_path: Path
    log_file: Path
    journal_file: Path
    telegram_bot_token: str
    telegram_chat_id: str


def load_config(config_path: str | Path = "config.yaml", env_path: str | Path = ".env") -> Config:
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file tidak ditemukan: {config_path}. "
            "Salin config.example.yaml ke config.yaml lalu isi datanya."
        )

    env_path = Path(env_path)
    if not env_path.is_absolute():
        env_path = REPO_ROOT / env_path
    load_dotenv(dotenv_path=env_path)

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    wallet_address = raw.get("wallet_address", "")
    if not wallet_address or wallet_address.startswith("GANTI_DENGAN"):
        raise ValueError(
            "wallet_address belum diisi di config.yaml. "
            "Isi dengan wallet address PUBLIK Anda (bukan private key)."
        )

    telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not telegram_bot_token or not telegram_chat_id:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi di .env. "
            "Salin .env.example ke .env lalu isi datanya."
        )

    th = raw.get("thresholds", {})
    thresholds = Thresholds(
        sl_percent=float(th.get("sl_percent", -10.0)),
        tp_floor_lock=float(th.get("tp_floor_lock", 3.0)),
        tp_trailing_drawdown=float(th.get("tp_trailing_drawdown", 5.0)),
        tp_fast_threshold=float(th.get("tp_fast_threshold", 5.0)),
        idle_timeout_hours=float(th.get("idle_timeout_hours", 3.0)),
    )

    node_script = raw.get("node_reader", {}).get("script_path", "node_reader/fetch_positions.js")
    node_script_path = Path(node_script)
    if not node_script_path.is_absolute():
        node_script_path = REPO_ROOT / node_script_path

    db_path = Path(raw.get("database", {}).get("path", "data/state.db"))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path

    log_file = Path(raw.get("logging", {}).get("log_file", "logs/bot.log"))
    if not log_file.is_absolute():
        log_file = REPO_ROOT / log_file

    journal_file = Path(raw.get("logging", {}).get("journal_file", "logs/evaluations.jsonl"))
    if not journal_file.is_absolute():
        journal_file = REPO_ROOT / journal_file

    return Config(
        wallet_address=wallet_address,
        rpc_url=raw.get("solana", {}).get("rpc_url", "https://api.mainnet-beta.solana.com"),
        thresholds=thresholds,
        poll_interval_seconds=int(raw.get("polling", {}).get("interval_seconds", 45)),
        price_api_base_url=raw.get("price_api", {}).get("base_url", "https://lite-api.jup.ag/price/v3"),
        meteora_app_base_url=raw.get("meteora", {}).get("app_base_url", "https://app.meteora.ag/dlmm"),
        utc_offset_hours=int(raw.get("timezone", {}).get("utc_offset_hours", 7)),
        node_reader_script=node_script_path,
        db_path=db_path,
        log_file=log_file,
        journal_file=journal_file,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
