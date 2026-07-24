"""Kirim ringkasan harian semua posisi terbuka ke Telegram.

Membaca data/state.db (hasil poll bot yang sudah tersimpan) - TIDAK
membaca wallet/RPC lagi, murni menyusun satu pesan ringkasan dari data
yang sudah ada. Dipicu sekali sehari lewat cron terpisah di
.github/workflows/monitor.yml.

Jalankan dari root project:
    python -m scripts.send_daily_summary
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.notifier import TelegramNotifier
from src.state_store import PositionState, StateStore
from src.timeutil import format_local, now_utc


def _short(addr: str) -> str:
    return f"{addr[:4]}..{addr[-4:]}" if addr and len(addr) > 10 else (addr or "-")


def build_summary(positions: list[PositionState], utc_offset_hours: int) -> str:
    ts = format_local(now_utc(), utc_offset_hours)

    if not positions:
        return f"📊 Ringkasan Harian LP - {ts}\n\nTidak ada posisi aktif yang sedang dipantau."

    lines = [f"📊 Ringkasan Harian LP - {ts}\n"]
    for i, p in enumerate(sorted(positions, key=lambda p: p.pair_label), start=1):
        pnl = f"{p.last_pnl_pct:+.2f}%" if p.last_pnl_pct is not None else "belum ada data"
        peak = f"{p.peak_pnl_pct:+.2f}%" if p.peak_pnl_pct is not None else "-"
        range_status = "pernah masuk range" if p.ever_in_range else "belum pernah masuk range"
        lines.append(
            f"{i}. {p.pair_label} (wallet {_short(p.wallet_address)})\n"
            f"   PnL: {pnl} | Peak: {peak} | {range_status}"
        )
    lines.append(f"\nTotal posisi aktif dipantau: {len(positions)}")
    return "\n".join(lines)


def main() -> None:
    config = load_config()
    store = StateStore(config.db_path)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    message = build_summary(store.list_open_positions(), config.utc_offset_hours)
    ok = notifier.send(message)
    print("Ringkasan harian terkirim." if ok else "GAGAL kirim ringkasan harian.")
    store.close()


if __name__ == "__main__":
    main()
