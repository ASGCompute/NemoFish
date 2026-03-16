"""
Fractional Kelly Criterion Position Sizer
==========================================
f* = (b*p - q) / b

Where:
  f = fraction of bankroll to bet
  b = net odds (decimal_odds - 1)
  p = true probability of winning (from model)
  q = 1 - p

Uses Quarter Kelly (0.25) by default for safety.
Hard caps: min edge 3%, max bet 5% of bankroll.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class BetSizing:
    """Result of Kelly Criterion calculation."""
    edge: float               # Model prob - market prob
    edge_pct: str              # Human-readable edge
    full_kelly_fraction: float # Full Kelly f*
    actual_fraction: float     # After scaling (quarter/half)
    bet_size: float            # Dollar amount to bet
    bankroll: float            # Current bankroll
    expected_value: float      # EV of bet
    recommendation: str        # BET / SKIP / STRONG_BET
    risk_level: str            # LOW / MEDIUM / HIGH / EXTREME


class KellyCriterion:
    """
    Fractional Kelly Criterion with hard safety limits.
    
    Usage:
        kelly = KellyCriterion(bankroll=5000)
        result = kelly.size_bet(
            model_prob=0.55,
            decimal_odds=1.909,  # -110 American
        )
        print(f"Bet ${result.bet_size:.2f} ({result.recommendation})")
    """

    def __init__(
        self,
        bankroll: float = 5000.0,
        kelly_fraction: float = 0.25,   # Quarter Kelly (conservative)
        min_edge: float = 0.03,          # Minimum 3% edge to bet
        max_bet_pct: float = 0.05,       # Max 5% of bankroll per bet
        min_bet: float = 5.0,            # Minimum bet size
        daily_loss_limit_pct: float = 0.20,  # Stop at 20% daily loss
    ):
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.min_edge = min_edge
        self.max_bet_pct = max_bet_pct
        self.min_bet = min_bet
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.daily_pnl = 0.0

    def size_bet(
        self,
        model_prob: float,
        decimal_odds: float,
        override_kelly_frac: Optional[float] = None,
    ) -> BetSizing:
        """
        Calculate optimal bet size using Fractional Kelly.
        
        Args:
            model_prob: Our model's estimated win probability (0-1)
            decimal_odds: Decimal odds offered (e.g., 1.909 for -110)
            override_kelly_frac: Override default kelly fraction
            
        Returns: BetSizing with recommendation
        """
        b = decimal_odds - 1.0  # Net odds
        p = model_prob
        q = 1.0 - p

        # Market implied probability
        market_prob = 1.0 / decimal_odds
        edge = p - market_prob

        # Full Kelly formula
        if b > 0:
            full_kelly = (b * p - q) / b
        else:
            full_kelly = 0.0

        # Scaled Kelly
        frac = override_kelly_frac or self.kelly_fraction
        scaled_kelly = max(0.0, full_kelly * frac)

        # Apply hard caps
        capped = min(scaled_kelly, self.max_bet_pct)
        bet_size = max(0.0, capped * self.bankroll)

        # Check daily loss limit
        if self.daily_pnl <= -(self.daily_loss_limit_pct * self.bankroll):
            bet_size = 0.0
            recommendation = "STOP_LOSS"
        elif edge < self.min_edge:
            bet_size = 0.0
            recommendation = "SKIP"
        elif bet_size < self.min_bet:
            bet_size = 0.0
            recommendation = "SKIP"
        elif edge >= 0.10:
            recommendation = "STRONG_BET"
        elif edge >= 0.05:
            recommendation = "BET"
        else:
            recommendation = "BET"

        # Expected value
        ev = bet_size * (decimal_odds * p - 1) if bet_size > 0 else 0.0

        # Risk level
        if capped >= 0.04:
            risk_level = "HIGH"
        elif capped >= 0.02:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return BetSizing(
            edge=round(edge, 4),
            edge_pct=f"{edge*100:.1f}%",
            full_kelly_fraction=round(full_kelly, 4),
            actual_fraction=round(capped, 4),
            bet_size=round(bet_size, 2),
            bankroll=self.bankroll,
            expected_value=round(ev, 2),
            recommendation=recommendation,
            risk_level=risk_level,
        )

    def record_result(self, bet_size: float, won: bool, decimal_odds: float):
        """Record a bet result and update bankroll + daily P&L."""
        if won:
            profit = bet_size * (decimal_odds - 1)
        else:
            profit = -bet_size

        self.bankroll += profit
        self.daily_pnl += profit
        return profit

    def reset_daily(self):
        """Reset daily P&L counter (call at start of each day)."""
        self.daily_pnl = 0.0

    def summary(self) -> dict:
        return {
            "bankroll": round(self.bankroll, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "kelly_fraction": self.kelly_fraction,
            "min_edge": f"{self.min_edge*100}%",
            "max_bet_pct": f"{self.max_bet_pct*100}%",
            "daily_loss_limit": f"{self.daily_loss_limit_pct*100}%",
        }

    @staticmethod
    def american_to_decimal(american_odds: int) -> float:
        """Convert American odds (-110, +150) to decimal (1.909, 2.50)."""
        if american_odds > 0:
            return 1.0 + (american_odds / 100.0)
        else:
            return 1.0 + (100.0 / abs(american_odds))

    @staticmethod
    def decimal_to_probability(decimal_odds: float) -> float:
        """Convert decimal odds to implied probability."""
        return 1.0 / decimal_odds


# --- CLI Demo ---
if __name__ == "__main__":
    kelly = KellyCriterion(bankroll=5000)

    print("=== Kelly Criterion Position Sizer ===")
    print(f"Bankroll: ${kelly.bankroll:,.2f}")
    print(f"Kelly Fraction: {kelly.kelly_fraction} (Quarter Kelly)")
    print()

    # Example 1: Tennis match
    print("--- Example 1: Sinner vs Medvedev (-110) ---")
    result = kelly.size_bet(model_prob=0.55, decimal_odds=1.909)
    print(f"Edge: {result.edge_pct}")
    print(f"Full Kelly: {result.full_kelly_fraction:.4f}")
    print(f"Quarter Kelly: {result.actual_fraction:.4f}")
    print(f"Bet Size: ${result.bet_size:.2f}")
    print(f"Expected Value: ${result.expected_value:.2f}")
    print(f"Recommendation: {result.recommendation}")
    print()

    # Example 2: Strong edge
    print("--- Example 2: Strong Edge (60% vs +120 odds) ---")
    result2 = kelly.size_bet(model_prob=0.60, decimal_odds=2.20)
    print(f"Edge: {result2.edge_pct}")
    print(f"Bet Size: ${result2.bet_size:.2f}")
    print(f"Expected Value: ${result2.expected_value:.2f}")
    print(f"Recommendation: {result2.recommendation}")
    print()

    # Example 3: No edge
    print("--- Example 3: No Edge (50% vs -110) ---")
    result3 = kelly.size_bet(model_prob=0.50, decimal_odds=1.909)
    print(f"Edge: {result3.edge_pct}")
    print(f"Recommendation: {result3.recommendation}")
