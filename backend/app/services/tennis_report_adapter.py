"""
Tennis Report Adapter — Scenario Report Generator
====================================================
Generates structured scenario reports for one match,
combining dossier, simulation signals, swarm comparison,
and overlay results.
"""

from typing import Dict, Any
from datetime import datetime


def generate_scenario_report(
    dossier_dict: Dict[str, Any],
    signals_dict: Dict[str, Any],
    overlay_dict: Dict[str, Any],
    match_label: str = "",
) -> Dict[str, Any]:
    """
    Generate a structured scenario report.

    Args:
        dossier_dict: MatchDossier.to_dict()
        signals_dict: ScenarioSignals.to_dict()
        overlay_dict: OverlayResult.to_dict()
        match_label: Human-readable match label

    Returns:
        Dict with complete scenario report
    """
    pa = dossier_dict.get("player_a", {}).get("identity", {})
    pb = dossier_dict.get("player_b", {}).get("identity", {})

    player_a_name = pa.get("name", "Player A")
    player_b_name = pb.get("name", "Player B")

    report = {
        "report_type": "nemofish_scenario",
        "generated_at": datetime.now().isoformat(),
        "match": match_label or f"{player_a_name} vs {player_b_name}",

        # Section 1: Dossier Summary
        "dossier_summary": {
            "player_a": {
                "name": player_a_name,
                "ranking": pa.get("ranking"),
                "elo": pa.get("elo_overall"),
                "surface_elo": pa.get("elo_surface"),
                "form": dossier_dict.get("player_a", {}).get("form_profile", {}).get("form_trajectory"),
                "fatigue": dossier_dict.get("player_a", {}).get("physical_profile", {}).get("fatigue_score"),
                "injury": dossier_dict.get("player_a", {}).get("physical_profile", {}).get("injury_flag"),
            },
            "player_b": {
                "name": player_b_name,
                "ranking": pb.get("ranking"),
                "elo": pb.get("elo_overall"),
                "surface_elo": pb.get("elo_surface"),
                "form": dossier_dict.get("player_b", {}).get("form_profile", {}).get("form_trajectory"),
                "fatigue": dossier_dict.get("player_b", {}).get("physical_profile", {}).get("fatigue_score"),
                "injury": dossier_dict.get("player_b", {}).get("physical_profile", {}).get("injury_flag"),
            },
            "h2h": dossier_dict.get("h2h", {}),
            "tournament": dossier_dict.get("tournament", {}),
            "data_quality": dossier_dict.get("data_quality", 0),
        },

        # Section 2: Scenario Signals
        "simulation_signals": {
            "pressure_edge": {
                "player_a": signals_dict.get("pressure_edge_a"),
                "player_b": signals_dict.get("pressure_edge_b"),
            },
            "fatigue_risk": {
                "player_a": signals_dict.get("fatigue_risk_a"),
                "player_b": signals_dict.get("fatigue_risk_b"),
            },
            "injury_risk": {
                "player_a": signals_dict.get("injury_risk_a"),
                "player_b": signals_dict.get("injury_risk_b"),
            },
            "matchup_discomfort": {
                "player_a": signals_dict.get("matchup_discomfort_a"),
                "player_b": signals_dict.get("matchup_discomfort_b"),
            },
            "mental_resilience": {
                "player_a": signals_dict.get("mental_resilience_a"),
                "player_b": signals_dict.get("mental_resilience_b"),
            },
            "volatility_score": signals_dict.get("volatility_score"),
            "simulation_confidence": signals_dict.get("simulation_confidence"),
            "recommendations": signals_dict.get("recommended_adjustments", []),
        },

        # Section 3: Overlay Comparison
        "overlay_comparison": {
            "baseline": {
                "prob_a": overlay_dict.get("baseline_prob_a"),
                "prob_b": overlay_dict.get("baseline_prob_b"),
                "confidence": overlay_dict.get("baseline_confidence"),
                "action": overlay_dict.get("baseline_action"),
            },
            "adjusted": {
                "prob_a": overlay_dict.get("adjusted_prob_a"),
                "prob_b": overlay_dict.get("adjusted_prob_b"),
                "confidence": overlay_dict.get("adjusted_confidence"),
                "action": overlay_dict.get("adjusted_action"),
            },
            "delta": overlay_dict.get("total_prob_delta"),
            "skip_escalated": overlay_dict.get("skip_escalated", False),
            "explanation": overlay_dict.get("explanation", ""),
        },

        # Section 4: Adjustments Audit Trail
        "adjustments": [
            {
                "field": adj.get("field"),
                "delta": adj.get("delta"),
                "reason": adj.get("reason"),
                "source": adj.get("source_signal"),
            }
            for adj in overlay_dict.get("adjustments", [])
        ],
    }

    return report


def format_report_text(report: Dict[str, Any]) -> str:
    """Pretty-print a scenario report to stdout."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  🐠 NemoFish Scenario Report")
    lines.append(f"  {report['match']}")
    lines.append("=" * 60)

    ds = report["dossier_summary"]
    pa = ds["player_a"]
    pb = ds["player_b"]

    lines.append(f"\n📋 DOSSIER (data quality: {ds['data_quality']:.0%})")
    lines.append(f"  {pa['name']:>20}  vs  {pb['name']}")
    lines.append(f"  {'Ranking':>20}: #{pa['ranking']}  vs  #{pb['ranking']}")
    lines.append(f"  {'Elo':>20}: {pa['elo']:.0f}  vs  {pb['elo']:.0f}")
    lines.append(f"  {'Surface Elo':>20}: {pa['surface_elo']:.0f}  vs  {pb['surface_elo']:.0f}")
    lines.append(f"  {'Form':>20}: {pa['form']}  vs  {pb['form']}")
    lines.append(f"  {'Fatigue':>20}: {pa['fatigue']:.0%}  vs  {pb['fatigue']:.0%}")

    h2h = ds.get("h2h", {})
    if h2h.get("total_matches", 0) > 0:
        lines.append(f"  {'H2H':>20}: {h2h['a_wins']}-{h2h['b_wins']}")

    lines.append(f"\n🎯 SIMULATION SIGNALS (confidence: {report['simulation_signals']['simulation_confidence']:.0%})")
    for signal_name, signal_data in report["simulation_signals"].items():
        if isinstance(signal_data, dict):
            pa_val = signal_data.get("player_a", "")
            pb_val = signal_data.get("player_b", "")
            if isinstance(pa_val, (int, float)):
                lines.append(f"  {signal_name:>24}: {pa_val:.0%} vs {pb_val:.0%}")
        elif signal_name == "recommendations":
            for rec in signal_data:
                lines.append(f"  💡 {rec}")

    overlay = report["overlay_comparison"]
    lines.append(f"\n📊 OVERLAY")
    lines.append(f"  Baseline: {overlay['baseline']['prob_a']:.1%} / {overlay['baseline']['prob_b']:.1%} [{overlay['baseline']['confidence']}]")
    lines.append(f"  Adjusted: {overlay['adjusted']['prob_a']:.1%} / {overlay['adjusted']['prob_b']:.1%} [{overlay['adjusted']['confidence']}]")
    lines.append(f"  Delta: {overlay['delta']:+.1%}")
    lines.append(f"  Action: {overlay['baseline']['action']} → {overlay['adjusted']['action']}")
    if overlay["skip_escalated"]:
        lines.append(f"  ⚠️ SKIP ESCALATED: {overlay['explanation']}")
    else:
        lines.append(f"  {overlay['explanation']}")

    if report.get("adjustments"):
        lines.append(f"\n📝 ADJUSTMENTS")
        for adj in report["adjustments"]:
            lines.append(f"  [{adj['source']}] {adj['reason']} (Δ={adj['delta']:+.2%})")

    lines.append("=" * 60)
    return "\n".join(lines)
