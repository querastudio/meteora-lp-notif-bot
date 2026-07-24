"""Pure evaluation logic for the four notification conditions.

Nothing in this module performs I/O (no network, no DB, no Telegram calls)
- it only reads/mutates a PositionState object and returns the list of
NotificationEvents that should be sent this poll. That makes it easy to
unit test independently of the rest of the bot.
"""
from __future__ import annotations

from datetime import datetime

from .config import Config
from .models import NotificationEvent, ValuedPosition
from .state_store import PositionState
from .timeutil import now_utc, format_local


def compute_pnl_pct(entry_value_usd: float, current_value_usd: float) -> float:
    if entry_value_usd <= 0:
        return 0.0
    return (current_value_usd - entry_value_usd) / entry_value_usd * 100.0


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _position_link(valued: ValuedPosition, app_base_url: str) -> str:
    return f"{app_base_url}/{valued.raw.lb_pair_pubkey}"


def evaluate_position(state: PositionState, valued: ValuedPosition, config: Config) -> list[NotificationEvent]:
    thresholds = config.thresholds
    events: list[NotificationEvent] = []
    raw = valued.raw
    label = valued.pair_label
    now = now_utc()
    ts_str = format_local(now, config.utc_offset_hours)
    link = _position_link(valued, config.meteora_app_base_url)

    if valued.value_usd is None:
        # Harga token gagal diambil poll ini - jangan evaluasi PnL, cukup catat kita masih melihat posisi ini.
        state.last_seen_at = now.isoformat()
        return events

    pnl_pct = compute_pnl_pct(state.entry_value_usd, valued.value_usd)
    previous_pnl = state.last_pnl_pct

    if raw.in_range:
        state.ever_in_range = True

    # 4) IDLE TIMEOUT - posisi belum pernah masuk range sampai batas waktu.
    # Pakai waktu pembuatan on-chain kalau sudah berhasil diambil (lebih
    # akurat), fallback ke waktu pertama kali bot melihat posisi ini kalau
    # belum/tidak berhasil diambil.
    if not state.ever_in_range and not state.notified_idle:
        entry_dt = _parse_iso(state.idle_clock_start)
        elapsed_hours = (now - entry_dt).total_seconds() / 3600.0
        if elapsed_hours >= thresholds.idle_timeout_hours:
            events.append(
                NotificationEvent(
                    kind="idle_timeout",
                    message=(
                        f"⏰ Posisi {label} idle {thresholds.idle_timeout_hours:.0f} jam tanpa masuk range — "
                        f"pertimbangkan CABUT manual, evaluasi ulang token ini dari awal.\n"
                        f"Dibuka: {format_local(entry_dt, config.utc_offset_hours)}\n"
                        f"Waktu cek: {ts_str}\n"
                        f"{link}"
                    ),
                )
            )
            state.notified_idle = True

    # 1) STOP LOSS
    if not state.notified_sl and pnl_pct <= thresholds.sl_percent:
        events.append(
            NotificationEvent(
                kind="stop_loss",
                message=(
                    f"⛔ SL {thresholds.sl_percent:.0f}% tercapai di {label} — segera cek dan tutup manual.\n"
                    f"PnL saat ini: {pnl_pct:+.2f}%\n"
                    f"Waktu: {ts_str}\n"
                    f"{link}"
                ),
            )
        )
        state.notified_sl = True

    # 3) FAST TP - lompat langsung >= tp_fast_threshold tanpa sempat floor-lock lebih dulu
    jumped_fast = (
        not state.notified_fast_tp
        and not state.notified_floor_lock
        and previous_pnl is not None
        and previous_pnl < thresholds.tp_floor_lock
        and pnl_pct >= thresholds.tp_fast_threshold
    )
    if jumped_fast:
        events.append(
            NotificationEvent(
                kind="fast_tp",
                message=(
                    f"🎯 PnL +{thresholds.tp_fast_threshold:.0f}%+ tercapai cepat di {label} — "
                    f"pertimbangkan amankan profit manual sekarang, jangan tunggu naik lebih tinggi.\n"
                    f"PnL saat ini: {pnl_pct:+.2f}%\n"
                    f"Waktu: {ts_str}\n"
                    f"{link}"
                ),
            )
        )
        state.notified_fast_tp = True
        # Trailing tetap diaktifkan diam-diam (tanpa notif floor-lock terpisah)
        # supaya profit yang sudah didapat tetap terlindungi trailing ke depan.
        state.notified_floor_lock = True
        state.peak_pnl_pct = pnl_pct
    elif not state.notified_floor_lock and pnl_pct >= thresholds.tp_floor_lock:
        # 2a) FLOOR LOCK AKTIF
        events.append(
            NotificationEvent(
                kind="floor_lock",
                message=(
                    f"🔒 Profit lock aktif di {label} — floor {thresholds.tp_floor_lock:.0f}% terkunci, "
                    f"trailing {thresholds.tp_trailing_drawdown:.0f}% mulai berjalan.\n"
                    f"PnL saat ini: {pnl_pct:+.2f}%\n"
                    f"Waktu: {ts_str}\n"
                    f"{link}"
                ),
            )
        )
        state.notified_floor_lock = True
        state.peak_pnl_pct = pnl_pct

    # Update peak PnL (hanya berlaku setelah floor lock aktif)
    if state.notified_floor_lock and (state.peak_pnl_pct is None or pnl_pct > state.peak_pnl_pct):
        state.peak_pnl_pct = pnl_pct

    # 2b) TRAILING STOP TERPICU - turun tpTrailingDrawdown poin dari peak
    if (
        state.notified_floor_lock
        and not state.notified_trailing_stop
        and state.peak_pnl_pct is not None
        and state.peak_pnl_pct >= thresholds.tp_floor_lock
        and pnl_pct <= state.peak_pnl_pct - thresholds.tp_trailing_drawdown
    ):
        events.append(
            NotificationEvent(
                kind="trailing_stop",
                message=(
                    f"📉 Trailing stop terpicu di {label} — turun dari peak +{state.peak_pnl_pct:.2f}% "
                    f"ke {pnl_pct:+.2f}%, segera amankan profit manual.\n"
                    f"Waktu: {ts_str}\n"
                    f"{link}"
                ),
            )
        )
        state.notified_trailing_stop = True

    # 2c) FLOOR TOUCH - PnL turun tepat ke floor 3%, pengingat terakhir sebelum wilayah SL
    if state.notified_floor_lock and not state.notified_floor_touch and pnl_pct <= thresholds.tp_floor_lock:
        events.append(
            NotificationEvent(
                kind="floor_touch",
                message=(
                    f"⚠️ PnL {label} turun ke floor {thresholds.tp_floor_lock:.0f}% (sekarang {pnl_pct:+.2f}%) — "
                    f"pengingat terakhir sebelum masuk wilayah SL, segera evaluasi manual.\n"
                    f"Waktu: {ts_str}\n"
                    f"{link}"
                ),
            )
        )
        state.notified_floor_touch = True

    state.last_pnl_pct = pnl_pct
    state.last_seen_at = now.isoformat()
    return events
