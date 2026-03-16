"""
NemoFish Unit Tests — Core Betting Engine
==========================================
Tests for WElo, strategies, CLV tracker, and Kelly criterion.
Run: python -m pytest terminal/tests/test_core.py -v
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# === WElo Tests ===

class TestWElo:
    """Test WElo (Weighted Elo) margin parsing and updates."""

    def setup_method(self):
        from models.tennis_elo import TennisEloEngine
        self.engine = TennisEloEngine()

    def test_margin_dominant_win(self):
        """6-0 6-0 should produce margin = 1.0"""
        m = self.engine._parse_score_margin("6-0 6-0")
        assert abs(m - 1.0) < 0.01

    def test_margin_close_win(self):
        """7-6 7-6 should produce margin ≈ 0.52"""
        m = self.engine._parse_score_margin("7-6(5) 7-6(3)")
        assert 0.45 < m < 0.60

    def test_margin_three_setter(self):
        """6-4 4-6 7-5 should produce margin ≈ 0.35"""
        m = self.engine._parse_score_margin("6-4 4-6 7-5")
        assert 0.30 < m < 0.45

    def test_margin_none_score(self):
        """None score should return 1.0 (standard Elo)"""
        m = self.engine._parse_score_margin(None)
        assert m == 1.0

    def test_margin_retirement(self):
        """RET should return 1.0"""
        m = self.engine._parse_score_margin("RET")
        assert m == 1.0

    def test_welo_dominant_vs_close(self):
        """Dominant win should give much more Elo than close win."""
        e1 = self._fresh_engine()
        e2 = self._fresh_engine()

        e1.update_elo("A", "B", "Hard", "G", "2024-01-01", score="6-0 6-0")
        e2.update_elo("A", "B", "Hard", "G", "2024-01-01", score="7-6(5) 7-6(3)")

        delta_dominant = e1.get_player("A").overall - 1500
        delta_close = e2.get_player("A").overall - 1500

        assert delta_dominant > delta_close * 5, \
            f"Dominant ({delta_dominant}) should be 5x+ more than close ({delta_close})"

    def test_welo_updates_surface(self):
        """WElo should update surface-specific ratings too."""
        self.engine.update_elo("A", "B", "Clay", "G", "2024-01-01", score="6-0 6-0")
        p = self.engine.get_player("A")
        assert p.clay > 1500

    def test_predict_basic(self):
        """Player with wins should have higher probability."""
        for i in range(10):
            self.engine.update_elo("Strong", "Weak", "Hard", "B", f"2024-01-{i+1:02d}")

        prob = self.engine.predict_match("Strong", "Weak", "Hard")
        assert prob > 0.6

    def _fresh_engine(self):
        from models.tennis_elo import TennisEloEngine
        return TennisEloEngine()


# === Strategy Tests ===

class TestStrategies:
    """Test strategy evaluation and Kelly sizing."""

    def test_kelly_positive_edge(self):
        """Kelly should return positive bet for positive edge."""
        from strategies.strategy_base import BettingStrategy, MatchInput

        class TestStrat(BettingStrategy):
            @property
            def name(self): return "test"
            @property
            def description(self): return "test"
            def evaluate_match(self, match): pass

        s = TestStrat()
        # 60% prob, 2.0 odds (implied 50%) → edge exists
        bet = s.compute_kelly(model_prob=0.60, odds=2.0, bankroll=1000)
        assert bet > 0
        assert bet < 250  # 25% Kelly should cap it

    def test_kelly_no_edge(self):
        """Kelly should return 0 when no edge."""
        from strategies.strategy_base import BettingStrategy

        class TestStrat(BettingStrategy):
            @property
            def name(self): return "test"
            @property
            def description(self): return "test"
            def evaluate_match(self, match): pass

        s = TestStrat()
        # 40% prob, 2.0 odds (implied 50%) → no edge
        bet = s.compute_kelly(model_prob=0.40, odds=2.0, bankroll=1000)
        assert bet == 0

    def test_atp_confidence_strategy(self):
        """ATPConfidence should bet on high-confidence, high-edge matches."""
        from strategies import ATPConfidenceStrategy
        from strategies.strategy_base import MatchInput

        strat = ATPConfidenceStrategy(top_pct=0.10)
        match = MatchInput(
            player_a="Sinner", player_b="Unknown",
            prob_a=0.85, prob_b=0.15,
            odds_a=1.30, odds_b=3.50,
            confidence="ELITE",
        )
        decision = strat.evaluate_match(match)
        assert decision.should_bet == True
        assert decision.pick == "A"

    def test_edge_threshold_skips_low_edge(self):
        """EdgeThreshold should skip matches with edge < threshold."""
        from strategies import EdgeThresholdStrategy
        from strategies.strategy_base import MatchInput

        strat = EdgeThresholdStrategy(min_edge=0.10)
        match = MatchInput(
            player_a="A", player_b="B",
            prob_a=0.52, prob_b=0.48,
            odds_a=1.90, odds_b=1.90,
            confidence="LOW",
        )
        decision = strat.evaluate_match(match)
        # Edge = 0.52 - 0.526 = -0.006 → no bet
        assert decision.should_bet == False


# === CLV Tracker Tests ===

class TestCLVTracker:
    """Test CLV tracking and reporting."""

    def test_positive_clv(self):
        """Bet at better odds than closing → positive CLV."""
        from execution.clv_tracker import BetRecord
        rec = BetRecord(
            match_id="test1", timestamp="2024-01-01",
            player_a="A", player_b="B", pick="A",
            odds_at_bet=1.85, closing_odds=1.75,
        )
        assert rec.clv > 0  # 1.85/1.75 - 1 = +5.7%

    def test_negative_clv(self):
        """Bet at worse odds than closing → negative CLV."""
        from execution.clv_tracker import BetRecord
        rec = BetRecord(
            match_id="test2", timestamp="2024-01-01",
            player_a="A", player_b="B", pick="A",
            odds_at_bet=1.60, closing_odds=1.75,
        )
        assert rec.clv < 0

    def test_tracker_summary(self):
        """Tracker should produce valid summary."""
        import tempfile
        from execution.clv_tracker import CLVTracker

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = CLVTracker(data_dir=tmpdir)
            tracker.record_bet("m1", "A", "B", "A", 1.85, strategy_name="test")
            tracker.record_closing_line("m1", 1.75)
            tracker.record_result("m1", "win")

            s = tracker.summary()
            assert s["total_bets"] == 1
            assert s["clv_tracked"] == 1
            assert s["avg_clv"] > 0


# === Integration Test ===

class TestIntegration:
    """Integration tests for full pipeline components."""

    def test_strategy_imports(self):
        """All strategy classes should be importable."""
        from strategies import (
            ATPConfidenceStrategy, ValueConfirmationStrategy,
            EdgeThresholdStrategy, KellyStrategy,
            SkempValueOnlyStrategy, SkempPredictedWinValueStrategy,
            SkempInverseStrategy,
        )
        assert ATPConfidenceStrategy is not None
        assert len([ATPConfidenceStrategy, ValueConfirmationStrategy,
                    EdgeThresholdStrategy, KellyStrategy,
                    SkempValueOnlyStrategy, SkempPredictedWinValueStrategy,
                    SkempInverseStrategy]) == 7

    def test_match_input_creation(self):
        """MatchInput with all default fields should work."""
        from strategies.strategy_base import MatchInput
        mi = MatchInput(
            player_a="Sinner", player_b="Alcaraz",
            prob_a=0.55, prob_b=0.45,
            odds_a=1.80, odds_b=2.10,
        )
        assert mi.surface == "Hard"
        assert mi.kelly_raw == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
