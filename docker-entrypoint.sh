#!/bin/sh
# Menulis config.yaml dari environment variables (diisi lewat dashboard web
# Railway/Render, bukan file), lalu menjalankan bot loop terus-menerus.
set -e

: "${SOLANA_RPC_URL:=https://api.mainnet-beta.solana.com}"
: "${POLL_INTERVAL_SECONDS:=45}"

cat > /app/config.yaml <<YAML
wallet_address: "${WALLET_ADDRESS}"
solana:
  rpc_url: "${SOLANA_RPC_URL}"
thresholds:
  sl_percent: -10.0
  tp_floor_lock: 3.0
  tp_trailing_drawdown: 5.0
  tp_fast_threshold: 5.0
  idle_timeout_hours: 3
polling:
  interval_seconds: ${POLL_INTERVAL_SECONDS}
price_api:
  base_url: "https://lite-api.jup.ag/price/v3"
meteora:
  app_base_url: "https://app.meteora.ag/dlmm"
timezone:
  utc_offset_hours: 7
node_reader:
  script_path: "node_reader/fetch_positions.js"
database:
  path: "data/state.db"
logging:
  log_file: "logs/bot.log"
  journal_file: "logs/evaluations.jsonl"
YAML

if [ -z "${WALLET_ADDRESS}" ] || [ -z "${TELEGRAM_BOT_TOKEN}" ] || [ -z "${TELEGRAM_CHAT_ID}" ]; then
  echo "GAGAL: environment variable WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, dan TELEGRAM_CHAT_ID wajib diisi di dashboard hosting Anda." >&2
  exit 1
fi

mkdir -p /app/data /app/logs
exec python -m src.main
