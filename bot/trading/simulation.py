"""
Realistic Paper Trading Simulation

Models:
  - Solana transaction fees (base + priority)
  - DEX swap fees (Raydium/Orca/Jupiter)
  - Price impact from low liquidity (x*y=k AMM model)
  - Market drift during execution delay
  - Transaction failure rate

Typical meme coin scenario:
  Pool liquidity: $5K–$200K
  Position size:  $50–$200
  → Price impact: 0.05%–8%
  → Swap fee:     0.25%
  → Total cost:   0.3%–8.3% per side
"""
import asyncio
import random
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Fees ──────────────────────────────────────────────────────────────────────
# Raydium CLMM / Orca Whirlpool standard fee tier
SWAP_FEE_PCT = 0.25          # 0.25% per swap (both buy and sell)

# Solana network fees in EUR (at ~$150/SOL)
# Base fee: 5000 lamports = 0.000005 SOL ≈ €0.0007
# Priority fee (fast inclusion): ~0.0001 SOL ≈ €0.014
NETWORK_FEE_EUR = 0.015      # base + typical priority fee

# ── Execution Delay ───────────────────────────────────────────────────────────
# Solana block time: 400ms, confirmation: 1–4 blocks typical
# Add routing overhead from Jupiter
DELAY_MIN_SEC = 1.0
DELAY_MAX_SEC = 4.5

# Probability a tx gets dropped (network congestion, stale blockhash, etc.)
TX_FAILURE_RATE = 0.03       # 3% — realistic for busy periods

# ── Price Impact (AMM model) ──────────────────────────────────────────────────
# Simplified constant-product AMM: price_impact = trade_size / (liquidity/2)
# Conservative fallback when liquidity data is unavailable
DEFAULT_LIQUIDITY_EUR = 15_000   # $15K — small meme coin pool

# Cap slippage at realistic max (AMM formula breaks at extreme sizes)
MAX_PRICE_IMPACT_PCT = 25.0

# Market drift 1-sigma during execution delay (meme coins move FAST)
DRIFT_SIGMA_PCT = 0.8        # ±0.8% per second of delay, damped


@dataclass
class ExecutionResult:
    success: bool
    executed_price_eur: float   # Fill price after slippage + drift
    fee_eur: float              # Total fees (swap + network)
    price_impact_pct: float     # Price impact from position size
    slippage_pct: float         # Total slippage (impact + drift, signed)
    delay_sec: float
    failure_reason: str = ""


def _calc_price_impact(trade_eur: float, liquidity_eur: float) -> float:
    """
    Simplified constant-product AMM price impact.
    Formula: impact = trade_size / (liquidity / 2) * 100
    Capped at MAX_PRICE_IMPACT_PCT.
    """
    if liquidity_eur <= 0:
        return MAX_PRICE_IMPACT_PCT
    impact = (trade_eur / (liquidity_eur / 2)) * 100
    return min(impact, MAX_PRICE_IMPACT_PCT)


async def simulate_buy(
    quote_price_eur: float,
    investment_eur: float,
    pool_liquidity_eur: Optional[float] = None,
) -> ExecutionResult:
    """
    Simulate a DEX BUY order on Solana.

    Costs vs quoted price:
      + Price impact (push market up)
      + Random market drift during tx delay (usually against us)
      + Swap fee (0.25%)
      + Network fee (fixed EUR)
    """
    delay = random.uniform(DELAY_MIN_SEC, DELAY_MAX_SEC)
    await asyncio.sleep(delay)

    # Transaction failure
    if random.random() < TX_FAILURE_RATE:
        logger.warning("[Simulation] BUY tx failed (congestion/stale blockhash)")
        return ExecutionResult(
            success=False,
            executed_price_eur=quote_price_eur,
            fee_eur=NETWORK_FEE_EUR,      # still pay base fee for failed tx
            price_impact_pct=0.0,
            slippage_pct=0.0,
            delay_sec=delay,
            failure_reason="Transaction dropped (Solana congestion)",
        )

    liquidity = pool_liquidity_eur or DEFAULT_LIQUIDITY_EUR
    impact_pct = _calc_price_impact(investment_eur, liquidity)

    # Market drift: typically adverse (price runs away from us)
    # Skewed slightly positive (FOMO buyers) but could go either way
    drift_pct = random.gauss(0.3, DRIFT_SIGMA_PCT * (delay / 2))

    total_slippage_pct = impact_pct + drift_pct
    executed_price = quote_price_eur * (1 + total_slippage_pct / 100)

    swap_fee_eur = investment_eur * (SWAP_FEE_PCT / 100)
    total_fee_eur = swap_fee_eur + NETWORK_FEE_EUR

    logger.info(
        f"[Simulation] BUY executed in {delay:.1f}s | "
        f"impact={impact_pct:.2f}% drift={drift_pct:+.2f}% → "
        f"slippage={total_slippage_pct:+.2f}% | "
        f"fee={total_fee_eur:.4f}€ | "
        f"{quote_price_eur:.8f} → {executed_price:.8f} EUR"
    )

    return ExecutionResult(
        success=True,
        executed_price_eur=executed_price,
        fee_eur=total_fee_eur,
        price_impact_pct=impact_pct,
        slippage_pct=total_slippage_pct,
        delay_sec=delay,
    )


async def simulate_sell(
    quote_price_eur: float,
    position_value_eur: float,
    pool_liquidity_eur: Optional[float] = None,
) -> ExecutionResult:
    """
    Simulate a DEX SELL order on Solana.

    Costs vs quoted price:
      - Price impact (push market down)
      - Random market drift (can go either way)
      - Swap fee (0.25%)
      - Network fee (fixed EUR)
    """
    delay = random.uniform(DELAY_MIN_SEC, DELAY_MAX_SEC)
    await asyncio.sleep(delay)

    if random.random() < TX_FAILURE_RATE:
        logger.warning("[Simulation] SELL tx failed")
        return ExecutionResult(
            success=False,
            executed_price_eur=quote_price_eur,
            fee_eur=NETWORK_FEE_EUR,
            price_impact_pct=0.0,
            slippage_pct=0.0,
            delay_sec=delay,
            failure_reason="Transaction dropped",
        )

    liquidity = pool_liquidity_eur or DEFAULT_LIQUIDITY_EUR
    impact_pct = _calc_price_impact(position_value_eur, liquidity)

    # Sell-side drift: slightly negative on average (panic selling / front-running)
    drift_pct = random.gauss(-0.2, DRIFT_SIGMA_PCT * (delay / 2))

    # Total slippage for a sell: both impact and drift work against us
    total_slippage_pct = -(impact_pct + abs(drift_pct))
    executed_price = quote_price_eur * (1 + total_slippage_pct / 100)

    swap_fee_eur = position_value_eur * (SWAP_FEE_PCT / 100)
    total_fee_eur = swap_fee_eur + NETWORK_FEE_EUR

    logger.info(
        f"[Simulation] SELL executed in {delay:.1f}s | "
        f"impact={impact_pct:.2f}% drift={drift_pct:+.2f}% → "
        f"slippage={total_slippage_pct:+.2f}% | "
        f"fee={total_fee_eur:.4f}€ | "
        f"{quote_price_eur:.8f} → {executed_price:.8f} EUR"
    )

    return ExecutionResult(
        success=True,
        executed_price_eur=executed_price,
        fee_eur=total_fee_eur,
        price_impact_pct=impact_pct,
        slippage_pct=total_slippage_pct,
        delay_sec=delay,
    )
