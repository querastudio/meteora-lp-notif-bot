"""Two log outputs:

- `log_file`: normal rotating text log for operational debugging.
- `journal_file`: one JSON line per evaluated position per poll (not just
  the ones that triggered a notification), so it can double as a trading
  journal / audit trail against your manual decisions later.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .timeutil import now_utc


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("meteora_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


class JournalWriter:
    def __init__(self, journal_file: Path):
        self.journal_file = journal_file
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        record = {"logged_at": now_utc().isoformat(), **record}
        with open(self.journal_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
