#!/usr/bin/env node
/**
 * READ-ONLY Meteora DLMM position reader.
 *
 * This script ONLY calls the official read query
 * `DLMM.getAllLbPairPositionsByUser(connection, ownerPublicKey)` from the
 * `@meteora-ag/dlmm` SDK (https://github.com/MeteoraAg/dlmm-sdk), which
 * requires nothing but a public wallet address.
 *
 * DO NOT add any of the following to this file: Keypair, Wallet, signer,
 * sendTransaction, signTransaction, addLiquidity, removeLiquidity,
 * closePosition, claimFee, or anything from a private key / .env secret.
 * If you need those for the future execution-bot phase, that belongs in a
 * completely separate project with its own limited-fund wallet.
 *
 * Usage:
 *   node fetch_positions.js <WALLET_ADDRESS> [RPC_URL]
 *
 * Output: a single line of JSON (array of positions) on stdout.
 * Any human-readable diagnostics go to stderr so stdout stays parseable.
 */

const { Connection, PublicKey } = require("@solana/web3.js");
const { getMint, TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID } = require("@solana/spl-token");
// The package's CommonJS build exports the DLMM class as module.exports
// itself (with everything else attached as static properties) - there is
// no `.default` in this version. Handle both shapes defensively in case
// that changes again in a future SDK release.
const dlmmModule = require("@meteora-ag/dlmm");
const DLMM = typeof dlmmModule.getAllLbPairPositionsByUser === "function"
  ? dlmmModule
  : dlmmModule.default;

function toStr(bnLike) {
  if (bnLike === null || bnLike === undefined) return null;
  if (typeof bnLike.toString === "function") return bnLike.toString();
  return String(bnLike);
}

// The exact property names for mint pubkey / decimals inside `tokenX` /
// `tokenY` (TokenReserve) have shifted across SDK versions. `lbPair.tokenXMint`
// / `tokenYMint` are the canonical mint addresses from the on-chain account,
// so prefer those; `tokenReserve.publicKey` is the pool's reserve TOKEN
// ACCOUNT (not the mint) in some SDK versions, so it is only used as a last
// resort fallback, never first.
function extractMint(tokenReserve, lbPair, side) {
  const candidates = [
    lbPair && lbPair[side === "x" ? "tokenXMint" : "tokenYMint"],
    tokenReserve && tokenReserve.mint,
    tokenReserve && tokenReserve.publicKey,
  ].filter(Boolean);
  return candidates.length ? candidates[0].toString() : null;
}

// Many newer SPL tokens (and some DLMM pools) use the Token-2022 program
// instead of the classic SPL Token program - getMint() must be pointed at
// the right owner program or it throws TokenInvalidAccountOwnerError.
async function resolveDecimals(connection, tokenReserve, mintAddress, cache) {
  if (tokenReserve && typeof tokenReserve.decimal === "number") {
    return tokenReserve.decimal;
  }
  if (tokenReserve && typeof tokenReserve.decimals === "number") {
    return tokenReserve.decimals;
  }
  if (!mintAddress) return null;
  if (cache.has(mintAddress)) return cache.get(mintAddress);

  const mintPubkey = new PublicKey(mintAddress);
  let info;
  try {
    info = await getMint(connection, mintPubkey, "confirmed", TOKEN_PROGRAM_ID);
  } catch (err) {
    info = await getMint(connection, mintPubkey, "confirmed", TOKEN_2022_PROGRAM_ID);
  }
  cache.set(mintAddress, info.decimals);
  return info.decimals;
}

async function main() {
  const [, , walletArg, rpcArg] = process.argv;
  if (!walletArg) {
    console.error("Usage: node fetch_positions.js <WALLET_ADDRESS> [RPC_URL]");
    process.exit(1);
  }

  const rpcUrl =
    rpcArg || process.env.SOLANA_RPC_URL || "https://api.mainnet-beta.solana.com";
  const connection = new Connection(rpcUrl, "confirmed");
  const owner = new PublicKey(walletArg);
  const decimalsCache = new Map();

  const positionsByPool = await DLMM.getAllLbPairPositionsByUser(connection, owner);

  const output = [];
  for (const [lbPairPubkey, info] of positionsByPool.entries()) {
    const lbPair = info.lbPair || {};
    const mintX = extractMint(info.tokenX, lbPair, "x");
    const mintY = extractMint(info.tokenY, lbPair, "y");
    const decimalX = await resolveDecimals(connection, info.tokenX, mintX, decimalsCache);
    const decimalY = await resolveDecimals(connection, info.tokenY, mintY, decimalsCache);
    const activeBinId = lbPair.activeId ?? null;

    for (const pos of info.lbPairPositionsData) {
      const pd = pos.positionData;
      output.push({
        position_pubkey: pos.publicKey.toString(),
        lb_pair_pubkey: lbPairPubkey,
        token_x_mint: mintX,
        token_y_mint: mintY,
        token_x_decimals: decimalX,
        token_y_decimals: decimalY,
        active_bin_id: activeBinId,
        lower_bin_id: pd.lowerBinId,
        upper_bin_id: pd.upperBinId,
        total_x_amount: toStr(pd.totalXAmount),
        total_y_amount: toStr(pd.totalYAmount),
        fee_x_unclaimed: toStr(pd.feeX),
        fee_y_unclaimed: toStr(pd.feeY),
        total_claimed_fee_x: toStr(pd.totalClaimedFeeXAmount),
        total_claimed_fee_y: toStr(pd.totalClaimedFeeYAmount),
        last_updated_at: toStr(pd.lastUpdatedAt),
      });
    }
  }

  process.stdout.write(JSON.stringify(output));
}

main().catch((err) => {
  console.error("fetch_positions failed:", (err && err.stack) || err);
  process.exit(1);
});
