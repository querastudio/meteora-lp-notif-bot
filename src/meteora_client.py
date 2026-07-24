"""READ-ONLY client for fetching Meteora DLMM positions.

This module shells out to `node_reader/fetch_positions.js`, which calls the
official read query `DLMM.getAllLbPairPositionsByUser()` from the
`@meteora-ag/dlmm` SDK. Nothing in this file (or the script it calls) ever
builds, signs, or sends a Solana transaction. There is no Keypair anywhere
in this codebase - only a public wallet address is used to query positions.
"""
from __future__ import annotations

import json
import logging
import subprocess

from .models import RawPosition

logger = logging.getLogger(__name__)


class MeteoraReadError(RuntimeError):
    pass


def fetch_positions(wallet_address: str, rpc_url: str, node_reader_script) -> list[RawPosition]:
    """Fetch all open DLMM positions for `wallet_address` (public key only).

    Runs `node node_reader/fetch_positions.js <wallet> <rpc_url>` and parses
    the JSON it prints to stdout. Raises MeteoraReadError on failure so the
    caller can log it and simply skip this poll cycle.
    """
    cmd = ["node", str(node_reader_script), wallet_address, rpc_url]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MeteoraReadError(
            "Perintah 'node' tidak ditemukan. Install Node.js dan jalankan "
            "'npm install' di folder node_reader/ terlebih dahulu."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MeteoraReadError("Timeout saat membaca posisi dari RPC Solana.") from exc

    if result.returncode != 0:
        raise MeteoraReadError(
            f"fetch_positions.js gagal (exit {result.returncode}): {result.stderr.strip()}"
        )

    try:
        raw_list = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MeteoraReadError(f"Output fetch_positions.js bukan JSON valid: {exc}") from exc

    positions: list[RawPosition] = []
    for item in raw_list:
        positions.append(
            RawPosition(
                position_pubkey=item["position_pubkey"],
                lb_pair_pubkey=item["lb_pair_pubkey"],
                token_x_mint=item.get("token_x_mint"),
                token_y_mint=item.get("token_y_mint"),
                token_x_decimals=item.get("token_x_decimals"),
                token_y_decimals=item.get("token_y_decimals"),
                active_bin_id=item.get("active_bin_id"),
                lower_bin_id=item["lower_bin_id"],
                upper_bin_id=item["upper_bin_id"],
                total_x_amount=int(item["total_x_amount"]),
                total_y_amount=int(item["total_y_amount"]),
                fee_x_unclaimed=int(item["fee_x_unclaimed"]),
                fee_y_unclaimed=int(item["fee_y_unclaimed"]),
            )
        )
    return positions
