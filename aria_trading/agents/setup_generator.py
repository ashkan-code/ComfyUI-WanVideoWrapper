"""
ARIA — Setup Generator & Qualifier Agent
Takes inputs from Market Analyst + Whale Tracker + Gem Hunter
and generates precise, high-probability trade setups.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict

from config import CONFIG

logger = logging.getLogger(__name__)


@dataclass
class TradeSetup:
    setup_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    symbol: str = ""
    direction: str = ""               # "long" | "short"
    confluence_score: int = 0
    setup_type: str = ""              # "OB_retest" | "FVG_fill" | "Liquidity_grab" | "Wyckoff_C"

    entry_zone_low: float = 0.0
    entry_zone_high: float = 0.0
    entry_trigger_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0

    rr_ratio: float = 0.0
    distance_to_sl_pct: float = 0.0
    risk_amount_usdt: float = 0.0

    invalidation_price: float = 0.0
    htf_bias: str = ""
    whale_signal: str = ""
    funding_rate: float = 0.0
    confluence_breakdown: dict = field(default_factory=dict)
    status: str = "pending"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SetupGeneratorAgent:
    """
    Evaluates gem candidates against market structure and whale data
    to generate qualified trade setups with full confluence scoring.
    """

    def __init__(self, signal_queue: asyncio.Queue, market_analyst=None, whale_tracker=None):
        self.signal_queue = signal_queue
        self.market_analyst = market_analyst
        self.whale_tracker = whale_tracker
        self._pending_setups: list[TradeSetup] = []

    # ──────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────

    async def run(self, gem_queue: asyncio.Queue) -> None:
        """Process gem candidates as they arrive."""
        logger.info("SetupGeneratorAgent started")
        while True:
            try:
                event = await asyncio.wait_for(gem_queue.get(), timeout=5.0)
                if event.get("type") == "gem_candidate":
                    setup = await self.evaluate(event["data"])
                    if setup:
                        await self.signal_queue.put({"type": "trade_setup", "data": setup.to_dict()})
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                logger.error("SetupGenerator error: %s", exc)

    # ──────────────────────────────────────────────────────────
    # Evaluation
    # ──────────────────────────────────────────────────────────

    async def evaluate(self, gem: dict) -> TradeSetup | None:
        """
        Evaluate a gem candidate and produce a TradeSetup if qualified.

        Args:
            gem: Gem report from GemHunterAgent

        Returns:
            TradeSetup if confluence ≥ 75, else None
        """
        symbol = gem["symbol"]
        direction = gem["direction"]

        market = self.market_analyst.get_cached(symbol) if self.market_analyst else {}
        whale = self.whale_tracker.get_cached(symbol) if self.whale_tracker else {}

        funding = (whale or {}).get("funding_rate", {}).get("current", 0.0)

        # Pre-checks
        rejection = self._pre_check(direction, funding, market)
        if rejection:
            logger.info("Setup REJECTED %s: %s", symbol, rejection)
            return None

        breakdown, total = self._score_confluence(gem, market, whale)
        if total < CONFIG["min_confluence_score"]:
            logger.debug("Setup below threshold %s: %d/100", symbol, total)
            return None

        entry = gem["suggested_entry"]
        sl = gem["suggested_sl"]
        tp1 = gem["suggested_tp1"]
        tp2 = gem["suggested_tp2"]
        tp3 = tp2 + (tp2 - tp1)  # extend by same delta

        sl_dist_pct = abs(entry - sl) / entry
        rr = abs(tp1 - entry) / abs(entry - sl) if entry != sl else 0

        if sl_dist_pct > 0.05 or rr < CONFIG["min_rr_ratio"]:
            logger.info("Setup REJECTED %s: SL=%.2f%% RR=%.2f", symbol, sl_dist_pct * 100, rr)
            return None

        setup = TradeSetup(
            symbol=symbol,
            direction=direction,
            confluence_score=total,
            setup_type=self._setup_type(gem),
            entry_zone_low=gem["technical"]["entry_zone"]["low"],
            entry_zone_high=gem["technical"]["entry_zone"]["high"],
            entry_trigger_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            rr_ratio=round(rr, 2),
            distance_to_sl_pct=round(sl_dist_pct * 100, 3),
            invalidation_price=sl,
            htf_bias=(market or {}).get("overall_bias", "neutral"),
            whale_signal=(whale or {}).get("whale_signal", "NEUTRAL"),
            funding_rate=funding,
            confluence_breakdown=breakdown,
            notes=gem.get("summary", ""),
        )

        logger.info("✅ SETUP QUALIFIED %s score=%d RR=%.1f", symbol, total, rr)
        return setup

    # ──────────────────────────────────────────────────────────
    # Confluence scoring
    # ──────────────────────────────────────────────────────────

    def _score_confluence(self, gem: dict, market: dict, whale: dict) -> tuple[dict, int]:
        """
        Score all confluence factors.

        Returns:
            (breakdown dict, total score)
        """
        breakdown: dict[str, int] = {}
        direction = gem["direction"]
        market = market or {}
        whale = whale or {}

        # ── Technical (50 pts) ───────────────────────
        htf_bias = market.get("overall_bias", "neutral")
        if htf_bias == direction:
            breakdown["htf_structure"] = 15
        elif htf_bias == "neutral":
            breakdown["htf_structure"] = 5
        else:
            breakdown["htf_structure"] = 0

        if gem.get("wyckoff", {}).get("event") in ("Spring", "UTAD"):
            breakdown["valid_ob_in_zone"] = 12
        else:
            breakdown["valid_ob_in_zone"] = 6

        # FVG if gem score high
        breakdown["fvg_present"] = 10 if gem["gem_score"] >= 80 else 0

        # Liquidity sweep from wyckoff Spring/UTAD
        if gem.get("wyckoff", {}).get("event") in ("Spring", "UTAD"):
            breakdown["liquidity_sweep"] = 8

        kz = market.get("killzone_active", "none")
        breakdown["killzone"] = 5 if kz != "none" else 0

        # ── On-Chain (30 pts) ────────────────────────
        whale_sig = whale.get("whale_signal", "NEUTRAL")
        whale_pts = {
            "BULLISH_STRONG": 15 if direction == "long" else 0,
            "BEARISH_STRONG": 15 if direction == "short" else 0,
            "BULLISH_MODERATE": 8 if direction == "long" else 0,
            "BEARISH_MODERATE": 8 if direction == "short" else 0,
        }.get(whale_sig, 0)
        breakdown["whale_signal"] = whale_pts

        funding = whale.get("funding_rate", {}).get("current", 0)
        if direction == "long" and funding < 0:
            breakdown["funding_rate"] = 8
        elif direction == "short" and funding > 0.001:
            breakdown["funding_rate"] = 8
        else:
            breakdown["funding_rate"] = 3

        oi_signal = whale.get("open_interest", {}).get("signal", "neutral")
        breakdown["oi_signal"] = 7 if oi_signal not in ("neutral", "unknown") else 2

        # ── Momentum (20 pts) ────────────────────────
        breakdown["cvd"] = 10 if gem.get("gem_score", 0) >= 75 else 4
        breakdown["volume"] = 6 if gem.get("wyckoff", {}).get("confidence", 0) >= 70 else 2
        breakdown["narrative"] = gem.get("narrative", {}).get("momentum_score", 3)

        total = sum(breakdown.values())
        return breakdown, min(100, total)

    # ──────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────

    def _pre_check(self, direction: str, funding: float, market: dict) -> str | None:
        """Return rejection reason string or None if OK."""
        if direction == "long" and funding > CONFIG["funding_rate_long_max"]:
            return f"Funding too high for long: {funding:.4f}"
        if direction == "short" and funding < CONFIG["funding_rate_short_max"]:
            return f"Funding too low for short: {funding:.4f}"
        return None

    def _setup_type(self, gem: dict) -> str:
        event = gem.get("wyckoff", {}).get("event", "")
        if event == "Spring":
            return "Wyckoff_Spring"
        if event == "UTAD":
            return "Wyckoff_UTAD"
        if gem["technical"].get("key_level_type") == "OB":
            return "OB_retest"
        if gem["technical"].get("key_level_type") == "FVG":
            return "FVG_fill"
        return "Liquidity_grab"
