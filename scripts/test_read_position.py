"""Sanity-check script: baca posisi wallet Anda dari Meteora DLMM dan hitung
nilai USD-nya, TANPA menyimpan state dan TANPA mengirim notifikasi.

Jalankan dari root project:
    python -m scripts.test_read_position

Gunakan ini dulu sebelum menjalankan bot penuh (`python -m src.main`) untuk
memastikan wallet address, RPC, dan node_reader sudah bekerja dengan benar.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.main import build_valued_positions
from src.meteora_client import MeteoraReadError, fetch_positions
from src.logging_setup import setup_logging


def main() -> None:
    config = load_config()
    logger = setup_logging(config.log_file)

    print(f"Membaca posisi untuk wallet: {config.wallet_address}")
    print(f"RPC: {config.rpc_url}\n")

    try:
        raw_positions = fetch_positions(config.wallet_address, config.rpc_url, config.node_reader_script)
    except MeteoraReadError as exc:
        print(f"GAGAL: {exc}")
        sys.exit(1)

    if not raw_positions:
        print("Tidak ada posisi DLMM aktif yang ditemukan untuk wallet ini.")
        return

    valued_positions = build_valued_positions(raw_positions, config, logger)
    for v in valued_positions:
        raw = v.raw
        print(f"--- Posisi {raw.position_pubkey} ---")
        print(f"  Pair            : {v.pair_label}")
        print(f"  LB Pair         : {raw.lb_pair_pubkey}")
        print(f"  Range bin       : {raw.lower_bin_id} .. {raw.upper_bin_id} (active: {raw.active_bin_id})")
        print(f"  In range?       : {raw.in_range}")
        print(f"  Total X / Y     : {raw.total_x_amount} / {raw.total_y_amount} (raw units)")
        print(f"  Fee unclaimed   : {raw.fee_x_unclaimed} / {raw.fee_y_unclaimed} (raw units)")
        if v.value_usd is not None:
            print(f"  Estimasi nilai  : ${v.value_usd:,.4f}")
        else:
            print("  Estimasi nilai  : tidak tersedia (gagal ambil harga token)")
        print()


if __name__ == "__main__":
    main()
