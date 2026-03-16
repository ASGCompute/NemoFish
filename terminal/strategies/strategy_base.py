"""
Strategy Base Class
====================
Abstract base for all NemoFish betting strategies.

Every strategy must implement:
  - evaluate_match(): Decide whether to bet on a single match
  - name / description properties

Strategies receive:
  - Prediction from the model (prob_a, prob_b, confidence, etc.)
  - Market odds for both players
  - Match context (surface, round, tournament, etc.)
  - Whether either player is a rookie

Strategies return:
  - BetDecision with should_bet, pick, bet_size, confidence_score
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BetDecision:
    """Result of a strategy's evaluation of a single match."""
    should_bet: bool
    pick: str = ""              # "A" or "B" — which player to bet on
    bet_size: float = 0.0       # Bet amount (for flat strategies, this is the base amount)
    confidence_score: float = 0.0  # Strategy-specific confidence (higher = more confident)
    strategy_name: str = ""
    reason: str = ""            # Human-readable explanation
    edge: float = 0.0           # Model edge over market
    our_odds: float = 0.0       # Odds on our pick


@dataclass
class MatchInput:
    """Standardized input for strategy evaluation."""
    player_a: str
    player_b: str
    prob_a: float               # Model probability for player A
    prob_b: float               # Model probability for player B
    odds_a: Optional[float]     # Market odds for player A (decimal)
    odds_b: Optional[float]     # Market odds for player B (decimal)
    surface: str = "Hard"
    tourney_name: str = ""
    tourney_level: str = ""
    round_name: str = ""
    confidence: str = ""        # Model confidence label (LOW/MEDIUM/HIGH/ELITE)
    has_rookie: bool = False
    kelly_raw: float = 0.0      # Raw Kelly bet size from model


class BettingStrategy(ABC):
    """Abstract base class for all betting strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short strategy name for display."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of the strategy."""
        pass

    @abstractmethod
    def evaluate_match(self, match: MatchInput) -> BetDecision:
        """
        Evaluate a single match and decide whether to bet.

        Args:
            match: Standardized match input with predictions and odds.

        Returns:
            BetDecision with should_bet, pick, bet_size, confidence_score.
        """
        pass

    def compute_implied_prob(self, odds: float) -> float:
        """Convert decimal odds to implied probability."""
        if odds and odds > 0:
            return 1.0 / odds
        return 0.5

    def compute_edge(self, model_prob: float, implied_prob: float) -> float:
        """Model edge = model_prob - implied_prob."""
        return model_prob - implied_prob

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name}>"
