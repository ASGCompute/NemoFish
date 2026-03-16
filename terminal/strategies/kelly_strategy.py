"""
Kelly Criterion Strategy
=========================
Variable bet sizing based on the Kelly Criterion.

Kelly formula: f* = (bp - q) / b
Where:
  b = decimal odds - 1 (net odds)
  p = model probability of winning
  q = 1 - p (probability of losing)

This gives the optimal fraction of bankroll to bet to maximize
long-term geometric growth rate.

In practice, "full Kelly" is too aggressive. We use fractional Kelly:
  - Quarter Kelly (0.25x): Very conservative, low variance
  - Half Kelly (0.50x): Standard, good risk/reward
  - Full Kelly (1.0x): Aggressive, maximum growth but high drawdowns

Parameters:
  - kelly_fraction: Multiplier for the raw Kelly amount (default 0.25)
  - min_edge: Minimum edge before considering a bet
  - max_bet_pct: Maximum fraction of bankroll per bet
  - bankroll: Current bankroll for bet sizing
"""

from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput


class KellyStrategy(BettingStrategy):
    """Kelly Criterion variable bet sizing."""

    def __init__(
        self,
        kelly_fraction: float = 0.25,  # Quarter Kelly (conservative)
        min_edge: float = 0.03,        # 3% minimum edge
        max_bet_pct: float = 0.05,     # Max 5% of bankroll per bet
        bankroll: float = 5000.0,      # Current bankroll
        skip_rookies: bool = True,
    ):
        self.kelly_fraction = kelly_fraction
        self.min_edge = min_edge
        self.max_bet_pct = max_bet_pct
        self.bankroll = bankroll
        self.skip_rookies = skip_rookies

    @property
    def name(self) -> str:
        frac_label = {0.25: "¼", 0.5: "½", 1.0: "Full"}.get(
            self.kelly_fraction, f"{self.kelly_fraction:.0%}"
        )
        return f"Kelly({frac_label})"

    @property
    def description(self) -> str:
        return f"Kelly Criterion ({self.kelly_fraction:.0%} fraction, min edge {self.min_edge:.0%})"

    def kelly_bet_size(self, prob: float, odds: float) -> float:
        """
        Compute Kelly bet size.

        f* = (b*p - q) / b
        where b = odds - 1, p = prob, q = 1 - prob
        """
        b = odds - 1
        if b <= 0:
            return 0.0
        p = prob
        q = 1 - p
        f_star = (b * p - q) / b
        if f_star <= 0:
            return 0.0
        # Apply fractional Kelly
        f_adjusted = f_star * self.kelly_fraction
        # Cap at max bet percentage
        f_capped = min(f_adjusted, self.max_bet_pct)
        return f_capped * self.bankroll

    def evaluate_match(self, match: MatchInput) -> BetDecision:
        if not match.odds_a or not match.odds_b:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason="No odds available"
            )

        if self.skip_rookies and match.has_rookie:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason="Rookie involved"
            )

        # Pick the model's favorite
        model_fav = "A" if match.prob_a >= 0.5 else "B"
        our_prob = match.prob_a if model_fav == "A" else match.prob_b
        our_odds = match.odds_a if model_fav == "A" else match.odds_b
        implied = self.compute_implied_prob(our_odds)
        edge = self.compute_edge(our_prob, implied)

        # Check minimum edge
        if edge < self.min_edge:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Edge {edge:.1%} < min {self.min_edge:.0%}"
            )

        # Compute Kelly bet size
        bet_amount = self.kelly_bet_size(our_prob, our_odds)

        if bet_amount < 5.0:  # Minimum bet
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Kelly bet ${bet_amount:.2f} too small"
            )

        return BetDecision(
            should_bet=True,
            pick=model_fav,
            bet_size=round(bet_amount, 2),
            confidence_score=edge,
            strategy_name=self.name,
            reason=f"Kelly: ${bet_amount:.2f} on {model_fav} @ {our_odds:.2f} (edge {edge:.1%})",
            edge=edge,
            our_odds=our_odds,
        )

    def update_bankroll(self, new_bankroll: float):
        """Update bankroll after a bet result."""
        self.bankroll = new_bankroll
