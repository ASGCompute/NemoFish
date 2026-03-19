"""
NemoFish Slate Runner — Batch Scenario Engine
===============================================
Auto-discovers tomorrow's ATP/WTA matches and runs the full
NemoFish scenario pipeline for each one.

Output:
  terminal/output/scenarios/slate_YYYYMMDD/
    ├── slate_summary.json          ← master index
    ├── <slug>_dossier.json
    ├── <slug>_signals.json
    ├── <slug>_overlay.json
    └── <slug>_report.json

Usage:
  # From project root:
  python3 terminal/intelligence/slate_runner.py               # Tomorrow (real LLM)
  python3 terminal/intelligence/slate_runner.py --dry-run     # Mock LLM
  python3 terminal/intelligence/slate_runner.py --date 2026-03-18
"""

import json
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

# Setup path
TERMINAL_DIR = Path(__file__).parent.parent
ROOT_DIR = TERMINAL_DIR.parent
sys.path.insert(0, str(TERMINAL_DIR))
sys.path.insert(0, str(ROOT_DIR))

# Load .env
_ENV_PATH = ROOT_DIR / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from feeds.api_tennis import ApiTennisClient
from intelligence.player_profile_schema import MatchDossier
from intelligence.match_dossier_builder import MatchDossierBuilder
from intelligence.scenario_simulation import ScenarioSimulation
from intelligence.scenario_overlay import ScenarioOverlay


# ── Classification thresholds ──────────────────────────────
MIN_DQ_FOR_PAPER = 0.35
MIN_EDGE_FOR_LIVE = 0.03


def _load_infra():
    """Load Elo engine + Sackmann loader (cached)."""
    elo_engine = None
    sackmann_loader = None

    try:
        from models.tennis_elo import TennisEloEngine
        data_dir = str(TERMINAL_DIR / "data" / "tennis" / "tennis_atp")
        elo_engine = TennisEloEngine(data_dir)
        elo_engine.load_and_process(start_year=2000, end_year=2025)
        print(f"  ✅ Elo Engine: {len(elo_engine.ratings)} players")
    except Exception as e:
        print(f"  ⚠️  Elo Engine unavailable: {e}")

    try:
        from agents.tennis_swarm import JeffSackmannLoader
        sackmann_loader = JeffSackmannLoader(
            str(TERMINAL_DIR / "data" / "tennis" / "tennis_atp")
        )
        mc = getattr(sackmann_loader, 'match_count', len(getattr(sackmann_loader, 'matches', [])))
        print(f"  ✅ Sackmann Loader ready ({mc:,} matches)")
    except Exception as e:
        print(f"  ⚠️  Sackmann Loader unavailable: {e}")

    return elo_engine, sackmann_loader


def _fetch_odds_batch(tennis_api: ApiTennisClient, fixtures) -> Dict[str, Any]:
    """Fetch odds for a batch of fixtures. Returns {event_key: odds_dict}."""
    odds_map = {}
    for fix in fixtures:
        try:
            odds = tennis_api.get_odds(fix.event_key)
            if odds:
                from dataclasses import asdict
                odds_map[fix.event_key] = asdict(odds)
        except Exception:
            pass
    return odds_map


def _classify_match(
    dossier_dq: float,
    has_odds: bool,
    has_unresolved: bool,
    overlay_action: str,
    edge: Optional[float],
) -> str:
    """Classify a match into execution tiers."""
    if has_unresolved:
        return "PREDICTION_ONLY"
    if not has_odds:
        return "PREDICTION_ONLY"
    if dossier_dq < MIN_DQ_FOR_PAPER:
        return "PREDICTION_ONLY"
    if overlay_action == "SKIP":
        return "PAPER_CANDIDATE"
    if edge is not None and abs(edge) >= MIN_EDGE_FOR_LIVE:
        return "LIVE_CANDIDATE"
    return "PAPER_CANDIDATE"


def _priority_score(
    classification: str,
    data_quality: float,
    has_odds: bool,
    confidence: str,
    edge: Optional[float],
) -> float:
    """Compute priority score for sorting (higher = shows first)."""
    score = 0.0
    # Tier weight
    tier_w = {"LIVE_CANDIDATE": 100, "PAPER_CANDIDATE": 50, "PREDICTION_ONLY": 10}
    score += tier_w.get(classification, 0)
    # Data quality
    score += data_quality * 20
    # Has odds
    if has_odds:
        score += 15
    # Confidence
    conf_w = {"ELITE": 20, "HIGH": 15, "MEDIUM": 10, "LOW": 5}
    score += conf_w.get(confidence, 0)
    # Edge
    if edge is not None:
        score += min(20, abs(edge) * 200)
    return round(score, 1)


def run_slate(
    target_date: str = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Run full scenario engine on all tomorrow's ATP/WTA matches.

    Args:
        target_date: YYYY-MM-DD (defaults to tomorrow)
        dry_run: Use mock LLM if True

    Returns:
        Slate summary dict with all matches and artifacts.
    """
    if not target_date:
        target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    print("=" * 60)
    print("  🐠 NemoFish Slate Runner")
    print(f"  Date: {target_date}")
    print(f"  Mode: {'DRY RUN (mock LLM)' if dry_run else 'LIVE (real LLM)'}")
    print("=" * 60)

    # ── Step 1: Load infrastructure ──
    print("\n🔧 Loading infrastructure...")
    elo_engine, sackmann_loader = _load_infra()

    # ── Step 2: Fetch fixtures ──
    print(f"\n📡 Fetching fixtures for {target_date}...")
    tennis_api = ApiTennisClient()

    if not tennis_api.api_key:
        print("  ❌ API_TENNIS_KEY not configured")
        return {"error": "API_TENNIS_KEY not set", "matches": [], "date": target_date}

    try:
        fixtures = tennis_api.get_fixtures(
            date_start=target_date, date_stop=target_date
        )
    except Exception as e:
        print(f"  ❌ Fixture fetch failed: {e}")
        return {"error": str(e), "matches": [], "date": target_date}

    # Filter ATP/WTA singles
    singles = [
        f for f in fixtures
        if any(t in f.event_type.lower() for t in ["atp singles", "wta singles"])
    ]
    print(f"  Total fixtures: {len(fixtures)} | ATP/WTA Singles: {len(singles)}")

    if not singles:
        print("  ⚠️  No ATP/WTA singles matches found for this date")
        return {"matches": [], "date": target_date, "count": 0}

    for f in singles[:10]:
        print(f"  📋 {f.player_a} vs {f.player_b} | {f.tournament} {f.round_name}")
    if len(singles) > 10:
        print(f"  ... and {len(singles) - 10} more")

    # ── Step 3: Fetch odds batch ──
    print(f"\n💰 Fetching odds for {len(singles)} matches...")
    odds_map = _fetch_odds_batch(tennis_api, singles)
    print(f"  Got odds for {len(odds_map)}/{len(singles)} matches")

    # ── Step 4: Prepare output directory ──
    slate_dir = TERMINAL_DIR / "output" / "scenarios" / f"slate_{target_date.replace('-', '')}"
    slate_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 5: Process each match ──
    from agents.tennis_swarm import MatchContext, TennisSwarm, SwarmConsensus

    builder = MatchDossierBuilder(elo_engine=elo_engine, sackmann_loader=sackmann_loader)
    sim = ScenarioSimulation()
    overlay_engine = ScenarioOverlay(max_prob_adjustment=0.03)

    swarm = None
    try:
        swarm = TennisSwarm(elo_engine)
        if sackmann_loader:
            swarm.sackmann = sackmann_loader
        print("  ✅ Swarm loaded")
    except Exception as e:
        print(f"  ⚠️  Swarm unavailable: {e}")

    # Import report generator
    try:
        import importlib.util
        _report_spec = importlib.util.spec_from_file_location(
            "tennis_report_adapter",
            str(ROOT_DIR / "backend" / "app" / "services" / "tennis_report_adapter.py"),
        )
        _report_mod = importlib.util.module_from_spec(_report_spec)
        _report_spec.loader.exec_module(_report_mod)
        generate_report = _report_mod.generate_scenario_report
    except Exception as e:
        print(f"  ⚠️  Report generator unavailable: {e}")
        generate_report = None

    match_results = []
    errors = []

    for i, fix in enumerate(singles):
        slug = f"{fix.player_a.replace(' ', '_')}_vs_{fix.player_b.replace(' ', '_')}"
        slug = slug.replace(".", "").replace("'", "")
        print(f"\n{'─' * 50}")
        print(f"  [{i+1}/{len(singles)}] {fix.player_a} vs {fix.player_b}")
        print(f"  {fix.tournament} {fix.round_name} | {fix.event_type}")

        try:
            # Determine surface
            tournament_lower = fix.tournament.lower()
            if "clay" in tournament_lower or "roland" in tournament_lower or "rome" in tournament_lower:
                surface = "Clay"
            elif "grass" in tournament_lower or "wimbledon" in tournament_lower:
                surface = "Grass"
            else:
                surface = "Hard"

            # Determine level
            if any(k in tournament_lower for k in ["grand slam", "australian", "french", "wimbledon", "us open"]):
                level = "G"
            elif any(k in tournament_lower for k in ["masters", "miami", "indian wells", "madrid", "rome", "montreal", "shanghai"]):
                level = "M"
            else:
                level = "B"

            # Extract odds
            match_odds = odds_map.get(fix.event_key, {})
            odds_a = match_odds.get("best_home") or match_odds.get("avg_home")
            odds_b = match_odds.get("best_away") or match_odds.get("avg_away")
            has_odds = bool(odds_a and odds_b and odds_a > 1 and odds_b > 1)

            # Build MatchContext
            ctx = MatchContext(
                player_a=fix.player_a,
                player_b=fix.player_b,
                surface=surface,
                tourney_name=fix.tournament,
                tourney_level=level,
                round_name=fix.round_name or "R32",
                date=target_date,
                rank_a=5,  # Will be enriched by Elo if available
                rank_b=5,
                rank_pts_a=0,
                rank_pts_b=0,
                odds_a=odds_a if has_odds else None,
                odds_b=odds_b if has_odds else None,
            )

            # Build dossier
            dossier = builder.build(ctx)
            dq = dossier.data_quality
            print(f"    Dossier: DQ={dq:.0%}")

            # Run simulation
            if dry_run:
                signals = sim.simulate_dry_run(dossier.to_json())
            else:
                signals = sim.simulate(dossier.to_json())

            # Get baseline from swarm
            if swarm:
                try:
                    baseline = swarm.predict(ctx)
                except Exception:
                    baseline = SwarmConsensus(
                        player_a=fix.player_a, player_b=fix.player_b,
                        surface=surface, prob_a=0.5, prob_b=0.5,
                        confidence="MEDIUM", edge_vs_market=None,
                        recommended_action="SKIP", kelly_bet_size=0.0,
                        agent_votes=[], reasoning_summary="Swarm error fallback",
                        data_quality_score=0.3,
                    )
            else:
                baseline = SwarmConsensus(
                    player_a=fix.player_a, player_b=fix.player_b,
                    surface=surface, prob_a=0.5, prob_b=0.5,
                    confidence="MEDIUM", edge_vs_market=None,
                    recommended_action="SKIP", kelly_bet_size=0.0,
                    agent_votes=[], reasoning_summary="Swarm unavailable",
                    data_quality_score=0.3,
                )

            # Apply overlay
            overlay_result = overlay_engine.apply(
                signals=signals,
                baseline_prob_a=baseline.prob_a,
                baseline_prob_b=baseline.prob_b,
                baseline_confidence=baseline.confidence,
                baseline_action=baseline.recommended_action,
                player_a=fix.player_a,
                player_b=fix.player_b,
            )

            # Generate report
            report = {}
            match_label = f"{fix.player_a} vs {fix.player_b} — {fix.tournament} {fix.round_name}"
            if generate_report:
                try:
                    report = generate_report(
                        dossier_dict=dossier.to_dict(),
                        signals_dict=signals.to_dict(),
                        overlay_dict=overlay_result.to_dict(),
                        match_label=match_label,
                    )
                except Exception as e:
                    report = {"error": str(e), "match_label": match_label}

            # Classify
            edge = None
            if baseline.edge_vs_market is not None:
                edge = baseline.edge_vs_market
            elif has_odds and odds_a:
                implied = 1.0 / odds_a
                edge = overlay_result.adjusted_prob_a - implied

            classification = _classify_match(
                dossier_dq=dq,
                has_odds=has_odds,
                has_unresolved=False,
                overlay_action=overlay_result.adjusted_action,
                edge=edge,
            )

            priority = _priority_score(
                classification=classification,
                data_quality=dq,
                has_odds=has_odds,
                confidence=overlay_result.adjusted_confidence,
                edge=edge,
            )

            # Save artifacts
            artifacts = {
                "dossier": dossier.to_dict(),
                "signals": signals.to_dict(),
                "overlay": overlay_result.to_dict(),
                "report": report,
            }
            for name, data in artifacts.items():
                path = slate_dir / f"{slug}_{name}.json"
                path.write_text(json.dumps(data, indent=2, default=str))

            # Build match summary
            match_entry = {
                "id": slug,
                "label": match_label,
                "player_a": fix.player_a,
                "player_b": fix.player_b,
                "tournament": fix.tournament,
                "round": fix.round_name,
                "surface": surface,
                "level": level,
                "event_type": fix.event_type,
                "time": fix.time,
                "event_key": fix.event_key,
                "baseline_prob_a": round(baseline.prob_a, 4),
                "baseline_prob_b": round(baseline.prob_b, 4),
                "adjusted_prob_a": round(overlay_result.adjusted_prob_a, 4),
                "adjusted_prob_b": round(overlay_result.adjusted_prob_b, 4),
                "delta": round(overlay_result.adjusted_prob_a - baseline.prob_a, 4),
                "baseline_confidence": baseline.confidence,
                "adjusted_confidence": overlay_result.adjusted_confidence,
                "baseline_action": baseline.recommended_action,
                "adjusted_action": overlay_result.adjusted_action,
                "edge": round(edge, 4) if edge is not None else None,
                "odds_a": odds_a,
                "odds_b": odds_b,
                "has_odds": has_odds,
                "data_quality": dq,
                "classification": classification,
                "priority": priority,
                "skip_escalated": overlay_result.skip_escalated,
                "skip_reason": overlay_result.skip_reason,
                "explanation": overlay_result.explanation,
            }
            match_results.append(match_entry)

            icon = {"LIVE_CANDIDATE": "🟢", "PAPER_CANDIDATE": "🟡", "PREDICTION_ONLY": "⚪"}
            print(f"    {icon.get(classification, '❓')} {classification} | "
                  f"P={overlay_result.adjusted_prob_a:.0%}/{overlay_result.adjusted_prob_b:.0%} | "
                  f"Δ={overlay_result.adjusted_prob_a - baseline.prob_a:+.1%} | "
                  f"DQ={dq:.0%} | Priority={priority}")

        except Exception as e:
            print(f"    ❌ Error: {e}")
            traceback.print_exc()
            errors.append({"match": f"{fix.player_a} vs {fix.player_b}", "error": str(e)})
            continue

    # ── Step 6: Save slate summary ──
    # Sort by priority (highest first)
    match_results.sort(key=lambda m: m["priority"], reverse=True)

    slate_summary = {
        "date": target_date,
        "generated_at": datetime.now().isoformat(),
        "mode": "dry_run" if dry_run else "live",
        "total_fixtures": len(fixtures),
        "atp_wta_singles": len(singles),
        "processed": len(match_results),
        "errors": len(errors),
        "with_odds": sum(1 for m in match_results if m["has_odds"]),
        "live_candidates": sum(1 for m in match_results if m["classification"] == "LIVE_CANDIDATE"),
        "paper_candidates": sum(1 for m in match_results if m["classification"] == "PAPER_CANDIDATE"),
        "prediction_only": sum(1 for m in match_results if m["classification"] == "PREDICTION_ONLY"),
        "matches": match_results,
        "error_details": errors,
    }

    summary_path = slate_dir / "slate_summary.json"
    summary_path.write_text(json.dumps(slate_summary, indent=2, default=str))

    # Also save as latest
    latest_path = TERMINAL_DIR / "output" / "scenarios" / "latest_slate.json"
    latest_path.write_text(json.dumps(slate_summary, indent=2, default=str))

    print(f"\n{'═' * 60}")
    print(f"  📊 SLATE SUMMARY — {target_date}")
    print(f"  {'─' * 56}")
    print(f"  Processed:  {len(match_results)}/{len(singles)} matches")
    print(f"  With odds:  {slate_summary['with_odds']}")
    print(f"  🟢 LIVE:    {slate_summary['live_candidates']}")
    print(f"  🟡 PAPER:   {slate_summary['paper_candidates']}")
    print(f"  ⚪ PREDICT: {slate_summary['prediction_only']}")
    print(f"  ❌ Errors:  {len(errors)}")
    print(f"\n  Artifacts:  {slate_dir}")
    print(f"{'═' * 60}")

    return slate_summary


# ── CLI ────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="🐠 NemoFish Slate Runner")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: tomorrow)")
    parser.add_argument("--dry-run", action="store_true", help="Use mock LLM responses")
    args = parser.parse_args()

    run_slate(target_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
