"""USD price + token symbol lookups (read-only, public APIs, no auth).

Third-party price API URLs/response shapes change over time (Jupiter has
moved from price v1 -> v2 -> v3 in the past). If this module starts
failing, check `price_api.base_url` in config.yaml and the current docs at
https://dev.jup.ag - you usually only need to update the URL, not the code
below, since the parser tries a few common response shapes.
"""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# Mint -> symbol for the handful of tokens that show up in almost every
# Meteora DLMM pool, so notifications stay readable even if the token
# metadata API is down or its response shape changed.
KNOWN_SYMBOLS = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
}

_symbol_cache: dict[str, str] = dict(KNOWN_SYMBOLS)


def _get_jupiter_prices(mints: list[str], base_url: str) -> dict[str, float]:
    try:
        resp = requests.get(base_url, params={"ids": ",".join(mints)}, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - network/parse errors are all "unavailable"
        logger.warning("Gagal ambil harga token dari %s: %s", base_url, exc)
        return {}

    data = payload.get("data", payload)  # some versions return the map directly
    prices: dict[str, float] = {}
    for mint in mints:
        entry = data.get(mint)
        if entry is None:
            continue
        # Confirmed live response shape (lite-api.jup.ag/price/v3): {"usdPrice": ...}.
        # Keep "price" as a fallback in case the API reverts/changes again.
        if isinstance(entry, dict):
            price_val = entry.get("usdPrice", entry.get("price"))
        else:
            price_val = entry
        try:
            prices[mint] = float(price_val)
        except (TypeError, ValueError):
            logger.warning("Format harga tidak dikenali untuk mint %s: %r", mint, entry)
    return prices


def _get_dexscreener_prices(mints: list[str]) -> dict[str, float]:
    """Fallback price source for mints Jupiter has no data for - common for
    very new/illiquid pump.fun-style tokens that a DLMM pool got created for
    before the bigger price aggregators picked them up. Public, no API key.
    """
    if not mints:
        return {}
    try:
        resp = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{','.join(mints)}", timeout=15
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal ambil harga fallback dari DexScreener: %s", exc)
        return {}

    mint_set = set(mints)
    best_liquidity: dict[str, float] = {}
    prices: dict[str, float] = {}
    for pair in payload.get("pairs") or []:
        base = pair.get("baseToken") or {}
        mint = base.get("address")
        if mint not in mint_set:
            continue

        # Bonus: warm the symbol cache while we're already fetching this
        # pair, so resolve_token_symbol() usually doesn't need its own
        # extra request for tokens that already needed a price fallback.
        symbol = base.get("symbol")
        if symbol and mint not in _symbol_cache:
            _symbol_cache[mint] = symbol

        try:
            price = float(pair.get("priceUsd"))
        except (TypeError, ValueError):
            continue
        # A token can have many pools (Raydium, Meteora, pump.fun bonding
        # curve, ...) - use the one with the most liquidity as the best
        # estimate of the "real" price.
        liquidity = ((pair.get("liquidity") or {}).get("usd")) or 0
        if mint not in best_liquidity or liquidity > best_liquidity[mint]:
            best_liquidity[mint] = liquidity
            prices[mint] = price
    return prices


def get_usd_prices(mints: list[str], base_url: str) -> dict[str, float]:
    """Return {mint: usd_price} for as many mints as could be resolved,
    trying Jupiter first and DexScreener as a fallback for whatever's left.

    Missing/failed mints are simply absent from the result - callers must
    treat that as "PnL unavailable this poll", not crash the loop.
    """
    mints = [m for m in dict.fromkeys(mints) if m]  # dedupe, drop None/empty
    if not mints:
        return {}

    prices = _get_jupiter_prices(mints, base_url)

    missing = [m for m in mints if m not in prices]
    if missing:
        fallback_prices = _get_dexscreener_prices(missing)
        if fallback_prices:
            logger.info("Harga %d mint diambil dari fallback DexScreener.", len(fallback_prices))
        prices.update(fallback_prices)

    return prices


def _dexscreener_symbol(mint: str) -> str | None:
    try:
        resp = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=10)
        if resp.ok:
            for pair in resp.json().get("pairs") or []:
                base = pair.get("baseToken") or {}
                if base.get("address") == mint and base.get("symbol"):
                    return base["symbol"]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gagal resolve symbol dari DexScreener untuk %s: %s", mint, exc)
    return None


def _jupiter_symbol(mint: str) -> str | None:
    try:
        resp = requests.get(f"https://lite-api.jup.ag/tokens/v1/token/{mint}", timeout=10)
        if resp.ok:
            return resp.json().get("symbol")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gagal resolve symbol dari Jupiter untuk %s: %s", mint, exc)
    return None


def resolve_token_symbol(mint: str | None) -> str:
    """Best-effort symbol lookup: DexScreener first (best coverage for very
    new pump.fun-style tokens, and often already warmed in the cache by
    get_usd_prices()'s fallback path), then Jupiter's token metadata API,
    falling back to a truncated mint address only if both fail."""
    if not mint:
        return "?"
    if mint in _symbol_cache:
        return _symbol_cache[mint]

    symbol = _dexscreener_symbol(mint) or _jupiter_symbol(mint)
    if symbol:
        _symbol_cache[mint] = symbol
        return symbol

    short = f"{mint[:4]}..{mint[-4:]}"
    _symbol_cache[mint] = short
    return short
