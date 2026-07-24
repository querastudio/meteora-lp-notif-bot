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
    wallet_address TEXT NOT NULL DEFAULT '',
    lb_pair_pubkey TEXT NOT NULL,
    pair_label TEXT NOT NULL,
    entry_value_usd REAL NOT NULL,
    entry_time TEXT NOT NULL,
    position_opened_at TEXT,
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

CREATE TABLE IF NOT EXISTS bot_health (
    wallet_address TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    failure_alert_sent INTEGER NOT NULL DEFAULT 0
);
"""

# SQLite happily opens old databases created before a column existed; this
# keeps upgrades in place instead of requiring users to delete data/state.db.
_MIGRATIONS = [
    ("positions", "wallet_address", "TEXT NOT NULL DEFAULT ''"),
    ("positions", "position_opened_at", "TEXT"),
]


@dataclass
class PositionState:
    position_pubkey: str
    wallet_address: str
    lb_pair_pubkey: str
    pair_label: str
    entry_value_usd: float
    entry_time: str
    position_opened_at: str | None
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

    @property
    def idle_clock_start(self) -> str:
        """Real on-chain creation time when known, else first-seen-by-bot."""
        return self.position_opened_at or self.entry_time


@dataclass
class BotHealth:
    wallet_address: str
    consecutive_failures: int
    failure_alert_sent: bool


class StateStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._apply_migrations()
        self.conn.commit()

    def _apply_migrations(self) -> None:
        for table, column, coltype in _MIGRATIONS:
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

    # -- positions -----------------------------------------------------

    def _row_to_state(self, row: sqlite3.Row) -> PositionState:
        return PositionState(
            position_pubkey=row["position_pubkey"],
            wallet_address=row["wallet_address"],
            lb_pair_pubkey=row["lb_pair_pubkey"],
            pair_label=row["pair_label"],
            entry_value_usd=row["entry_value_usd"],
            entry_time=row["entry_time"],
            position_opened_at=row["position_opened_at"],
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

    def get(self, position_pubkey: str) -> PositionState | None:
        row = self.conn.execute(
            "SELECT * FROM positions WHERE position_pubkey = ?", (position_pubkey,)
        ).fetchone()
        return self._row_to_state(row) if row is not None else None

    def create(
        self,
        position_pubkey: str,
        wallet_address: str,
        lb_pair_pubkey: str,
        pair_label: str,
        entry_value_usd: float,
        position_opened_at: str | None = None,
    ) -> PositionState:
        ts = now_utc().isoformat()
        self.conn.execute(
            """INSERT INTO positions
               (position_pubkey, wallet_address, lb_pair_pubkey, pair_label,
                entry_value_usd, entry_time, position_opened_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (position_pubkey, wallet_address, lb_pair_pubkey, pair_label, entry_value_usd, ts, position_opened_at, ts),
        )
        self.conn.commit()
        return self.get(position_pubkey)

    def save(self, state: PositionState) -> None:
        self.conn.execute(
            """UPDATE positions SET
                 lb_pair_pubkey = ?, pair_label = ?, last_seen_at = ?,
                 position_opened_at = COALESCE(position_opened_at, ?),
                 last_pnl_pct = ?, peak_pnl_pct = ?, ever_in_range = ?,
                 notified_sl = ?, notified_floor_lock = ?,
                 notified_trailing_stop = ?, notified_floor_touch = ?,
                 notified_fast_tp = ?, notified_idle = ?, closed = ?
               WHERE position_pubkey = ?""",
            (
                state.lb_pair_pubkey,
                state.pair_label,
                state.last_seen_at,
                state.position_opened_at,
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

    def list_pubkeys_with_known_open_time(self) -> set[str]:
        """Positions whose real on-chain creation time we've already
        resolved - used to skip the extra on-chain lookup for them on
        future polls. Positions NOT in this set (including ones we already
        have a row for, if the lookup failed/was skipped before) get
        retried, so a transient RPC failure doesn't leave them stuck on the
        first-seen-by-bot fallback forever."""
        rows = self.conn.execute(
            "SELECT position_pubkey FROM positions WHERE position_opened_at IS NOT NULL"
        ).fetchall()
        return {row["position_pubkey"] for row in rows}

    def list_open_positions(self, wallet_address: str | None = None) -> list[PositionState]:
        if wallet_address is None:
            rows = self.conn.execute("SELECT * FROM positions WHERE closed = 0").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM positions WHERE closed = 0 AND wallet_address = ?", (wallet_address,)
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def mark_missing_as_closed(self, wallet_address: str, seen_position_pubkeys: set[str]) -> list[str]:
        """Positions we tracked before for this wallet but no longer see ->
        assume closed/withdrawn by the user and stop evaluating them."""
        rows = self.conn.execute(
            "SELECT position_pubkey FROM positions WHERE closed = 0 AND wallet_address = ?",
            (wallet_address,),
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

    # -- bot health (consecutive fetch failures) ------------------------

    def get_health(self, wallet_address: str) -> BotHealth:
        row = self.conn.execute(
            "SELECT * FROM bot_health WHERE wallet_address = ?", (wallet_address,)
        ).fetchone()
        if row is None:
            return BotHealth(wallet_address=wallet_address, consecutive_failures=0, failure_alert_sent=False)
        return BotHealth(
            wallet_address=row["wallet_address"],
            consecutive_failures=row["consecutive_failures"],
            failure_alert_sent=bool(row["failure_alert_sent"]),
        )

    def save_health(self, health: BotHealth) -> None:
        self.conn.execute(
            """INSERT INTO bot_health (wallet_address, consecutive_failures, failure_alert_sent)
               VALUES (?, ?, ?)
               ON CONFLICT(wallet_address) DO UPDATE SET
                 consecutive_failures = excluded.consecutive_failures,
                 failure_alert_sent = excluded.failure_alert_sent""",
            (health.wallet_address, health.consecutive_failures, int(health.failure_alert_sent)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
