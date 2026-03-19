"""
NemoFish Scenario Runner — End-to-End CLI
==========================================
One-match end-to-end runner for the NemoFish Scenario Engine.

Usage:
  python terminal/intelligence/scenario_runner.py \
    --player-a "Jannik Sinner" --player-b "Carlos Alcaraz" \
    --surface Hard --tournament "Miami Open" --level M --round SF

  # Dry run (mock LLM, full pipeline validation):
  python terminal/intelligence/scenario_runner.py \
    --player-a "Jannik Sinner" --player-b "Carlos Alcaraz" \
    --surface Hard --tournament "Miami Open" --level M --round SF --dry-run

Pipeline:
  1. Build MatchDossier from feeds
  2. Run ScenarioSimulation (all 6 scenarios)
  3. Get baseline SwarmConsensus from TennisSwarm
  4. Apply ScenarioOverlay → adjusted consensus
  5. Generate ScenarioReport
  6. Save all artifacts as JSON + print report
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Setup path
TERMINAL_DIR = Path(__file__).parent.parent
ROOT_DIR = TERMINAL_DIR.parent
sys.path.insert(0, str(TERMINAL_DIR))
sys.path.insert(0, str(ROOT_DIR))

from intelligence.player_profile_schema import MatchDossier
from intelligence.match_dossier_builder import MatchDossierBuilder
from intelligence.scenario_simulation import ScenarioSimulation
from intelligence.scenario_overlay import ScenarioOverlay


def run_scenario(args):
    """Run complete scenario engine pipeline for one match."""

    print("=" * 60)
    print("  🐠 NemoFish Scenario Engine v0.1 MVP")
    print("=" * 60)
    print(f"  Match: {args.player_a} vs {args.player_b}")
    print(f"  Tournament: {args.tournament} ({args.level}) | {args.surface} | {args.round}")
    print(f"  Mode: {'DRY RUN (mock LLM)' if args.dry_run else 'LIVE (real LLM)'}")
    print("=" * 60)

    # === Step 1: Initialize data infrastructure ===
    print("\n🔧 Step 1: Loading data infrastructure...")

    elo_engine = None
    sackmann_loader = None

    try:
        from models.tennis_elo import TennisEloEngine
        data_dir = str(TERMINAL_DIR / "data" / "tennis" / "tennis_atp")
        elo_engine = TennisEloEngine(data_dir)
        elo_engine.load_and_process(start_year=2000, end_year=2025)
        print(f"  ✅ Elo Engine: {len(elo_engine.ratings)} players")
    except Exception as e:
        print(f"  ⚠️ Elo Engine unavailable: {e}")

    try:
        from agents.tennis_swarm import JeffSackmannLoader
        sackmann_loader = JeffSackmannLoader(
            str(TERMINAL_DIR / "data" / "tennis" / "tennis_atp")
        )
        mc = getattr(sackmann_loader, 'match_count', len(getattr(sackmann_loader, 'matches', [])))
        print(f"  ✅ Sackmann Loader ready ({mc:,} matches)")
    except Exception as e:
        print(f"  ⚠️ Sackmann Loader unavailable: {e}")

    # === Step 2: Build Match Dossier ===
    print("\n📋 Step 2: Building Match Dossier...")

    from agents.tennis_swarm import MatchContext

    ctx = MatchContext(
        player_a=args.player_a,
        player_b=args.player_b,
        surface=args.surface,
        tourney_name=args.tournament,
        tourney_level=args.level,
        round_name=args.round,
        date=args.date or datetime.now().strftime("%Y-%m-%d"),
        rank_a=args.rank_a,
        rank_b=args.rank_b,
        rank_pts_a=0,
        rank_pts_b=0,
        seed_a=args.rank_a if args.rank_a <= 32 else None,
        seed_b=args.rank_b if args.rank_b <= 32 else None,
        odds_a=args.odds_a,
        odds_b=args.odds_b,
        days_since_last_match_a=args.rest_a,
        days_since_last_match_b=args.rest_b,
        matches_last_14d_a=args.load_a,
        matches_last_14d_b=args.load_b,
        recent_wins_a=7,
        recent_wins_b=7,
        best_of=args.best_of,
        indoor=args.indoor,
        altitude_m=0,
    )

    builder = MatchDossierBuilder(
        elo_engine=elo_engine,
        sackmann_loader=sackmann_loader,
    )
    dossier = builder.build(ctx)
    print(f"  ✅ Dossier built | Data quality: {dossier.data_quality:.0%}")

    # === Step 3: Run Scenario Simulation ===
    print("\n🎯 Step 3: Running Scenario Simulation...")

    sim = ScenarioSimulation()
    if args.dry_run:
        signals = sim.simulate_dry_run(dossier.to_json())
        print("  ✅ Dry run signals generated (mock)")
    else:
        signals = sim.simulate(dossier.to_json())
        print(f"  ✅ Simulation complete | Confidence: {signals.simulation_confidence:.0%}")

    # === Step 4: Get Baseline Swarm Prediction ===
    print("\n🐝 Step 4: Getting Baseline Swarm Prediction...")

    try:
        from agents.tennis_swarm import TennisSwarm
        swarm = TennisSwarm(elo_engine)
        if sackmann_loader:
            swarm.sackmann = sackmann_loader
        baseline = swarm.predict(ctx)
        print(f"  ✅ Baseline: {baseline.prob_a:.1%}/{baseline.prob_b:.1%} [{baseline.confidence}] → {baseline.recommended_action}")
    except Exception as e:
        print(f"  ⚠️ Swarm unavailable: {e}")
        # Fallback: create a mock consensus
        from agents.tennis_swarm import SwarmConsensus
        baseline = SwarmConsensus(
            player_a=args.player_a,
            player_b=args.player_b,
            surface=args.surface,
            prob_a=0.55,
            prob_b=0.45,
            confidence="MEDIUM",
            edge_vs_market=None,
            recommended_action="SKIP",
            kelly_bet_size=0.0,
            agent_votes=[],
            reasoning_summary="Mock baseline (swarm unavailable)",
            data_quality_score=0.3,
        )

    # === Step 5: Apply Scenario Overlay ===
    print("\n📊 Step 5: Applying Scenario Overlay...")

    overlay = ScenarioOverlay(max_prob_adjustment=0.03)
    overlay_result = overlay.apply(
        signals=signals,
        baseline_prob_a=baseline.prob_a,
        baseline_prob_b=baseline.prob_b,
        baseline_confidence=baseline.confidence,
        baseline_action=baseline.recommended_action,
        player_a=args.player_a,
        player_b=args.player_b,
    )

    print(f"  ✅ Overlay applied")
    print(f"     Baseline: {overlay_result.baseline_prob_a:.1%}/{overlay_result.baseline_prob_b:.1%}")
    print(f"     Adjusted: {overlay_result.adjusted_prob_a:.1%}/{overlay_result.adjusted_prob_b:.1%}")
    print(f"     Delta: {overlay_result.adjusted_prob_a - overlay_result.baseline_prob_a:+.2%}")

    # === Step 6: Generate Report ===
    print("\n📝 Step 6: Generating Scenario Report...")

    # Import directly to avoid Flask dependency in backend/app/__init__.py
    import importlib.util
    _report_spec = importlib.util.spec_from_file_location(
        "tennis_report_adapter",
        str(ROOT_DIR / "backend" / "app" / "services" / "tennis_report_adapter.py"),
    )
    _report_mod = importlib.util.module_from_spec(_report_spec)
    _report_spec.loader.exec_module(_report_mod)
    generate_scenario_report = _report_mod.generate_scenario_report
    format_report_text = _report_mod.format_report_text

    report = generate_scenario_report(
        dossier_dict=dossier.to_dict(),
        signals_dict=signals.to_dict(),
        overlay_dict=overlay_result.to_dict(),
        match_label=f"{args.player_a} vs {args.player_b} — {args.tournament} {args.round}",
    )

    # Print report
    print()
    print(format_report_text(report))

    # === Step 7: Save Artifacts ===
    output_dir = TERMINAL_DIR / "output" / "scenarios"
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"{args.player_a.replace(' ', '_')}_vs_{args.player_b.replace(' ', '_')}_{ts}"

    # Save all artifacts
    artifacts = {
        "dossier": dossier.to_dict(),
        "signals": signals.to_dict(),
        "overlay": overlay_result.to_dict(),
        "report": report,
    }

    for name, data in artifacts.items():
        path = output_dir / f"{slug}_{name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"  💾 Saved: {path.name}")

    print(f"\n✅ Scenario complete. Artifacts saved to: {output_dir}")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="🐠 NemoFish Scenario Engine — Single Match Runner",
    )
    parser.add_argument("--player-a", required=True, help="Player A name")
    parser.add_argument("--player-b", required=True, help="Player B name")
    parser.add_argument("--surface", required=True, choices=["Hard", "Clay", "Grass"])
    parser.add_argument("--tournament", required=True, help="Tournament name")
    parser.add_argument("--level", default="M", choices=["G", "M", "A", "B", "F"])
    parser.add_argument("--round", default="QF", help="Round (F/SF/QF/R16/R32/R64)")
    parser.add_argument("--date", default=None, help="Match date YYYY-MM-DD")
    parser.add_argument("--rank-a", type=int, default=5, help="Player A ranking")
    parser.add_argument("--rank-b", type=int, default=5, help="Player B ranking")
    parser.add_argument("--odds-a", type=float, default=None, help="Player A decimal odds")
    parser.add_argument("--odds-b", type=float, default=None, help="Player B decimal odds")
    parser.add_argument("--rest-a", type=int, default=3, help="Days since last match for A")
    parser.add_argument("--rest-b", type=int, default=3, help="Days since last match for B")
    parser.add_argument("--load-a", type=int, default=4, help="Matches in last 14d for A")
    parser.add_argument("--load-b", type=int, default=4, help="Matches in last 14d for B")
    parser.add_argument("--best-of", type=int, default=3, choices=[3, 5])
    parser.add_argument("--indoor", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use mock LLM responses (no API call)")

    args = parser.parse_args()
    run_scenario(args)


if __name__ == "__main__":
    main()
