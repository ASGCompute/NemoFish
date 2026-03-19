"""
Tennis Scenario Simulation — LLM-Driven Match Scenario Engine
===============================================================
Runs focused tennis scenario prompts against an LLM and returns
structured signals. NOT a free-text narrative — strict JSON output.

Scenario modes:
  1. pressure     — who handles pressure better
  2. comeback     — comeback/resilience in adversity
  3. long_rally   — baseline grinding, physical endurance
  4. serve_dominant — serve-and-volley, ace-heavy
  5. injury_fatigue — physical condition, travel load
  6. momentum_swing — momentum shifts, mental fragility

Falls back to neutral signals if LLM unavailable.
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class ScenarioSignals:
    """
    Structured output from scenario simulation.
    All values 0.0-1.0 unless otherwise noted.
    """
    # Edge assessments (0=no edge, 1=total edge for that player)
    pressure_edge_a: float = 0.5
    pressure_edge_b: float = 0.5

    # Risk factors (0=no risk, 1=critical risk)
    fatigue_risk_a: float = 0.0
    fatigue_risk_b: float = 0.0
    injury_risk_a: float = 0.0
    injury_risk_b: float = 0.0

    # Match dynamics
    volatility_score: float = 0.5       # 0=predictable, 1=chaotic
    matchup_discomfort_a: float = 0.0   # how much B's style troubles A
    matchup_discomfort_b: float = 0.0   # how much A's style troubles B

    # Mental factors
    mental_resilience_a: float = 0.5
    mental_resilience_b: float = 0.5

    # Meta-signals
    narrative_confidence: float = 0.5   # how confident the simulation is
    simulation_confidence: float = 0.5  # overall confidence in signals

    # Recommendations
    recommended_adjustments: List[str] = field(default_factory=list)

    # Per-scenario breakdown (for audit)
    scenario_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def neutral(cls) -> 'ScenarioSignals':
        """Return completely neutral signals (no adjustment)."""
        return cls(simulation_confidence=0.0)


# === Scenario Prompt Templates ===

SCENARIO_SYSTEM_PROMPT = """You are NemoFish Scenario Engine — a tennis match analysis AI.
You analyze STRUCTURED DATA about two tennis players and produce STRUCTURED JSON signals.

RULES:
1. Output ONLY valid JSON. No markdown, no explanation outside JSON.
2. All numeric values must be between 0.0 and 1.0.
3. Be conservative — don't hallucinate psychology you can't infer from data.
4. If data is insufficient, set values close to 0.5 (neutral) and lower confidence.
5. Never output more than 3 recommended_adjustments.
6. Think like a professional tennis analyst, not a storyteller."""


SCENARIO_TEMPLATES = {
    "pressure": {
        "focus": "Pressure handling and mental edge in crucial moments",
        "prompt": """Analyze this match for PRESSURE scenarios.

MATCH DOSSIER:
{dossier_json}

Focus on:
- Who handles pressure better in big points/sets?
- Tiebreak tendencies, deciding set records
- Tournament importance and round pressure
- Ranking/seed expectations

Output JSON:
{{
  "pressure_edge_a": <0-1, higher = A handles pressure better>,
  "pressure_edge_b": <0-1, higher = B handles pressure better>,
  "mental_resilience_a": <0-1>,
  "mental_resilience_b": <0-1>,
  "confidence": <0-1, how confident you are in this assessment>,
  "key_factor": "<one-line summary>"
}}""",
    },

    "comeback": {
        "focus": "Comeback ability and resilience",
        "prompt": """Analyze this match for COMEBACK scenarios.

MATCH DOSSIER:
{dossier_json}

Focus on:
- Who is more likely to come back from a set down?
- Recent form trajectory (rising vs declining)
- Physical endurance for long matches
- Mental toughness indicators

Output JSON:
{{
  "mental_resilience_a": <0-1>,
  "mental_resilience_b": <0-1>,
  "volatility_score": <0-1, how likely the match goes to deciding set>,
  "confidence": <0-1>,
  "key_factor": "<one-line summary>"
}}""",
    },

    "long_rally": {
        "focus": "Baseline grinding and physical endurance",
        "prompt": """Analyze this match for LONG RALLY / BASELINE scenarios.

MATCH DOSSIER:
{dossier_json}

Focus on:
- Who wins in extended baseline rallies?
- Return game quality vs serve dominance
- Physical fitness and fatigue levels
- Surface suitability for grinding

Output JSON:
{{
  "matchup_discomfort_a": <0-1, how much B's baseline game troubles A>,
  "matchup_discomfort_b": <0-1, how much A's baseline game troubles B>,
  "fatigue_risk_a": <0-1>,
  "fatigue_risk_b": <0-1>,
  "confidence": <0-1>,
  "key_factor": "<one-line summary>"
}}""",
    },

    "serve_dominant": {
        "focus": "Serve-dominated match dynamics",
        "prompt": """Analyze this match for SERVE DOMINANT scenarios.

MATCH DOSSIER:
{dossier_json}

Focus on:
- Whose serve is more dominant? Ace rates, first serve %
- Return game quality — who can break serve?
- Tiebreak likelihood (both holding easily)
- Surface effect on serve advantage

Output JSON:
{{
  "pressure_edge_a": <0-1, who wins in serve-dominated tight sets>,
  "pressure_edge_b": <0-1>,
  "volatility_score": <0-1, high = likely tiebreaks>,
  "confidence": <0-1>,
  "key_factor": "<one-line summary>"
}}""",
    },

    "injury_fatigue": {
        "focus": "Injury concerns and physical fatigue",
        "prompt": """Analyze this match for INJURY/FATIGUE scenarios.

MATCH DOSSIER:
{dossier_json}

Focus on:
- Any injury flags or physical concerns
- Days rest, match load in last 14 days
- Travel schedule and fatigue
- Best-of-3 vs best-of-5 endurance impact

Output JSON:
{{
  "fatigue_risk_a": <0-1>,
  "fatigue_risk_b": <0-1>,
  "injury_risk_a": <0-1>,
  "injury_risk_b": <0-1>,
  "volatility_score": <0-1, higher if injury could cause collapse>,
  "confidence": <0-1>,
  "key_factor": "<one-line summary>"
}}""",
    },

    "momentum_swing": {
        "focus": "Momentum shifts and mental fragility",
        "prompt": """Analyze this match for MOMENTUM SWING scenarios.

MATCH DOSSIER:
{dossier_json}

Focus on:
- Who is more prone to momentum swings?
- Current form trajectory (hot streak vs cold)
- Mental resilience when things go wrong
- Historical pattern of collapses or comebacks

Output JSON:
{{
  "mental_resilience_a": <0-1>,
  "mental_resilience_b": <0-1>,
  "volatility_score": <0-1>,
  "matchup_discomfort_a": <0-1>,
  "matchup_discomfort_b": <0-1>,
  "confidence": <0-1>,
  "key_factor": "<one-line summary>"
}}""",
    },
}


class ScenarioSimulation:
    """
    Runs tennis scenario simulations via LLM.
    Falls back to neutral signals if LLM unavailable.
    """

    def __init__(self, llm_client=None, model: str = None):
        self.client = llm_client
        self.model = model
        self._init_client()

    def _init_client(self):
        """Initialize LLM client from environment (same config as MiroFish)."""
        if self.client:
            return

        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent.parent.parent / ".env")
        except ImportError:
            pass

        api_key = os.getenv("LLM_API_KEY")
        base_url = os.getenv("LLM_BASE_URL")
        self.model = self.model or os.getenv("LLM_MODEL_NAME", "deepseek-ai/deepseek-v3.2")

        if api_key and base_url:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=api_key, base_url=base_url)
            except ImportError:
                self.client = None

    def simulate(
        self,
        dossier_json: str,
        scenarios: Optional[List[str]] = None,
    ) -> ScenarioSignals:
        """
        Run all scenario simulations and merge into unified signals.

        Args:
            dossier_json: JSON string of the MatchDossier
            scenarios: List of scenario names to run (default: all)

        Returns:
            ScenarioSignals with merged results from all scenarios
        """
        if scenarios is None:
            scenarios = list(SCENARIO_TEMPLATES.keys())

        if not self.client:
            return ScenarioSignals.neutral()

        # Run each scenario
        results = {}
        for scenario_name in scenarios:
            if scenario_name not in SCENARIO_TEMPLATES:
                continue
            result = self._run_scenario(scenario_name, dossier_json)
            results[scenario_name] = result

        # Merge scenario results into unified signals
        return self._merge_signals(results)

    def simulate_dry_run(self, dossier_json: str) -> ScenarioSignals:
        """
        Dry run — return plausible mock signals without LLM call.
        Used for testing the full pipeline.
        """
        return ScenarioSignals(
            pressure_edge_a=0.55,
            pressure_edge_b=0.45,
            fatigue_risk_a=0.2,
            fatigue_risk_b=0.15,
            injury_risk_a=0.05,
            injury_risk_b=0.0,
            volatility_score=0.4,
            matchup_discomfort_a=0.3,
            matchup_discomfort_b=0.35,
            mental_resilience_a=0.65,
            mental_resilience_b=0.55,
            narrative_confidence=0.6,
            simulation_confidence=0.65,
            recommended_adjustments=[
                "Slight pressure edge to player A in tiebreaks",
                "Monitor fatigue for both — moderate match load",
            ],
            scenario_details={"mode": "dry_run"},
        )

    def _run_scenario(
        self, scenario_name: str, dossier_json: str
    ) -> Dict[str, Any]:
        """Run a single scenario prompt against the LLM."""
        template = SCENARIO_TEMPLATES[scenario_name]

        prompt = template["prompt"].format(dossier_json=dossier_json)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SCENARIO_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.2,
            )

            text = response.choices[0].message.content.strip()

            # Parse JSON — handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            data = json.loads(text)

            # Clamp all numeric values to [0, 1]
            for key, val in data.items():
                if isinstance(val, (int, float)) and key != "key_factor":
                    data[key] = max(0.0, min(1.0, float(val)))

            return data

        except Exception as e:
            return {"error": str(e), "confidence": 0.0}

    def _merge_signals(
        self, results: Dict[str, Dict[str, Any]]
    ) -> ScenarioSignals:
        """Merge results from multiple scenarios into unified signals."""

        # Collect weighted values across scenarios
        def _avg(key: str, default: float = 0.5) -> float:
            values = []
            weights = []
            for name, result in results.items():
                if key in result and "error" not in result:
                    values.append(result[key])
                    weights.append(result.get("confidence", 0.5))
            if not values:
                return default
            # Weighted average by scenario confidence
            total_w = sum(weights)
            if total_w == 0:
                return sum(values) / len(values)
            return sum(v * w for v, w in zip(values, weights)) / total_w

        # Build merged signals
        signals = ScenarioSignals(
            pressure_edge_a=round(_avg("pressure_edge_a"), 3),
            pressure_edge_b=round(_avg("pressure_edge_b"), 3),
            fatigue_risk_a=round(_avg("fatigue_risk_a", 0.0), 3),
            fatigue_risk_b=round(_avg("fatigue_risk_b", 0.0), 3),
            injury_risk_a=round(_avg("injury_risk_a", 0.0), 3),
            injury_risk_b=round(_avg("injury_risk_b", 0.0), 3),
            volatility_score=round(_avg("volatility_score"), 3),
            matchup_discomfort_a=round(_avg("matchup_discomfort_a", 0.0), 3),
            matchup_discomfort_b=round(_avg("matchup_discomfort_b", 0.0), 3),
            mental_resilience_a=round(_avg("mental_resilience_a"), 3),
            mental_resilience_b=round(_avg("mental_resilience_b"), 3),
        )

        # Overall confidence = average of scenario confidences
        confidences = [
            r.get("confidence", 0.0)
            for r in results.values()
            if "error" not in r
        ]
        signals.simulation_confidence = round(
            sum(confidences) / max(1, len(confidences)), 3
        )
        signals.narrative_confidence = signals.simulation_confidence

        # Collect key factors as recommendations
        adjustments = []
        for name, result in results.items():
            kf = result.get("key_factor", "")
            if kf and "error" not in result:
                adjustments.append(f"[{name}] {kf}")
        signals.recommended_adjustments = adjustments[:3]  # Max 3

        # Store per-scenario details for audit
        signals.scenario_details = results

        return signals
