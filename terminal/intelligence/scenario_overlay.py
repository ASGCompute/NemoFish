"""
Scenario Overlay Adapter — Bounded Adjustment Layer
=====================================================
Takes ScenarioSignals + SwarmConsensus and produces bounded adjustments.

Safety constraints:
  - Max probability adjustment: ±3% (configurable)
  - Confidence can only be downgraded, never upgraded
  - High injury/ambiguity → force SKIP
  - Every adjustment is logged with reason
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from intelligence.scenario_simulation import ScenarioSignals


@dataclass
class Adjustment:
    """A single adjustment with reason."""
    field: str
    delta: float
    reason: str
    source_signal: str


@dataclass
class OverlayResult:
    """Result of applying scenario overlay to swarm consensus."""
    baseline_prob_a: float
    baseline_prob_b: float
    adjusted_prob_a: float
    adjusted_prob_b: float
    baseline_confidence: str
    adjusted_confidence: str
    baseline_action: str
    adjusted_action: str
    adjustments: List[Adjustment] = field(default_factory=list)
    skip_escalated: bool = False
    skip_reason: str = ""
    explanation: str = ""
    simulation_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["total_prob_delta"] = round(
            self.adjusted_prob_a - self.baseline_prob_a, 4
        )
        return result


class ScenarioOverlay:
    """
    Bounded overlay adapter for swarm predictions.

    Config:
        max_prob_adjustment: Maximum probability change (default 0.03 = 3%)
        injury_skip_threshold: Force SKIP if injury risk exceeds this
        ambiguity_skip_threshold: Force SKIP if simulation confidence below this
    """

    # Confidence hierarchy for downgrade logic
    CONFIDENCE_ORDER = ["LOW", "MEDIUM", "HIGH", "ELITE"]

    def __init__(
        self,
        max_prob_adjustment: float = 0.03,
        injury_skip_threshold: float = 0.7,
        ambiguity_skip_threshold: float = 0.15,
    ):
        self.max_prob_adjustment = max_prob_adjustment
        self.injury_skip_threshold = injury_skip_threshold
        self.ambiguity_skip_threshold = ambiguity_skip_threshold

    def apply(
        self,
        signals: ScenarioSignals,
        baseline_prob_a: float,
        baseline_prob_b: float,
        baseline_confidence: str,
        baseline_action: str,
        player_a: str = "A",
        player_b: str = "B",
    ) -> OverlayResult:
        """
        Apply scenario signals as bounded overlay to baseline prediction.

        Returns:
            OverlayResult with adjusted values and audit trail.
        """
        adjustments = []
        total_delta = 0.0

        # === 1. Pressure Edge Adjustment ===
        pressure_diff = signals.pressure_edge_a - signals.pressure_edge_b
        if abs(pressure_diff) > 0.1:
            delta = pressure_diff * 0.02  # Scale down: max ~2% from pressure
            delta = self._clamp(delta)
            adjustments.append(Adjustment(
                field="prob_a",
                delta=round(delta, 4),
                reason=f"Pressure edge: {player_a} {signals.pressure_edge_a:.0%} vs {player_b} {signals.pressure_edge_b:.0%}",
                source_signal="pressure_edge",
            ))
            total_delta += delta

        # === 2. Fatigue Risk Adjustment ===
        fatigue_diff = signals.fatigue_risk_b - signals.fatigue_risk_a
        if abs(fatigue_diff) > 0.1:
            delta = fatigue_diff * 0.015  # Max ~1.5% from fatigue
            delta = self._clamp(delta)
            adjustments.append(Adjustment(
                field="prob_a",
                delta=round(delta, 4),
                reason=f"Fatigue risk: {player_a} {signals.fatigue_risk_a:.0%} vs {player_b} {signals.fatigue_risk_b:.0%}",
                source_signal="fatigue_risk",
            ))
            total_delta += delta

        # === 3. Matchup Discomfort ===
        discomfort_diff = signals.matchup_discomfort_b - signals.matchup_discomfort_a
        if abs(discomfort_diff) > 0.1:
            delta = discomfort_diff * 0.015
            delta = self._clamp(delta)
            adjustments.append(Adjustment(
                field="prob_a",
                delta=round(delta, 4),
                reason=f"Matchup discomfort: {player_a} {signals.matchup_discomfort_a:.0%} vs {player_b} {signals.matchup_discomfort_b:.0%}",
                source_signal="matchup_discomfort",
            ))
            total_delta += delta

        # === 4. Mental Resilience ===
        mental_diff = signals.mental_resilience_a - signals.mental_resilience_b
        if abs(mental_diff) > 0.1:
            delta = mental_diff * 0.01  # Max ~1% from mental
            delta = self._clamp(delta)
            adjustments.append(Adjustment(
                field="prob_a",
                delta=round(delta, 4),
                reason=f"Mental resilience: {player_a} {signals.mental_resilience_a:.0%} vs {player_b} {signals.mental_resilience_b:.0%}",
                source_signal="mental_resilience",
            ))
            total_delta += delta

        # === Apply cap on total adjustment ===
        if abs(total_delta) > self.max_prob_adjustment:
            scale_factor = self.max_prob_adjustment / abs(total_delta)
            total_delta = total_delta * scale_factor
            # Scale all individual adjustments proportionally
            for adj in adjustments:
                adj.delta = round(adj.delta * scale_factor, 4)

        # === Calculate adjusted probabilities ===
        adjusted_prob_a = max(0.05, min(0.95, baseline_prob_a + total_delta))
        adjusted_prob_b = 1.0 - adjusted_prob_a

        # === Confidence Adjustment (can only go down) ===
        adjusted_confidence = baseline_confidence
        if signals.simulation_confidence < 0.3:
            # Low simulation confidence → reduce our confidence
            adjusted_confidence = self._downgrade_confidence(
                baseline_confidence, 1
            )
            adjustments.append(Adjustment(
                field="confidence",
                delta=0,
                reason=f"Low simulation confidence ({signals.simulation_confidence:.0%}) → confidence downgrade",
                source_signal="simulation_confidence",
            ))

        if signals.volatility_score > 0.75:
            # High volatility → reduce confidence
            adjusted_confidence = self._downgrade_confidence(
                adjusted_confidence, 1
            )
            adjustments.append(Adjustment(
                field="confidence",
                delta=0,
                reason=f"High volatility ({signals.volatility_score:.0%}) → confidence downgrade",
                source_signal="volatility_score",
            ))

        # === Skip Escalation ===
        skip_escalated = False
        skip_reason = ""

        # Check injury risk
        max_injury = max(signals.injury_risk_a, signals.injury_risk_b)
        if max_injury > self.injury_skip_threshold:
            skip_escalated = True
            injured_player = player_a if signals.injury_risk_a > signals.injury_risk_b else player_b
            skip_reason = f"High injury risk ({injured_player}: {max_injury:.0%})"

        # Check ambiguity
        if signals.simulation_confidence < self.ambiguity_skip_threshold:
            skip_escalated = True
            skip_reason = f"Simulation too ambiguous (confidence: {signals.simulation_confidence:.0%})"

        # Determine adjusted action
        adjusted_action = baseline_action
        if skip_escalated and baseline_action != "SKIP":
            adjusted_action = "SKIP"
            adjustments.append(Adjustment(
                field="action",
                delta=0,
                reason=f"Skip escalation: {skip_reason}",
                source_signal="skip_escalation",
            ))

        # === Build explanation ===
        explanation_parts = []
        if abs(total_delta) > 0.001:
            direction = "toward" if total_delta > 0 else "away from"
            explanation_parts.append(
                f"Probability shifted {direction} {player_a} by {abs(total_delta):.1%}"
            )
        if adjusted_confidence != baseline_confidence:
            explanation_parts.append(
                f"Confidence downgraded: {baseline_confidence} → {adjusted_confidence}"
            )
        if skip_escalated:
            explanation_parts.append(f"SKIP escalated: {skip_reason}")
        if not explanation_parts:
            explanation_parts.append("No significant adjustments from scenario simulation")

        return OverlayResult(
            baseline_prob_a=round(baseline_prob_a, 4),
            baseline_prob_b=round(baseline_prob_b, 4),
            adjusted_prob_a=round(adjusted_prob_a, 4),
            adjusted_prob_b=round(adjusted_prob_b, 4),
            baseline_confidence=baseline_confidence,
            adjusted_confidence=adjusted_confidence,
            baseline_action=baseline_action,
            adjusted_action=adjusted_action,
            adjustments=adjustments,
            skip_escalated=skip_escalated,
            skip_reason=skip_reason,
            explanation=". ".join(explanation_parts),
            simulation_confidence=round(signals.simulation_confidence, 3),
        )

    def _clamp(self, delta: float) -> float:
        """Clamp a single adjustment to ±max_prob_adjustment."""
        return max(-self.max_prob_adjustment, min(self.max_prob_adjustment, delta))

    def _downgrade_confidence(self, current: str, levels: int = 1) -> str:
        """Downgrade confidence by N levels. Never upgrades."""
        if current not in self.CONFIDENCE_ORDER:
            return current
        idx = self.CONFIDENCE_ORDER.index(current)
        new_idx = max(0, idx - levels)
        return self.CONFIDENCE_ORDER[new_idx]
