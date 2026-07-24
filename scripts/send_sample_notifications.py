"""Kirim contoh (sample) tiap jenis notifikasi bot ke Telegram.

INI BUKAN TRIGGER ASLI - tidak membaca posisi wallet, tidak menyentuh
data/state.db, tidak mempengaruhi pemantauan sungguhan. Hanya memakai posisi
& PnL rekaan untuk memicu src.conditions.evaluate_position() secara sengaja,
supaya format/isi pesan yang dikirim identik dengan notifikasi asli (bukan
teks yang ditulis ulang manual dan bisa melenceng dari kode sebenarnya).

Jalankan dari root project:
    python -m scripts.send_sample_notifications
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import conditions
from src.config import load_config
from src.models import RawPosition, ValuedPosition
from src.notifier import TelegramNotifier
from src.state_store import PositionState
from src.timeutil import now_utc

SAMPLE_PREFIX = "🧪 CONTOH/TEST (bukan notifikasi asli - posisi & PnL rekaan)\n\n"


def _raw(in_range: bool) -> RawPosition:
    return RawPosition(
        position_pubkey="ContohPosisi1111111111111111111111111111",
        lb_pair_pubkey="ContohLbPair1111111111111111111111111111",
        token_x_mint="ContohMintX", token_y_mint="ContohMintY",
        token_x_decimals=9, token_y_decimals=6,
        active_bin_id=100 if in_range else 500,
        lower_bin_id=90, upper_bin_id=110,
        total_x_amount=0, total_y_amount=0,
        fee_x_unclaimed=0, fee_y_unclaimed=0,
        total_claimed_fee_x=0, total_claimed_fee_y=0,
        opened_at=None,
    )


def _state(entry_time=None) -> PositionState:
    entry_iso = (entry_time or now_utc()).isoformat()
    return PositionState(
        position_pubkey="contoh", wallet_address="ContohWallet", lb_pair_pubkey="contoh-pair",
        pair_label="SOL-USDC", entry_value_usd=100.0, entry_time=entry_iso,
        position_opened_at=entry_iso,
        last_seen_at=now_utc().isoformat(), last_pnl_pct=None, peak_pnl_pct=None,
        ever_in_range=False, notified_sl=False, notified_floor_lock=False,
        notified_trailing_stop=False, notified_floor_touch=False,
        notified_fast_tp=False, notified_idle=False, closed=False,
    )


def _valued(pnl_pct: float, in_range: bool = True) -> ValuedPosition:
    value = 100.0 * (1 + pnl_pct / 100)
    return ValuedPosition(raw=_raw(in_range), token_x_symbol="SOL", token_y_symbol="USDC", value_usd=value)


def collect_samples(config) -> list:
    samples = []

    # 1) Stop loss
    state = _state()
    samples += conditions.evaluate_position(state, _valued(-11.0), config)

    # 2) Floor lock -> trailing stop terpicu -> floor touch (satu alur bertahap)
    state = _state()
    for pnl in (4.0, 10.0, 4.0, 3.0):
        samples += conditions.evaluate_position(state, _valued(pnl), config)

    # 3) Fast TP (lompat langsung tanpa sempat floor-lock bertahap)
    state = _state()
    for pnl in (1.0, 6.0):
        samples += conditions.evaluate_position(state, _valued(pnl), config)

    # 4) Idle timeout ("cabut posisi")
    idle_hours = config.thresholds.idle_timeout_hours + 1
    state = _state(entry_time=now_utc() - timedelta(hours=idle_hours))
    samples += conditions.evaluate_position(state, _valued(0.0, in_range=False), config)

    return samples


def main() -> None:
    config = load_config()
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    samples = collect_samples(config)

    print(f"Mengirim {len(samples)} contoh notifikasi ke Telegram...")
    for event in samples:
        ok = notifier.send(SAMPLE_PREFIX + event.message)
        print(f"[{event.kind}] {'terkirim' if ok else 'GAGAL'}")


if __name__ == "__main__":
    main()
