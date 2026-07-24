"""Monitoring loop entry point.

Read-only end to end: fetches positions (public wallet address only),
computes PnL, evaluates the 4 alert conditions, and sends Telegram
notifications. Never signs or sends a Solana transaction.

Run with:  python -m src.main
"""
from __future__ import annotations

import argparse
import time

from . import conditions
from .config import Config, load_config
from .logging_setup import JournalWriter, setup_logging
from .meteora_client import MeteoraReadError, fetch_positions
from .models import ValuedPosition
from .notifier import TelegramNotifier
from .price_provider import get_usd_prices, resolve_token_symbol
from .state_store import StateStore


def build_valued_positions(raw_positions, config: Config, logger) -> list[ValuedPosition]:
    mints: list[str] = []
    for p in raw_positions:
        mints.extend([p.token_x_mint, p.token_y_mint])
    prices = get_usd_prices(mints, config.price_api_base_url)

    valued: list[ValuedPosition] = []
    for p in raw_positions:
        symbol_x = resolve_token_symbol(p.token_x_mint)
        symbol_y = resolve_token_symbol(p.token_y_mint)

        price_x = prices.get(p.token_x_mint) if p.token_x_mint else None
        price_y = prices.get(p.token_y_mint) if p.token_y_mint else None

        value_usd = None
        if price_x is not None and price_y is not None and p.token_x_decimals is not None and p.token_y_decimals is not None:
            amount_x = (p.total_x_amount + p.fee_x_unclaimed) / (10 ** p.token_x_decimals)
            amount_y = (p.total_y_amount + p.fee_y_unclaimed) / (10 ** p.token_y_decimals)
            value_usd = amount_x * price_x + amount_y * price_y
        else:
            logger.warning(
                "Harga/desimal tidak lengkap untuk posisi %s (%s/%s) - PnL dilewati poll ini.",
                p.position_pubkey,
                symbol_x,
                symbol_y,
            )

        valued.append(
            ValuedPosition(raw=p, token_x_symbol=symbol_x, token_y_symbol=symbol_y, value_usd=value_usd)
        )
    return valued


def run_once(config: Config, store: StateStore, notifier: TelegramNotifier, journal: JournalWriter, logger) -> None:
    try:
        raw_positions = fetch_positions(config.wallet_address, config.rpc_url, config.node_reader_script)
    except MeteoraReadError as exc:
        logger.error("Gagal membaca posisi: %s", exc)
        return

    seen_pubkeys = {p.position_pubkey for p in raw_positions}
    newly_closed = store.mark_missing_as_closed(seen_pubkeys)
    for pubkey in newly_closed:
        logger.info("Posisi %s tidak terlihat lagi di wallet, ditandai closed.", pubkey)

    valued_positions = build_valued_positions(raw_positions, config, logger)

    for valued in valued_positions:
        raw = valued.raw
        state = store.get(raw.position_pubkey)
        if state is None:
            if valued.value_usd is None:
                # Belum bisa tentukan baseline nilai deposit tanpa harga - tunggu poll berikutnya.
                continue
            state = store.create(raw.position_pubkey, raw.lb_pair_pubkey, valued.pair_label, valued.value_usd)
            logger.info(
                "Posisi baru terdeteksi: %s (%s), baseline nilai = $%.4f",
                raw.position_pubkey,
                valued.pair_label,
                valued.value_usd,
            )

        events = conditions.evaluate_position(state, valued, config)
        store.save(state)

        journal.write(
            {
                "position_pubkey": raw.position_pubkey,
                "pair": valued.pair_label,
                "value_usd": valued.value_usd,
                "pnl_pct": state.last_pnl_pct,
                "peak_pnl_pct": state.peak_pnl_pct,
                "in_range": raw.in_range,
                "ever_in_range": state.ever_in_range,
                "notifications_sent_this_poll": [e.kind for e in events],
            }
        )

        for event in events:
            sent = notifier.send(event.message)
            logger.info(
                "Notifikasi [%s] untuk %s: %s", event.kind, valued.pair_label, "terkirim" if sent else "GAGAL kirim"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Meteora DLMM read-only monitoring bot")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--once", action="store_true", help="Jalankan satu kali poll lalu keluar (untuk testing)")
    args = parser.parse_args()

    config = load_config(args.config, args.env)
    logger = setup_logging(config.log_file)
    journal = JournalWriter(config.journal_file)
    store = StateStore(config.db_path)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    logger.info(
        "Bot monitoring dimulai (read-only). Wallet: %s | Interval: %ss",
        config.wallet_address,
        config.poll_interval_seconds,
    )

    try:
        if args.once:
            run_once(config, store, notifier, journal, logger)
            return
        while True:
            run_once(config, store, notifier, journal, logger)
            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Dihentikan oleh user (Ctrl+C).")
    finally:
        store.close()


if __name__ == "__main__":
    main()
