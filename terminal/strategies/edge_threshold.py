"""
Edge Threshold Strategy
========================
Pure value betting: bet whenever the model's edge over the market
exceeds a configurable threshold.

Edge = model_probability - implied_probability_from_odds

This is the simplest strategy and serves as a baseline.
Most traditional sports betting models use this approach.

Configurable parameters:
  - min_edge: Minimum edge to bet (default 3%)
  - max_edge: Maximum edge (filter out extreme disagreements)
  - skip_rookies: Whether to skip rookie matches
"""

from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput


class EdgeThresholdStrategy(BettingStrategy):
    """Bet when model edge exceeds threshold."""

    def __init__(
        self,
        min_edge: float = 0.03,       # 3% minimum edge
        max_edge: float = 0.30,       # 30% max edge (outlier filter)
        skip_rookies: bool = True,
        flat_bet_size: float = 100.0,
    ):
        self.min_edge = min_edge
        self.max_edge = max_edge
        self.skip_rookies = skip_rookies
        self.flat_bet_size = flat_bet_size

    @property
    def name(self) -> str:
        return f"Edge({self.min_edge:.0%}-{self.max_edge:.0%})"

    @property
    def description(self) -> str:
        return f"Bet when edge is {self.min_edge:.0%}–{self.max_edge:.0%}"

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

        # Compute edge for our predicted winner
        model_fav = "A" if match.prob_a >= 0.5 else "B"
        our_prob = match.prob_a if model_fav == "A" else match.prob_b
        our_odds = match.odds_a if model_fav == "A" else match.odds_b
        implied = self.compute_implied_prob(our_odds)
        edge = self.compute_edge(our_prob, implied)

        # Check edge bounds
        if edge < self.min_edge:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Edge {edge:.1%} < min {self.min_edge:.0%}"
            )

        if edge > self.max_edge:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Edge {edge:.1%} > max {self.max_edge:.0%} (outlier)"
            )

        return BetDecision(
            should_bet=True,
            pick=model_fav,
            bet_size=self.flat_bet_size,
            confidence_score=edge,  # Use edge as confidence proxy
            strategy_name=self.name,
            reason=f"Edge {edge:.1%} on {model_fav} @ {our_odds:.2f}",
            edge=edge,
            our_odds=our_odds,
        )
