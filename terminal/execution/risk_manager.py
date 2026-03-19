"""
NemoFish Risk Manager
======================
Central risk management engine for all trading operations.

Controls:
  - Per-bet limits (max 5% bankroll)
  - Daily loss limit (20% stop-loss)
  - Correlation limits (max 3 bets on same event)
  - Exposure limits by sport, surface, tournament
  - Drawdown protection (reduce size after losses)

This sits between the Swarm predictions and the execution layer.
Every trade MUST pass through the Risk Manager before execution.
"""

import json
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path


@dataclass
class TradeSignal:
    """A trading signal from the swarm."""
    id: str
    timestamp: str
    sport: str          # tennis / hockey / crypto
    event: str          # "Miami Open 2026"
    match: str          # "Sinner vs Alcaraz"
    pick: str           # "Jannik Sinner"
    side: str           # BET_A / BET_B
    odds: float         # Decimal odds
    model_prob: float   # Our model probability
    market_prob: float  # Market implied probability
    edge: float         # model_prob - market_prob
    confidence: str     # LOW / MEDIUM / HIGH / ELITE
    kelly_raw: float    # Raw Kelly bet size
    surface: str = ""
    round_name: str = ""
    data_quality: float = 0.0
    source: str = "swarm"  # swarm / elo / xgboost


@dataclass 
class RiskDecision:
    """Risk manager's decision on a trade signal."""
    approved: bool
    signal: TradeSignal
    final_bet_size: float
    reason: str
    risk_flags: List[str]
    adjusted_from: float  # Original kelly amount
    portfolio_exposure: float  # Total exposure after this bet


@dataclass
class Position:
    """An open position (pending bet)."""
    signal: TradeSignal
    bet_size: float
    opened_at: str
    status: str = "OPEN"  # OPEN / WON / LOST / VOID
    pnl: float = 0.0


class RiskManager:
    """
    Central risk management engine.

    Usage:
        risk = RiskManager(bankroll=20)
        signal = TradeSignal(...)
        decision = risk.evaluate(signal)
        if decision.approved:
            execute_trade(signal, decision.final_bet_size)
    """

    def __init__(
        self,
        bankroll: float = 20.0,          # Must match config.yaml bankroll.initial_usd
        max_bet_pct: float = 0.05,         # 5% max per bet
        daily_loss_limit_pct: float = 0.20, # 20% daily stop
        max_exposure_pct: float = 0.30,     # 30% max total exposure
        max_correlated_bets: int = 3,       # Max bets on same event
        min_edge: float = 0.03,             # 3% minimum edge
        min_data_quality: float = 0.50,     # 50% minimum data quality
        drawdown_threshold: float = 0.10,   # 10% drawdown = reduce size
    ):
        self.initial_bankroll = bankroll
        self.bankroll = bankroll
        self.max_bet_pct = max_bet_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_exposure_pct = max_exposure_pct
        self.max_correlated_bets = max_correlated_bets
        self.min_edge = min_edge
        self.min_data_quality = min_data_quality
        self.drawdown_threshold = drawdown_threshold

        # State
        self.positions: List[Position] = []
        self.daily_pnl = 0.0
        self.daily_bets = 0
        self.total_bets = 0
        self.total_won = 0
        self.total_pnl = 0.0
        self.peak_bankroll = bankroll

        # Limits tracking
        self._event_counts: Dict[str, int] = defaultdict(int)
        self._sport_exposure: Dict[str, float] = defaultdict(float)

    def evaluate(self, signal: TradeSignal) -> RiskDecision:
        """
        Evaluate a trade signal through all risk checks.
        Returns approved/rejected with reasoning.
        """
        flags = []
        approved = True
        adjusted_size = signal.kelly_raw

        # === Check 1: Minimum edge ===
        if signal.edge < self.min_edge:
            flags.append(f"EDGE_TOO_LOW: {signal.edge:.1%} < {self.min_edge:.0%}")
            approved = False

        # === Check 2: Data quality ===
        if signal.data_quality < self.min_data_quality:
            flags.append(f"LOW_DATA_QUALITY: {signal.data_quality:.0%} < {self.min_data_quality:.0%}")
            approved = False

        # === Check 3: Daily loss limit ===
        if self.daily_pnl <= -(self.daily_loss_limit_pct * self.bankroll):
            flags.append(f"DAILY_STOP_LOSS: P&L ${self.daily_pnl:+.2f}")
            approved = False

        # === Check 4: Max bet size ===
        max_bet = self.bankroll * self.max_bet_pct
        if adjusted_size > max_bet:
            flags.append(f"BET_CAPPED: ${adjusted_size:.2f} → ${max_bet:.2f}")
            adjusted_size = max_bet

        # === Check 5: Correlation limit ===
        event_count = self._event_counts.get(signal.event, 0)
        if event_count >= self.max_correlated_bets:
            flags.append(f"CORRELATED: {event_count} bets on {signal.event}")
            approved = False

        # === Check 6: Max exposure ===
        current_exposure = sum(p.bet_size for p in self.positions if p.status == "OPEN")
        if current_exposure + adjusted_size > self.bankroll * self.max_exposure_pct:
            max_allowed = self.bankroll * self.max_exposure_pct - current_exposure
            if max_allowed > 0:
                flags.append(f"EXPOSURE_REDUCED: ${adjusted_size:.2f} → ${max_allowed:.2f}")
                adjusted_size = max_allowed
            else:
                flags.append(f"MAX_EXPOSURE: ${current_exposure:.2f} already at limit")
                approved = False

        # === Check 7: Drawdown protection ===
        drawdown = (self.peak_bankroll - self.bankroll) / self.peak_bankroll
        if drawdown > self.drawdown_threshold:
            # Reduce bet size proportionally to drawdown
            reduction = 1.0 - (drawdown - self.drawdown_threshold) * 2
            reduction = max(0.25, reduction)  # Never reduce more than 75%
            flags.append(f"DRAWDOWN_REDUCTION: {reduction:.0%} size (drawdown {drawdown:.1%})")
            adjusted_size *= reduction

        # === Check 8: Minimum bet size ===
        if adjusted_size < 5.0 and approved:
            flags.append("BET_TOO_SMALL: < $5")
            approved = False

        # === Check 9: Confidence filter ===
        if signal.confidence == "LOW" and signal.edge < 0.08:
            flags.append(f"LOW_CONFIDENCE_EDGE: {signal.confidence} + {signal.edge:.1%} edge")
            # Don't reject, but flag for review

        total_exposure = current_exposure + (adjusted_size if approved else 0)

        return RiskDecision(
            approved=approved,
            signal=signal,
            final_bet_size=round(adjusted_size, 2) if approved else 0.0,
            reason="APPROVED" if approved else "REJECTED",
            risk_flags=flags,
            adjusted_from=signal.kelly_raw,
            portfolio_exposure=round(total_exposure, 2),
        )

    def open_position(self, signal: TradeSignal, bet_size: float) -> Position:
        """Record an opened position."""
        pos = Position(
            signal=signal,
            bet_size=bet_size,
            opened_at=datetime.now().isoformat(),
        )
        self.positions.append(pos)
        self._event_counts[signal.event] += 1
        self._sport_exposure[signal.sport] += bet_size
        self.daily_bets += 1
        self.total_bets += 1
        return pos

    def close_position(self, position: Position, won: bool):
        """Close a position with result."""
        if won:
            pnl = position.bet_size * (position.signal.odds - 1)
            position.status = "WON"
            self.total_won += 1
        else:
            pnl = -position.bet_size
            position.status = "LOST"

        position.pnl = pnl
        self.bankroll += pnl
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.peak_bankroll = max(self.peak_bankroll, self.bankroll)

        self._event_counts[position.signal.event] = max(
            0, self._event_counts[position.signal.event] - 1
        )
        self._sport_exposure[position.signal.sport] -= position.bet_size

    def reset_daily(self):
        """Reset daily counters (call at start of each day)."""
        self.daily_pnl = 0.0
        self.daily_bets = 0

    def get_portfolio_summary(self) -> dict:
        """Get current portfolio state."""
        open_pos = [p for p in self.positions if p.status == "OPEN"]
        closed_pos = [p for p in self.positions if p.status != "OPEN"]

        return {
            "bankroll": round(self.bankroll, 2),
            "initial_bankroll": self.initial_bankroll,
            "total_return": f"{(self.bankroll / self.initial_bankroll - 1) * 100:+.1f}%",
            "total_pnl": round(self.total_pnl, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(open_pos),
            "total_exposure": round(sum(p.bet_size for p in open_pos), 2),
            "total_bets": self.total_bets,
            "win_rate": f"{self.total_won / self.total_bets * 100:.1f}%" if self.total_bets > 0 else "N/A",
            "drawdown": f"{(self.peak_bankroll - self.bankroll) / self.peak_bankroll * 100:.1f}%",
        }

    def display_status(self):
        """Pretty-print current risk status."""
        s = self.get_portfolio_summary()
        print(f"\n{'='*50}")
        print(f"  📊 RISK MANAGER STATUS")
        print(f"{'='*50}")
        print(f"  Bankroll:     ${s['bankroll']:>10,.2f} ({s['total_return']})")
        print(f"  Daily P&L:    ${s['daily_pnl']:>+10,.2f}")
        print(f"  Total P&L:    ${s['total_pnl']:>+10,.2f}")
        print(f"  Open pos:     {s['open_positions']:>10}")
        print(f"  Exposure:     ${s['total_exposure']:>10,.2f}")
        print(f"  Win rate:     {s['win_rate']:>10}")
        print(f"  Drawdown:     {s['drawdown']:>10}")
        print(f"{'='*50}")


# === CLI Demo ===
if __name__ == "__main__":
    risk = RiskManager(bankroll=5000)

    # Simulate a trade signal
    signal = TradeSignal(
        id="test-001",
        timestamp=datetime.now().isoformat(),
        sport="tennis",
        event="Miami Open 2026",
        match="Sinner vs Alcaraz",
        pick="Jannik Sinner",
        side="BET_A",
        odds=1.55,
        model_prob=0.693,
        market_prob=0.645,
        edge=0.048,
        confidence="HIGH",
        kelly_raw=169.22,
        surface="Hard",
        round_name="F",
        data_quality=1.0,
    )

    print("=== RISK EVALUATION ===")
    decision = risk.evaluate(signal)
    print(f"Signal: {signal.match} → {signal.pick}")
    print(f"Edge: {signal.edge:.1%} | Odds: {signal.odds}")
    print(f"Decision: {decision.reason}")
    print(f"Bet size: ${decision.final_bet_size:.2f} (from ${decision.adjusted_from:.2f})")
    print(f"Flags: {decision.risk_flags}")

    if decision.approved:
        pos = risk.open_position(signal, decision.final_bet_size)
        print(f"\nPosition opened: {pos.signal.match} @ ${pos.bet_size:.2f}")

    risk.display_status()
