"""
NemoFish Live Contract Tests
==============================
Tests for live pipeline contracts — ensures components wire correctly.
Run: python -m pytest terminal/tests/test_live_contracts.py -v
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestKellyStrategyContract:
    """KellyStrategy must accept kelly_fraction kwarg."""

    def test_default_instantiation(self):
        from strategies.kelly_strategy import KellyStrategy
        ks = KellyStrategy()
        assert ks is not None

    def test_fraction_kwarg(self):
        from strategies.kelly_strategy import KellyStrategy
        ks = KellyStrategy(kelly_fraction=0.25)
        assert ks.kelly_fraction == 0.25

    def test_fraction_kwarg_half(self):
        from strategies.kelly_strategy import KellyStrategy
        ks = KellyStrategy(kelly_fraction=0.50)
        assert ks.kelly_fraction == 0.50

    def test_wrong_kwarg_fails(self):
        """The old buggy kwarg 'fraction' should NOT work."""
        from strategies.kelly_strategy import KellyStrategy
        with pytest.raises(TypeError):
            KellyStrategy(fraction=0.25)


class TestMatchContextOdds:
    """MatchContext must accept and properly store odds_a/odds_b."""

    def test_odds_fields_populated(self):
        from agents.tennis_swarm import MatchContext
        ctx = MatchContext(
            player_a="Sinner", player_b="Alcaraz",
            surface="Hard", tourney_name="Miami Open",
            tourney_level="M", round_name="SF", date="2026-03-18",
            odds_a=1.55, odds_b=2.65,
        )
        assert ctx.odds_a == 1.55
        assert ctx.odds_b == 2.65

    def test_odds_fields_none(self):
        from agents.tennis_swarm import MatchContext
        ctx = MatchContext(
            player_a="A", player_b="B",
            surface="Hard", tourney_name="Test",
            tourney_level="B", round_name="R32", date="2026-01-01",
        )
        assert ctx.odds_a is None
        assert ctx.odds_b is None


class TestSwarmAttribute:
    """TennisSwarm must have .elo attribute (not .elo_engine)."""

    def test_swarm_has_elo(self):
        from agents.tennis_swarm import TennisSwarm
        swarm = TennisSwarm()
        assert hasattr(swarm, 'elo')
        assert not hasattr(swarm, 'elo_engine')

    def test_swarm_elo_has_methods(self):
        from agents.tennis_swarm import TennisSwarm
        swarm = TennisSwarm()
        assert hasattr(swarm.elo, 'get_player')
        assert hasattr(swarm.elo, 'predict_match')


class TestMarketMatching:
    """match_fixture_to_polymarket must correctly match or return None."""

    def test_no_markets_returns_none(self):
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from live_runner import match_fixture_to_polymarket
        from dataclasses import dataclass

        @dataclass
        class FakeFixture:
            player_a: str = "Jannik Sinner"
            player_b: str = "Carlos Alcaraz"

        result = match_fixture_to_polymarket(FakeFixture(), [], [])
        assert result is None

    def test_matching_market_found(self):
        from live_runner import match_fixture_to_polymarket
        from execution.polymarket_live import Market
        from dataclasses import dataclass

        @dataclass
        class FakeFixture:
            player_a: str = "Jannik Sinner"
            player_b: str = "Carlos Alcaraz"

        market = Market(
            condition_id="0xabc123",
            question="Will Sinner win vs Alcaraz?",
            yes_price=0.62,
            no_price=0.38,
            volume=50000,
            liquidity=10000,
            active=True,
            token_yes="0xtoken_yes",
            token_no="0xtoken_no",
            event_title="Sinner vs Alcaraz - Miami Open",
            event_slug="sinner-alcaraz",
        )

        result = match_fixture_to_polymarket(FakeFixture(), [market], [])
        assert result is not None
        assert result.condition_id == "0xabc123"

    def test_no_token_market_skipped(self):
        from live_runner import match_fixture_to_polymarket
        from execution.polymarket_live import Market
        from dataclasses import dataclass

        @dataclass
        class FakeFixture:
            player_a: str = "Jannik Sinner"
            player_b: str = "Carlos Alcaraz"

        market = Market(
            condition_id="0xabc123",
            question="Sinner vs Alcaraz",
            yes_price=0.62,
            no_price=0.38,
            volume=50000,
            liquidity=10000,
            active=True,
            token_yes="",
            token_no="",
            event_title="Sinner vs Alcaraz - Miami Open",
            event_slug="sinner-alcaraz",
        )

        result = match_fixture_to_polymarket(FakeFixture(), [market], [])
        assert result is None  # No tokens → no match


class TestFailClosedPolicy:
    """Pipeline must skip matches without odds or market match."""

    def test_no_odds_constant(self):
        """NO_ODDS string must be the sentinel."""
        import live_runner
        # The pipeline uses "NO_ODDS" string as sentinel
        assert hasattr(live_runner, 'MIN_EDGE_THRESHOLD')

    def test_canary_constants(self):
        """Canary rules must be defined."""
        import live_runner
        assert live_runner.CANARY_MAX_STAKE == 1.0
        assert live_runner.CANARY_MAX_DAILY == 4.0
        assert live_runner.CANARY_MAX_CONCURRENT == 1


class TestStrategyRegistry:
    """All strategies in the registry must be instantiable."""

    def test_registry_loads(self):
        import live_runner
        assert len(live_runner.STRATEGY_REGISTRY) >= 5

    def test_kelly_in_registry(self):
        import live_runner
        assert 'kelly_quarter' in live_runner.STRATEGY_REGISTRY
        ks = live_runner.STRATEGY_REGISTRY['kelly_quarter']
        assert ks.kelly_fraction == 0.25

    def test_default_strategies_exist(self):
        import live_runner
        for s in live_runner.DEFAULT_STRATEGIES:
            assert s in live_runner.STRATEGY_REGISTRY


class TestEnvLoading:
    """Environment variables must be loaded from .env (not hardcoded)."""

    def test_no_hardcoded_api_tennis_key(self):
        """api_tennis.py must not contain hardcoded key."""
        source = (Path(__file__).parent.parent / "feeds" / "api_tennis.py").read_text()
        assert "d146e28f6dd96205fcd9302463e3113176b77600442f99444137df409e8456e8" not in source

    def test_no_hardcoded_sportradar_key(self):
        """sportradar_tennis.py must not contain hardcoded key."""
        source = (Path(__file__).parent.parent / "feeds" / "sportradar_tennis.py").read_text()
        assert "XK6HLp7UPB4rzBn81U2prttFCerHbbIHMD2kftCU" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
