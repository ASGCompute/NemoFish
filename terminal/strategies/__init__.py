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
    'STRATEGY_REGISTRY',
]

# === Unified Strategy Registry ===
# Maps canonical name → (instance, source, validation_status)
# Status: "research" = unproven, "validated" = positive ROI in backtest, "live-approved" = founder sign-off
#
# Backtest results loaded automatically from execution/backtest_results.json
# when available. Run `python3 backtest_historical.py` to generate.

STRATEGY_REGISTRY = {
    'atp_confidence_5': {
        'instance': ATPConfidenceStrategy(top_pct=0.05),
        'source': 'ATPBetting',
        'status': 'research',
        'note': 'Insufficient sample (N<50)',
    },
    'atp_confidence_10': {
        'instance': ATPConfidenceStrategy(top_pct=0.10),
        'source': 'ATPBetting',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
    'atp_confidence_15': {
        'instance': ATPConfidenceStrategy(top_pct=0.15),
        'source': 'ATPBetting',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
    'value_confirmation': {
        'instance': ValueConfirmationStrategy(),
        'source': 'NemoFish',
        'status': 'live-approved',  # Founder sign-off 2026-03-16
        'note': '+1.4% ROI on 107 bets (backtest validated, founder approved)',
    },
    'edge_3pct': {
        'instance': EdgeThresholdStrategy(min_edge=0.03),
        'source': 'NemoFish',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
    'edge_5pct': {
        'instance': EdgeThresholdStrategy(min_edge=0.05),
        'source': 'NemoFish',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
    'kelly_quarter': {
        'instance': KellyStrategy(kelly_fraction=0.25),
        'source': 'NemoFish',
        'status': 'research',
        'note': 'No bets placed in backtest',
    },
    'skemp_value': {
        'instance': SkempValueOnlyStrategy(),
        'source': 'skemp15',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
    'skemp_predict_value': {
        'instance': SkempPredictedWinValueStrategy(),
        'source': 'skemp15',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
    'skemp_inverse': {
        'instance': SkempInverseStrategy(),
        'source': 'skemp15',
        'status': 'research',
        'note': 'Negative ROI in backtest',
    },
}

# === Name mapping: backtest strategy name → registry key ===
_BACKTEST_TO_REGISTRY = {
    'ValueConfirmation': 'value_confirmation',
    'ATPConfidence(top5%)': 'atp_confidence_5',
    'ATPConfidence(top10%)': 'atp_confidence_10',
    'ATPConfidence(top15%)': 'atp_confidence_15',
    'Edge(3%-30%)': 'edge_3pct',
    'Edge(5%-20%)': 'edge_5pct',
    'Kelly(¼)': 'kelly_quarter',
    'SkempValue': 'skemp_value',
    'SkempPredictWin+Value': 'skemp_predict_value',
    'SkempInverse': 'skemp_inverse',
}


def apply_backtest_results(path: str = None) -> int:
    """
    Load latest backtest_results.json and auto-promote strategies.
    
    research → validated: if all validation criteria pass.
    validated → live-approved: NOT automated (requires founder sign-off).
    
    Returns count of strategies promoted.
    """
    import json
    from pathlib import Path as _Path

    if path is None:
        path = str(_Path(__file__).parent.parent / "execution" / "backtest_results.json")

    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

    promoted = 0
    strategies_data = data.get("strategies", {})

    for bt_name, metrics in strategies_data.items():
        reg_key = _BACKTEST_TO_REGISTRY.get(bt_name)
        if not reg_key or reg_key not in STRATEGY_REGISTRY:
            continue

        entry = STRATEGY_REGISTRY[reg_key]
        validation = metrics.get("validation", {})
        roi = metrics.get("roi", 0)
        bets = metrics.get("bets", 0)

        if validation.get("passes", False) and entry["status"] == "research":
            entry["status"] = "validated"
            entry["note"] = f"+{roi:.1f}% ROI on {bets} bets (backtest validated)"
            # Also set on the BettingStrategy instance
            entry["instance"].set_validation("validated", roi, bets)
            promoted += 1
        elif not validation.get("passes", False):
            # Update note with latest results
            reasons = validation.get("fail_reasons", [])
            if bets > 0:
                entry["note"] = f"{roi:+.1f}% ROI on {bets} bets ({'; '.join(reasons)})"
            else:
                entry["note"] = "No bets placed in backtest"

    return promoted


def get_live_approved() -> list:
    """Return only live-approved strategies."""
    return [
        (name, entry) for name, entry in STRATEGY_REGISTRY.items()
        if entry['status'] == 'live-approved'
    ]


def get_by_status(status: str) -> list:
    """Return strategies by validation status."""
    return [
        (name, entry) for name, entry in STRATEGY_REGISTRY.items()
        if entry['status'] == status
    ]


# Auto-load backtest results on import
_promoted = apply_backtest_results()
if _promoted > 0:
    import sys
    print(f"  🔬 {_promoted} strategy(s) auto-promoted to 'validated'", file=sys.stderr)
