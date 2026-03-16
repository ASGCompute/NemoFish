"""
Skemp Value Betting Strategies
================================
Strategies from skemp15/Tennis-Betting-Model repository.
https://github.com/skemp15/Tennis-Betting-Model

Three strategies extracted from the P&L analysis notebook:

1. ValueOnly: Bet when model sees value (model_prob > implied_prob),
   regardless of who the model predicts to win.

2. PredictedWinValue: Bet on model's predicted winner, but ONLY
   when the model also sees value (model_prob > implied_odds_prob).
   This was the BEST strategy in the paper: 4.78% ROI out-of-sample.

3. InverseInefficiency: Bet AGAINST the model's predicted winner
   when the odds suggest the market is overvaluing them.
   This exploits cases where the bookmaker also gets it wrong.

Key differences from ATPBetting approach:
  - ATPBetting uses confidence = model_prob / implied_prob (ratio)
  - Skemp uses value = model_prob > implied_prob (boolean)
  - ATPBetting selects top N%, Skemp bets ALL value matches
  - Skemp achieves 4.78% ROI vs ATPBetting's 40-70% ROI
  - Skemp has MORE bets (higher volume, lower variance)
"""

from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput


class SkempValueOnlyStrategy(BettingStrategy):
    """
    Bet whenever the model sees value, regardless of win prediction.

    Value = model_probability > bookmaker_implied_probability

    This means we bet on whichever side has value, even if the model
    thinks the other player is more likely to win overall.
    """

    def __init__(
        self,
        min_value_edge: float = 0.0,    # Minimum value edge (model_prob - implied_prob)
        skip_rookies: bool = True,
        flat_bet_size: float = 100.0,
    ):
        self.min_value_edge = min_value_edge
        self.skip_rookies = skip_rookies
        self.flat_bet_size = flat_bet_size

    @property
    def name(self) -> str:
        return "SkempValue"

    @property
    def description(self) -> str:
        return "Bet any side where model prob > implied prob (skemp15)"

    def evaluate_match(self, match: MatchInput) -> BetDecision:
        if not match.odds_a or not match.odds_b:
            return BetDecision(should_bet=False, strategy_name=self.name, reason="No odds")

        if self.skip_rookies and match.has_rookie:
            return BetDecision(should_bet=False, strategy_name=self.name, reason="Rookie")

        implied_a = self.compute_implied_prob(match.odds_a)
        implied_b = self.compute_implied_prob(match.odds_b)

        value_a = match.prob_a - implied_a
        value_b = match.prob_b - implied_b

        # Pick the side with the most value
        if value_a > value_b and value_a > self.min_value_edge:
            return BetDecision(
                should_bet=True, pick="A", bet_size=self.flat_bet_size,
                confidence_score=value_a, strategy_name=self.name,
                reason=f"Value on A: {value_a:.1%} (prob={match.prob_a:.0%}, impl={implied_a:.0%})",
                edge=value_a, our_odds=match.odds_a,
            )
        elif value_b > self.min_value_edge:
            return BetDecision(
                should_bet=True, pick="B", bet_size=self.flat_bet_size,
                confidence_score=value_b, strategy_name=self.name,
                reason=f"Value on B: {value_b:.1%} (prob={match.prob_b:.0%}, impl={implied_b:.0%})",
                edge=value_b, our_odds=match.odds_b,
            )

        return BetDecision(
            should_bet=False, strategy_name=self.name,
            reason=f"No value: A={value_a:.1%}, B={value_b:.1%}"
        )


class SkempPredictedWinValueStrategy(BettingStrategy):
    """
    Bet on the model's PREDICTED WINNER, but only when there is VALUE.

    Two conditions must be met:
      1. Model predicts this player to win (prob > 0.5)
      2. Model probability > bookmaker implied probability (value exists)

    This was the BEST strategy in the skemp15 paper:
      → 4.78% ROI on out-of-sample 2023-2025 data

    The key insight is that combining prediction + value filters out
    matches where the model is confident but the market already prices
    this in (no edge), and also filters out value on the wrong side.
    """

    def __init__(
        self,
        min_model_prob: float = 0.50,  # Must predict win (prob > 50%)
        min_value_edge: float = 0.0,   # Minimum value edge
        skip_rookies: bool = True,
        flat_bet_size: float = 100.0,
    ):
        self.min_model_prob = min_model_prob
        self.min_value_edge = min_value_edge
        self.skip_rookies = skip_rookies
        self.flat_bet_size = flat_bet_size

    @property
    def name(self) -> str:
        return "SkempPredictWin+Value"

    @property
    def description(self) -> str:
        return "Bet predicted winner when model sees value (skemp15 best: 4.78% ROI)"

    def evaluate_match(self, match: MatchInput) -> BetDecision:
        if not match.odds_a or not match.odds_b:
            return BetDecision(should_bet=False, strategy_name=self.name, reason="No odds")

        if self.skip_rookies and match.has_rookie:
            return BetDecision(should_bet=False, strategy_name=self.name, reason="Rookie")

        # Model's predicted winner
        model_fav = "A" if match.prob_a >= 0.5 else "B"
        our_prob = match.prob_a if model_fav == "A" else match.prob_b
        our_odds = match.odds_a if model_fav == "A" else match.odds_b
        implied = self.compute_implied_prob(our_odds)
        edge = self.compute_edge(our_prob, implied)

        # Condition 1: Model must predict winner
        if our_prob < self.min_model_prob:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Model prob {our_prob:.0%} < {self.min_model_prob:.0%}"
            )

        # Condition 2: Must have value (model prob > implied)
        if edge <= self.min_value_edge:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"No value: edge {edge:.1%} ≤ {self.min_value_edge:.0%}"
            )

        return BetDecision(
            should_bet=True, pick=model_fav, bet_size=self.flat_bet_size,
            confidence_score=edge, strategy_name=self.name,
            reason=f"Win+Value: {model_fav} @ {our_odds:.2f} (prob={our_prob:.0%}, edge={edge:.1%})",
            edge=edge, our_odds=our_odds,
        )


class SkempInverseStrategy(BettingStrategy):
    """
    Bet AGAINST the model's predicted winner when odds suggest inefficiency.

    Logic:
      - Model predicts player A wins
      - But bookmaker odds on B are very generous (high odds = high payout)
      - If implied probability on B is much lower than what model gives B
      - Then bet on B → exploit bookmaker overvaluing A

    This is a "contrarian" strategy that bets on underdogs where the
    bookmaker has over-corrected in favor of the favorite.

    From skemp15 paper: This strategy is high-risk/high-reward.
    """

    def __init__(
        self,
        min_inverse_value: float = 0.05,  # Min value edge on the "wrong" side
        max_model_prob: float = 0.60,     # Don't bet against very strong predictions
        skip_rookies: bool = True,
        flat_bet_size: float = 100.0,
    ):
        self.min_inverse_value = min_inverse_value
        self.max_model_prob = max_model_prob
        self.skip_rookies = skip_rookies
        self.flat_bet_size = flat_bet_size

    @property
    def name(self) -> str:
        return "SkempInverse"

    @property
    def description(self) -> str:
        return "Bet against prediction when odds show inefficiency (skemp15)"

    def evaluate_match(self, match: MatchInput) -> BetDecision:
        if not match.odds_a or not match.odds_b:
            return BetDecision(should_bet=False, strategy_name=self.name, reason="No odds")

        if self.skip_rookies and match.has_rookie:
            return BetDecision(should_bet=False, strategy_name=self.name, reason="Rookie")

        # Model's predicted winner
        model_fav = "A" if match.prob_a >= 0.5 else "B"
        model_prob = max(match.prob_a, match.prob_b)

        # Don't bet against very confident predictions
        if model_prob > self.max_model_prob:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Model too confident ({model_prob:.0%}), skip inverse"
            )

        # The "underdog" (model says they lose)
        underdog = "B" if model_fav == "A" else "A"
        underdog_prob = match.prob_b if underdog == "B" else match.prob_a
        underdog_odds = match.odds_b if underdog == "B" else match.odds_a
        implied_underdog = self.compute_implied_prob(underdog_odds)

        # Value on the underdog
        inverse_value = underdog_prob - implied_underdog

        if inverse_value < self.min_inverse_value:
            return BetDecision(
                should_bet=False, strategy_name=self.name,
                reason=f"Inverse value {inverse_value:.1%} < {self.min_inverse_value:.0%}"
            )

        return BetDecision(
            should_bet=True, pick=underdog, bet_size=self.flat_bet_size,
            confidence_score=inverse_value, strategy_name=self.name,
            reason=f"Inverse: {underdog} @ {underdog_odds:.2f} (model={underdog_prob:.0%}, impl={implied_underdog:.0%})",
            edge=inverse_value, our_odds=underdog_odds,
        )
