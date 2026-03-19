"""
NemoFish Scenario Engine — Unit Tests
=======================================
Tests schema, dossier, overlay bounds, and skip escalation.
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from intelligence.player_profile_schema import (
    PlayerIntelligence, PlayerIdentity, PlayStyle, MentalProfile,
    PhysicalProfile, SurfaceProfile, FormProfile, MarketProfile,
    NewsProfile, Unknowns, H2HSummary, TournamentContext, MatchDossier,
)
from intelligence.scenario_simulation import ScenarioSignals, ScenarioSimulation
from intelligence.scenario_overlay import ScenarioOverlay, OverlayResult


# === Schema Tests ===

class TestPlayerProfileSchema:
    def test_player_intelligence_roundtrip(self):
        """PlayerIntelligence → JSON → back, all fields preserved."""
        pi = PlayerIntelligence(
            identity=PlayerIdentity(
                name="Jannik Sinner", ranking=1, elo_overall=2105.3
            ),
            play_style=PlayStyle(
                serve_type="solid", return_game="elite"
            ),
            mental_profile=MentalProfile(pressure_handling=0.8),
        )

        json_str = pi.to_json()
        data = json.loads(json_str)
        restored = PlayerIntelligence.from_dict(data)

        assert restored.identity.name == "Jannik Sinner"
        assert restored.identity.ranking == 1
        assert restored.identity.elo_overall == 2105.3
        assert restored.play_style.serve_type == "solid"
        assert restored.play_style.return_game == "elite"
        assert restored.mental_profile.pressure_handling == 0.8

    def test_match_dossier_roundtrip(self):
        """MatchDossier → JSON → back."""
        dossier = MatchDossier(
            player_a=PlayerIntelligence(
                identity=PlayerIdentity(name="Sinner")
            ),
            player_b=PlayerIntelligence(
                identity=PlayerIdentity(name="Alcaraz")
            ),
            h2h=H2HSummary(total_matches=10, a_wins=6, b_wins=4),
            tournament=TournamentContext(
                tournament_name="Miami Open", surface="Hard",
                tournament_level="M", round_name="F",
            ),
            data_quality=0.85,
        )

        json_str = dossier.to_json()
        data = json.loads(json_str)
        restored = MatchDossier.from_dict(data)

        assert restored.player_a.identity.name == "Sinner"
        assert restored.player_b.identity.name == "Alcaraz"
        assert restored.h2h.a_wins == 6
        assert restored.tournament.surface == "Hard"
        assert restored.data_quality == 0.85

    def test_default_values(self):
        """All defaults should be sane."""
        pi = PlayerIntelligence()
        assert pi.identity.ranking == 999
        assert pi.identity.elo_overall == 1500.0
        assert pi.play_style.serve_type == "unknown"
        assert pi.mental_profile.pressure_handling == 0.5
        assert pi.physical_profile.fatigue_score == 0.0

    def test_unknowns_tracking(self):
        """Unknowns should track missing data."""
        u = Unknowns(
            missing_data_fields=["elo_data", "sackmann"],
            low_confidence_flags=["limited_h2h"],
            data_quality_score=0.4,
        )
        assert len(u.missing_data_fields) == 2
        assert u.data_quality_score == 0.4


# === Scenario Signals Tests ===

class TestScenarioSignals:
    def test_neutral_signals(self):
        """Neutral signals should have zero confidence."""
        signals = ScenarioSignals.neutral()
        assert signals.simulation_confidence == 0.0
        assert signals.pressure_edge_a == 0.5
        assert signals.pressure_edge_b == 0.5

    def test_dry_run_simulation(self):
        """Dry run should return plausible non-neutral signals."""
        sim = ScenarioSimulation()
        signals = sim.simulate_dry_run("{}")
        assert signals.simulation_confidence > 0
        assert signals.pressure_edge_a != signals.pressure_edge_b
        assert len(signals.recommended_adjustments) > 0

    def test_signals_serialization(self):
        """ScenarioSignals should serialize to JSON."""
        signals = ScenarioSignals(
            pressure_edge_a=0.7, pressure_edge_b=0.3,
            volatility_score=0.8,
        )
        data = json.loads(signals.to_json())
        assert data["pressure_edge_a"] == 0.7
        assert data["volatility_score"] == 0.8


# === Overlay Tests ===

class TestScenarioOverlay:
    def test_probability_cap_respected(self):
        """Overlay adjustment must never exceed ±3%."""
        overlay = ScenarioOverlay(max_prob_adjustment=0.03)

        # Extreme signals that would push large adjustment
        signals = ScenarioSignals(
            pressure_edge_a=1.0, pressure_edge_b=0.0,
            fatigue_risk_a=0.0, fatigue_risk_b=1.0,
            matchup_discomfort_a=0.0, matchup_discomfort_b=1.0,
            mental_resilience_a=1.0, mental_resilience_b=0.0,
            simulation_confidence=0.9,
        )

        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.50,
            baseline_prob_b=0.50,
            baseline_confidence="MEDIUM",
            baseline_action="SKIP",
        )

        delta = abs(result.adjusted_prob_a - result.baseline_prob_a)
        assert delta <= 0.03 + 1e-9, f"Delta {delta} exceeds cap 0.03"

    def test_neutral_signals_no_adjustment(self):
        """Neutral signals should not change probability."""
        overlay = ScenarioOverlay()
        signals = ScenarioSignals.neutral()

        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.60,
            baseline_prob_b=0.40,
            baseline_confidence="HIGH",
            baseline_action="BET_A",
        )

        assert result.adjusted_prob_a == result.baseline_prob_a
        # Neutral signals have sim_confidence=0 which triggers downgrade — that's correct
        # Confidence should stay same OR downgrade, never upgrade
        conf_order = ["LOW", "MEDIUM", "HIGH", "ELITE"]
        assert conf_order.index(result.adjusted_confidence) <= conf_order.index("HIGH")

    def test_skip_escalation_injury(self):
        """High injury risk should force SKIP."""
        overlay = ScenarioOverlay(injury_skip_threshold=0.7)
        signals = ScenarioSignals(
            injury_risk_a=0.85,
            simulation_confidence=0.6,
        )

        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.70,
            baseline_prob_b=0.30,
            baseline_confidence="HIGH",
            baseline_action="BET_A",
        )

        assert result.skip_escalated is True
        assert result.adjusted_action == "SKIP"

    def test_skip_escalation_ambiguity(self):
        """Very low simulation confidence should force SKIP."""
        overlay = ScenarioOverlay(ambiguity_skip_threshold=0.15)
        signals = ScenarioSignals(
            simulation_confidence=0.05,
        )

        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.65,
            baseline_prob_b=0.35,
            baseline_confidence="MEDIUM",
            baseline_action="BET_A",
        )

        assert result.skip_escalated is True
        assert result.adjusted_action == "SKIP"

    def test_confidence_only_downgrades(self):
        """Overlay can downgrade confidence but never upgrade."""
        overlay = ScenarioOverlay()

        # Low simulation confidence should downgrade
        signals = ScenarioSignals(
            simulation_confidence=0.2,
            volatility_score=0.8,  # Also triggers downgrade
        )

        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.60,
            baseline_prob_b=0.40,
            baseline_confidence="HIGH",
            baseline_action="BET_A",
        )

        # Should be downgraded from HIGH
        confidence_order = ["LOW", "MEDIUM", "HIGH", "ELITE"]
        baseline_idx = confidence_order.index("HIGH")
        adjusted_idx = confidence_order.index(result.adjusted_confidence)
        assert adjusted_idx <= baseline_idx, "Confidence was upgraded, not allowed"

    def test_probability_bounds(self):
        """Adjusted probabilities must stay in [0.05, 0.95]."""
        overlay = ScenarioOverlay()
        signals = ScenarioSignals(
            pressure_edge_a=1.0, pressure_edge_b=0.0,
            simulation_confidence=0.9,
        )

        # Test near extremes
        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.94,
            baseline_prob_b=0.06,
            baseline_confidence="MEDIUM",
            baseline_action="BET_A",
        )

        assert result.adjusted_prob_a <= 0.95
        assert result.adjusted_prob_b >= 0.05

    def test_audit_trail(self):
        """Every adjustment should have audit information."""
        overlay = ScenarioOverlay()
        signals = ScenarioSignals(
            pressure_edge_a=0.8, pressure_edge_b=0.2,
            simulation_confidence=0.7,
        )

        result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.55,
            baseline_prob_b=0.45,
            baseline_confidence="MEDIUM",
            baseline_action="SKIP",
        )

        assert len(result.adjustments) > 0
        for adj in result.adjustments:
            assert adj.field, "Adjustment missing field"
            assert adj.reason, "Adjustment missing reason"
            assert adj.source_signal, "Adjustment missing source_signal"


# === Report Tests ===

class TestScenarioReport:
    def test_report_generation(self):
        """Report should contain all required sections."""
        # Import directly to avoid Flask dependency in backend/app/__init__.py
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "tennis_report_adapter",
            str(Path(__file__).parent.parent.parent / "backend" / "app" / "services" / "tennis_report_adapter.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        generate_scenario_report = mod.generate_scenario_report

        dossier = MatchDossier(
            player_a=PlayerIntelligence(
                identity=PlayerIdentity(name="Sinner", ranking=1, elo_overall=2100),
            ),
            player_b=PlayerIntelligence(
                identity=PlayerIdentity(name="Alcaraz", ranking=3, elo_overall=2050),
            ),
            data_quality=0.8,
        )

        signals = ScenarioSignals(
            pressure_edge_a=0.6, pressure_edge_b=0.4,
            simulation_confidence=0.7,
        )

        overlay = ScenarioOverlay()
        overlay_result = overlay.apply(
            signals=signals,
            baseline_prob_a=0.55, baseline_prob_b=0.45,
            baseline_confidence="MEDIUM", baseline_action="SKIP",
        )

        report = generate_scenario_report(
            dossier_dict=dossier.to_dict(),
            signals_dict=signals.to_dict(),
            overlay_dict=overlay_result.to_dict(),
        )

        assert "dossier_summary" in report
        assert "simulation_signals" in report
        assert "overlay_comparison" in report
        assert "adjustments" in report
        assert report["report_type"] == "nemofish_scenario"


# === Ontology Tests ===

class TestTennisOntology:
    @pytest.fixture(autouse=True)
    def load_modules(self):
        """Load backend modules directly to avoid Flask dependency."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "tennis_ontology",
            str(Path(__file__).parent.parent.parent / "backend" / "app" / "services" / "tennis_ontology.py")
        )
        self._ontology_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._ontology_mod)

    def test_ontology_structure(self):
        """Ontology should have 10 entity types and 8 edge types."""
        ontology = self._ontology_mod.get_tennis_ontology()
        assert len(ontology["entity_types"]) == 10
        assert len(ontology["edge_types"]) == 8

    def test_required_entities_present(self):
        """Required entity types must be present."""
        ontology = self._ontology_mod.get_tennis_ontology()
        entity_names = {e["name"] for e in ontology["entity_types"]}

        required = {"Player", "Tournament", "Surface", "Match", "Market", "Injury"}
        assert required.issubset(entity_names)

    def test_graph_text_generation(self):
        """build_match_graph_text should produce non-empty text."""
        build_match_graph_text = self._ontology_mod.build_match_graph_text

        dossier = MatchDossier(
            player_a=PlayerIntelligence(
                identity=PlayerIdentity(name="Sinner", ranking=1, elo_overall=2100),
            ),
            player_b=PlayerIntelligence(
                identity=PlayerIdentity(name="Alcaraz", ranking=3, elo_overall=2050),
            ),
            tournament=TournamentContext(
                tournament_name="Miami Open", surface="Hard",
            ),
        )
        text = build_match_graph_text(dossier.to_dict())
        assert len(text) > 100
        assert "Sinner" in text
        assert "Alcaraz" in text
