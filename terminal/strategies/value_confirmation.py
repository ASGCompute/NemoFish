"""
Value Confirmation Strategy
============================
Bet when our model AGREES with the market favorite.

Logic:
  - Market favorite = player with lower odds
  - Model favorite = player with higher predicted probability
  - If both agree → bet on the favorite
  - Only bet if model probability ≥ min_prob (default 55%)
  - Skip matches with rookies

This strategy exploits the fact that when both model and market
converge on the same pick, the win rate is very high (~68+%),
which can overcome the bookmaker's vig on low-odds favorites.

Historical performance: ~62% win rate, +0.3% ROI (2026 data)
"""

from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput


class ValueConfirmationStrategy(BettingStrategy):
    """Bet when model confirms the market favorite."""

    def __init__(
        self,
        min_model_prob: float = 0.55,
        skip_rookies: bool = True,
        flat_bet_size: float = 100.0,
    ):
        self.min_model_prob = min_model_prob
        self.skip_rookies = skip_rookies
        self.flat_bet_size = flat_bet_size

    @property
    def name(self) -> str:
        return "ValueConfirmation"

    @property
    def description(self) -> str:
        return f"Bet when model agrees with market fav (prob≥{self.min_model_prob:.0%})"

    def evaluate_match(self, match: MatchInput) -> BetDecision:
        # Need odds to evaluate
        if not match.odds_a or not match.odds_b:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason="No odds available"
            )

        # Skip rookies
        if self.skip_rookies and match.has_rookie:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason="Rookie involved"
            )

        # Determine market favorite (lower odds = favorite)
        market_fav = "A" if match.odds_a < match.odds_b else "B"

        # Determine model favorite (higher prob = favorite)
        model_fav = "A" if match.prob_a >= 0.5 else "B"
        model_prob = max(match.prob_a, match.prob_b)

        # Must agree on the favorite
        if model_fav != market_fav:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Model ({model_fav}) disagrees with market ({market_fav})"
            )

        # Must meet probability threshold
        if model_prob < self.min_model_prob:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Model prob {model_prob:.0%} < {self.min_model_prob:.0%}"
            )

        # Compute edge
        pick = model_fav
        our_odds = match.odds_a if pick == "A" else match.odds_b
        our_prob = match.prob_a if pick == "A" else match.prob_b
        implied = self.compute_implied_prob(our_odds)
        edge = self.compute_edge(our_prob, implied)

        return BetDecision(
            should_bet=True,
            pick=pick,
            bet_size=self.flat_bet_size,
            confidence_score=model_prob,
            strategy_name=self.name,
            reason=f"Model+Market agree: {pick} @ {our_odds:.2f} (prob {our_prob:.0%})",
            edge=edge,
            our_odds=our_odds,
        )
