"""
Strategy Contract Tests
========================
Validates that all strategies:
  1. Accept MatchInput and return BetDecision
  2. Have correct status/registry fields
  3. Handle edge cases (zero edge, no odds, etc.)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from strategies import STRATEGY_REGISTRY, get_live_approved, get_by_status
from strategies.strategy_base import BettingStrategy, MatchInput, BetDecision


# === Shared Fixtures ===

@pytest.fixture
def sample_match():
    """A typical match with clear favorite."""
    return MatchInput(
        player_a="Djokovic N.",
        player_b="Rune H.",
        prob_a=0.72,
        prob_b=0.28,
        odds_a=1.40,
        odds_b=3.10,
        surface="Hard",
        tourney_name="Miami Open",
        tourney_level="M",
        round_name="QF",
        confidence="HIGH",
        has_rookie=False,
        kelly_raw=0.15,
    )


@pytest.fixture
def zero_edge_match():
    """A match where model probability equals market implied."""
    return MatchInput(
        player_a="Player A",
        player_b="Player B",
        prob_a=0.50,
        prob_b=0.50,
        odds_a=2.0,
        odds_b=2.0,
        surface="Hard",
        confidence="LOW",
    )


@pytest.fixture
def no_odds_match():
    """A match with no market odds."""
    return MatchInput(
        player_a="Player A",
        player_b="Player B",
        prob_a=0.65,
        prob_b=0.35,
        odds_a=None,
        odds_b=None,
        surface="Clay",
        confidence="MEDIUM",
    )


# === Registry Tests ===

class TestStrategyRegistry:
    def test_all_strategies_present(self):
        """Registry must have at least 7 strategies."""
        assert len(STRATEGY_REGISTRY) >= 7

    def test_each_entry_has_required_fields(self):
        """Every registry entry must have instance, source, status."""
        for name, entry in STRATEGY_REGISTRY.items():
            assert 'instance' in entry, f"{name} missing 'instance'"
            assert 'source' in entry, f"{name} missing 'source'"
            assert 'status' in entry, f"{name} missing 'status'"
            assert entry['status'] in ('research', 'validated', 'live-approved'), \
                f"{name} has invalid status: {entry['status']}"

    def test_all_instances_are_strategies(self):
        """Every instance must be a BettingStrategy subclass."""
        for name, entry in STRATEGY_REGISTRY.items():
            assert isinstance(entry['instance'], BettingStrategy), \
                f"{name} instance is not a BettingStrategy"

    def test_no_live_approved_yet(self):
        """No strategy should be live-approved (honest state)."""
        approved = get_live_approved()
        assert len(approved) == 0, \
            f"Unexpected live-approved strategies: {[n for n, _ in approved]}"

    def test_all_currently_research_or_validated(self):
        """All strategies should be 'research' or 'validated'."""
        for name, entry in STRATEGY_REGISTRY.items():
            assert entry['status'] in ('research', 'validated'), \
                f"{name} has unexpected status: {entry['status']}"

    def test_sources_are_known(self):
        """Sources must be one of known types."""
        known_sources = {'ATPBetting', 'NemoFish', 'skemp15'}
        for name, entry in STRATEGY_REGISTRY.items():
            assert entry['source'] in known_sources, \
                f"{name} has unknown source: {entry['source']}"


# === Contract Tests ===

class TestStrategyContract:
    """Every strategy must accept MatchInput → BetDecision."""

    def test_all_strategies_accept_match_input(self, sample_match):
        for name, entry in STRATEGY_REGISTRY.items():
            strategy = entry['instance']
            result = strategy.evaluate_match(sample_match)
            assert isinstance(result, BetDecision), \
                f"{name} returned {type(result)}, expected BetDecision"

    def test_all_strategies_return_valid_pick(self, sample_match):
        for name, entry in STRATEGY_REGISTRY.items():
            result = entry['instance'].evaluate_match(sample_match)
            if result.should_bet:
                assert result.pick in ("A", "B"), \
                    f"{name} returned invalid pick: {result.pick}"
                assert result.bet_size > 0, \
                    f"{name} should_bet=True but bet_size={result.bet_size}"

    def test_all_strategies_handle_no_odds(self, no_odds_match):
        """Strategies must not crash with None odds."""
        for name, entry in STRATEGY_REGISTRY.items():
            try:
                result = entry['instance'].evaluate_match(no_odds_match)
                assert isinstance(result, BetDecision)
            except (TypeError, AttributeError, ZeroDivisionError):
                pytest.fail(f"{name} crashed with None odds")


# === Edge Case Tests ===

class TestEdgeCases:
    def test_kelly_zero_edge_no_bet(self, zero_edge_match):
        """Kelly with zero edge should not bet."""
        kelly = STRATEGY_REGISTRY['kelly_quarter']['instance']
        result = kelly.evaluate_match(zero_edge_match)
        # At exactly fair odds, Kelly should return 0 or not bet
        if result.should_bet:
            assert result.bet_size == 0 or result.edge <= 0

    def test_strategy_name_not_empty(self):
        """Every strategy must have a non-empty name."""
        for key, entry in STRATEGY_REGISTRY.items():
            strategy = entry['instance']
            assert strategy.name, f"{key} has empty name"
            assert strategy.description, f"{key} has empty description"

    def test_strategy_status_defaults_research(self):
        """Default status on a fresh BettingStrategy instance is 'research'."""
        from strategies.strategy_base import BettingStrategy
        class FreshStrategy(BettingStrategy):
            @property
            def name(self): return "fresh"
            @property
            def description(self): return "test"
            def evaluate_match(self, match):
                return BetDecision(should_bet=False)
        s = FreshStrategy()
        assert s.status == "research"

    def test_set_validation(self):
        """set_validation should update status and metrics."""
        from strategies.strategy_base import BettingStrategy
        # Create a concrete subclass to test
        class DummyStrategy(BettingStrategy):
            @property
            def name(self):
                return "dummy"
            @property
            def description(self):
                return "test"
            def evaluate_match(self, match):
                return BetDecision(should_bet=False)

        s = DummyStrategy()
        assert s.status == "research"
        s.set_validation("validated", roi=5.2, samples=100)
        assert s.status == "validated"
        assert s.backtest_roi == 5.2
        assert s.backtest_samples == 100
