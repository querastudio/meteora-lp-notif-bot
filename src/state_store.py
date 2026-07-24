"""SQLite persistence for per-position monitoring state.

Only bookkeeping data lives here (entry value, peak PnL, which
notifications were already sent, whether the position has ever been
in-range). Nothing here touches the chain - it is pure local state.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .timeutil import now_utc

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    position_pubkey TEXT PRIMARY KEY,
    lb_pair_pubkey TEXT NOT NULL,
    pair_label TEXT NOT NULL,
    entry_value_usd REAL NOT NULL,
    entry_time TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_pnl_pct REAL,
    peak_pnl_pct REAL,
    ever_in_range INTEGER NOT NULL DEFAULT 0,
    notified_sl INTEGER NOT NULL DEFAULT 0,
    notified_floor_lock INTEGER NOT NULL DEFAULT 0,
    notified_trailing_stop INTEGER NOT NULL DEFAULT 0,
    notified_floor_touch INTEGER NOT NULL DEFAULT 0,
    notified_fast_tp INTEGER NOT NULL DEFAULT 0,
    notified_idle INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class PositionState:
    position_pubkey: str
    lb_pair_pubkey: str
    pair_label: str
    entry_value_usd: float
    entry_time: str
    last_seen_at: str
    last_pnl_pct: float | None
    peak_pnl_pct: float | None
    ever_in_range: bool
    notified_sl: bool
    notified_floor_lock: bool
    notified_trailing_stop: bool
    notified_floor_touch: bool
    notified_fast_tp: bool
    notified_idle: bool
    closed: bool


class StateStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def get(self, position_pubkey: str) -> PositionState | None:
        row = self.conn.execute(
            "SELECT * FROM positions WHERE position_pubkey = ?", (position_pubkey,)
        ).fetchone()
        if row is None:
            return None
        return PositionState(
            position_pubkey=row["position_pubkey"],
            lb_pair_pubkey=row["lb_pair_pubkey"],
            pair_label=row["pair_label"],
            entry_value_usd=row["entry_value_usd"],
            entry_time=row["entry_time"],
            last_seen_at=row["last_seen_at"],
            last_pnl_pct=row["last_pnl_pct"],
            peak_pnl_pct=row["peak_pnl_pct"],
            ever_in_range=bool(row["ever_in_range"]),
            notified_sl=bool(row["notified_sl"]),
            notified_floor_lock=bool(row["notified_floor_lock"]),
            notified_trailing_stop=bool(row["notified_trailing_stop"]),
            notified_floor_touch=bool(row["notified_floor_touch"]),
            notified_fast_tp=bool(row["notified_fast_tp"]),
            notified_idle=bool(row["notified_idle"]),
            closed=bool(row["closed"]),
        )

    def create(self, position_pubkey: str, lb_pair_pubkey: str, pair_label: str, entry_value_usd: float) -> PositionState:
        ts = now_utc().isoformat()
        self.conn.execute(
            """INSERT INTO positions
               (position_pubkey, lb_pair_pubkey, pair_label, entry_value_usd,
                entry_time, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (position_pubkey, lb_pair_pubkey, pair_label, entry_value_usd, ts, ts),
        )
        self.conn.commit()
        return self.get(position_pubkey)

    def save(self, state: PositionState) -> None:
        self.conn.execute(
            """UPDATE positions SET
                 lb_pair_pubkey = ?, pair_label = ?, last_seen_at = ?,
                 last_pnl_pct = ?, peak_pnl_pct = ?, ever_in_range = ?,
                 notified_sl = ?, notified_floor_lock = ?,
                 notified_trailing_stop = ?, notified_floor_touch = ?,
                 notified_fast_tp = ?, notified_idle = ?, closed = ?
               WHERE position_pubkey = ?""",
            (
                state.lb_pair_pubkey,
                state.pair_label,
                state.last_seen_at,
                state.last_pnl_pct,
                state.peak_pnl_pct,
                int(state.ever_in_range),
                int(state.notified_sl),
                int(state.notified_floor_lock),
                int(state.notified_trailing_stop),
                int(state.notified_floor_touch),
                int(state.notified_fast_tp),
                int(state.notified_idle),
                int(state.closed),
                state.position_pubkey,
            ),
        )
        self.conn.commit()

    def mark_missing_as_closed(self, seen_position_pubkeys: set[str]) -> list[str]:
        """Positions we tracked before but no longer see in the wallet ->
        assume closed/withdrawn by the user and stop evaluating them."""
        rows = self.conn.execute(
            "SELECT position_pubkey FROM positions WHERE closed = 0"
        ).fetchall()
        newly_closed = []
        for row in rows:
            pubkey = row["position_pubkey"]
            if pubkey not in seen_position_pubkeys:
                self.conn.execute(
                    "UPDATE positions SET closed = 1 WHERE position_pubkey = ?", (pubkey,)
                )
                newly_closed.append(pubkey)
        if newly_closed:
            self.conn.commit()
        return newly_closed

    def close(self) -> None:
        self.conn.close()
