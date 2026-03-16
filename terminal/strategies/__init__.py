"""
NemoFish Betting Strategies
============================
Pluggable strategy architecture for testing different betting approaches.

Available strategies:
  - ValueConfirmationStrategy: Bet when model agrees with market favorite
  - ATPConfidenceStrategy: Bet on top N% most confident picks (ATPBetting approach)
  - EdgeThresholdStrategy: Bet when model edge exceeds threshold
  - KellyStrategy: Kelly Criterion variable bet sizing
  - SkempValueOnlyStrategy: Bet any side where model sees value (skemp15)
  - SkempPredictedWinValueStrategy: Bet predicted winner + value (skemp15 best: 4.78% ROI)
  - SkempInverseStrategy: Bet against prediction when odds show inefficiency (skemp15)
"""

from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput
from strategies.value_confirmation import ValueConfirmationStrategy
from strategies.atp_confidence import ATPConfidenceStrategy
from strategies.edge_threshold import EdgeThresholdStrategy
from strategies.kelly_strategy import KellyStrategy
from strategies.skemp_value import (
    SkempValueOnlyStrategy,
    SkempPredictedWinValueStrategy,
    SkempInverseStrategy,
)

__all__ = [
    'BettingStrategy', 'BetDecision', 'MatchInput',
    'ValueConfirmationStrategy',
    'ATPConfidenceStrategy',
    'EdgeThresholdStrategy',
    'KellyStrategy',
    'SkempValueOnlyStrategy',
    'SkempPredictedWinValueStrategy',
    'SkempInverseStrategy',
]
