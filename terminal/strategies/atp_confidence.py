"""
ATP Confidence Strategy
========================
Implements the ATPBetting repository's core approach.

Key insight from https://github.com/edouardthom/ATPBetting:
  confidence = model_probability / bookmaker_implied_probability

When confidence > 1.0, our model sees more value than the bookmaker.
The higher the confidence, the more the bookmaker underestimates our pick.

The strategy:
  1. Compute confidence for EVERY match (both sides)
  2. For each match, pick the side with highest confidence
  3. Only bet on the top N% most confident picks

This requires a TWO-PASS approach:
  - Pass 1: Compute confidence for all matches (evaluate_match returns should_bet=True for all valid matches)
  - Pass 2: Sort by confidence_score, keep only top N% → filter_top_n()

Historical performance (ATPBetting paper): ~40-70% ROI on top 5-10%
"""

from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput
from typing import List


class ATPConfidenceStrategy(BettingStrategy):
    """Bet on top N% most confident picks (model_prob / implied_prob)."""

    def __init__(
        self,
        top_pct: float = 0.10,       # Bet on top 10% most confident
        min_confidence: float = 1.0,  # Minimum confidence ratio
        skip_rookies: bool = True,
        flat_bet_size: float = 100.0,
    ):
        self.top_pct = top_pct
        self.min_confidence = min_confidence
        self.skip_rookies = skip_rookies
        self.flat_bet_size = flat_bet_size

    @property
    def name(self) -> str:
        return f"ATPConfidence(top{self.top_pct:.0%})"

    @property
    def description(self) -> str:
        return f"Bet top {self.top_pct:.0%} by confidence ratio (model/implied)"

    def evaluate_match(self, match: MatchInput) -> BetDecision:
        """
        Phase 1: Compute confidence for this match.
        Returns should_bet=True with confidence_score for ALL valid matches.
        The actual bet filtering happens in filter_top_n().
        """
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

        # Compute confidence ratio for both sides
        implied_a = self.compute_implied_prob(match.odds_a)
        implied_b = self.compute_implied_prob(match.odds_b)

        conf_a = match.prob_a / implied_a if implied_a > 0 else 0
        conf_b = match.prob_b / implied_b if implied_b > 0 else 0

        # Pick the side with higher confidence
        if conf_a >= conf_b:
            pick = "A"
            confidence = conf_a
            our_prob = match.prob_a
            our_odds = match.odds_a
            implied = implied_a
        else:
            pick = "B"
            confidence = conf_b
            our_prob = match.prob_b
            our_odds = match.odds_b
            implied = implied_b

        edge = self.compute_edge(our_prob, implied)

        # In Phase 1, we mark all valid matches as should_bet=True
        # Phase 2 (filter_top_n) will select only the top N%
        return BetDecision(
            should_bet=True,
            pick=pick,
            bet_size=self.flat_bet_size,
            confidence_score=confidence,
            strategy_name=self.name,
            reason=f"Confidence: {confidence:.3f} (prob={our_prob:.0%}, impl={implied:.0%})",
            edge=edge,
            our_odds=our_odds,
        )

    @staticmethod
    def filter_top_n(
        decisions: List[BetDecision], top_pct: float = 0.10
    ) -> List[BetDecision]:
        """
        Phase 2: Sort all decisions by confidence_score, keep only top N%.
        Non-betting decisions are passed through unchanged.

        Args:
            decisions: List of BetDecisions from evaluate_match()
            top_pct: Fraction of betting decisions to keep (0.10 = top 10%)

        Returns:
            Updated list where only top N% have should_bet=True
        """
        # Separate betting vs non-betting decisions
        betting = [(i, d) for i, d in enumerate(decisions) if d.should_bet]
        non_betting = [(i, d) for i, d in enumerate(decisions) if not d.should_bet]

        if not betting:
            return decisions

        # Sort by confidence descending
        betting.sort(key=lambda x: x[1].confidence_score, reverse=True)

        # Keep only top N%
        n_keep = max(1, int(len(betting) * top_pct))

        # Create result list
        result = list(decisions)  # Copy

        # Mark all as should_bet=False first
        for idx, dec in betting:
            result[idx] = BetDecision(
                should_bet=False,
                pick=dec.pick,
                bet_size=0.0,
                confidence_score=dec.confidence_score,
                strategy_name=dec.strategy_name,
                reason=f"Below top {top_pct:.0%} cutoff (rank={betting.index((idx, dec))+1}/{len(betting)})",
                edge=dec.edge,
                our_odds=dec.our_odds,
            )

        # Then mark top N% as should_bet=True
        for rank, (idx, dec) in enumerate(betting[:n_keep]):
            result[idx] = BetDecision(
                should_bet=True,
                pick=dec.pick,
                bet_size=dec.bet_size,
                confidence_score=dec.confidence_score,
                strategy_name=dec.strategy_name,
                reason=f"Top {top_pct:.0%}: rank {rank+1}/{len(betting)} (conf={dec.confidence_score:.3f})",
                edge=dec.edge,
                our_odds=dec.our_odds,
            )

        return result
