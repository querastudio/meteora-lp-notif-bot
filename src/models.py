"""Plain data structures shared across modules. No I/O here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawPosition:
    """One position exactly as read from the Meteora DLMM SDK (read-only)."""

    position_pubkey: str
    lb_pair_pubkey: str
    token_x_mint: str | None
    token_y_mint: str | None
    token_x_decimals: int | None
    token_y_decimals: int | None
    active_bin_id: int | None
    lower_bin_id: int
    upper_bin_id: int
    total_x_amount: int
    total_y_amount: int
    fee_x_unclaimed: int
    fee_y_unclaimed: int

    @property
    def in_range(self) -> bool | None:
        if self.active_bin_id is None:
            return None
        return self.lower_bin_id <= self.active_bin_id <= self.upper_bin_id


@dataclass
class ValuedPosition:
    """A RawPosition plus USD valuation + human-friendly labels."""

    raw: RawPosition
    token_x_symbol: str
    token_y_symbol: str
    value_usd: float | None  # None kalau harga token gagal diambil poll ini

    @property
    def pair_label(self) -> str:
        return f"{self.token_x_symbol}-{self.token_y_symbol}"


@dataclass
class NotificationEvent:
    kind: str
    message: str
