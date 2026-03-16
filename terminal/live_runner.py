#!/usr/bin/env python3
"""
NemoFish Live Runner — End-to-End Pipeline
============================================
Connects REAL data sources → Swarm prediction → Polymarket execution.

Pipeline:
  1. Fetch today's fixtures from api-tennis.com
  2. Enrich with Sportradar rankings + competitor data
  3. Search Polymarket for matching tennis markets
  4. Run 5-agent swarm on each viable match
  5. Execute bets (PAPER or LIVE) on Polymarket

Usage:
  python3 terminal/live_runner.py              # Full pipeline (PAPER mode)
  python3 terminal/live_runner.py --live       # LIVE mode (real $$$)
  python3 terminal/live_runner.py --scan-only  # Just scan, don't bet
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

# Path setup
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from feeds.api_tennis import ApiTennisClient
from feeds.sportradar_tennis import SportradarTennisClient
from feeds.polymarket import PolymarketClient
from feeds.name_resolver import TennisNameResolver
from agents.tennis_swarm import TennisSwarm, MatchContext
from execution.polymarket_live import PolymarketTrader
from execution.risk_manager import RiskManager
from execution.pnl_tracker import PnLTracker
from strategies import (
    ATPConfidenceStrategy, ValueConfirmationStrategy, 
    EdgeThresholdStrategy, KellyStrategy
)
from strategies.skemp_value import (
    SkempValueOnlyStrategy, SkempPredictedWinValueStrategy
)
from strategies.strategy_base import MatchInput

# Strategy registry — maps CLI names to strategy instances
STRATEGY_REGISTRY = {
    'atp_confidence_5': ATPConfidenceStrategy(top_pct=0.05),
    'atp_confidence_10': ATPConfidenceStrategy(top_pct=0.10),
    'value_confirmation': ValueConfirmationStrategy(),
    'edge_3pct': EdgeThresholdStrategy(min_edge=0.03),
    'edge_5pct': EdgeThresholdStrategy(min_edge=0.05),
    'kelly_quarter': KellyStrategy(fraction=0.25),
    'skemp_value': SkempValueOnlyStrategy(),
    'skemp_predict_value': SkempPredictedWinValueStrategy(),
}

# Default strategy set — only proven profitable strategies
DEFAULT_STRATEGIES = ['atp_confidence_5']


# === Config ===
MIN_EDGE_THRESHOLD = 0.03       # 3% minimum edge to place bet
MAX_BET_PER_MATCH = 50.0        # Max $50 per position
MAX_DAILY_EXPOSURE = 200.0      # Max $200 total daily
CONFIDENCE_MULTIPLIER = {
    "ELITE": 1.0,
    "HIGH": 0.75,
    "MEDIUM": 0.50,
    "LOW": 0.25,
}


def banner():
    print("═" * 65)
    print("  🐡 NEMOFISH — LIVE EXECUTION PIPELINE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 65)


def step_1_fetch_fixtures(tennis_client):
    """Step 1: Get today's real fixtures from api-tennis.com."""
    print("\n📡 STEP 1: Fetching fixtures from api-tennis.com...")
    
    today = datetime.now().strftime("%Y-%m-%d")
    fixtures = tennis_client.get_fixtures(date_start=today, date_stop=today)
    
    # Filter to ATP/WTA singles only
    singles = [f for f in fixtures
               if any(t in f.event_type.lower() for t in ["atp singles", "wta singles"])]
    
    print(f"   Total fixtures: {len(fixtures)}")
    print(f"   ATP/WTA Singles: {len(singles)}")
    
    for f in singles[:8]:
        print(f"   📋 {f.player_a} vs {f.player_b} | {f.tournament} {f.round_name} | {f.time}")
    
    if len(singles) > 8:
        print(f"   ... and {len(singles) - 8} more")
    
    return singles


def step_2_enrich_rankings(sportradar_client):
    """Step 2: Fetch current rankings for enrichment."""
    print("\n📊 STEP 2: Fetching Sportradar rankings...")
    
    rankings = {}
    try:
        atp = sportradar_client.get_rankings("ATP")
        if atp and "rankings" in atp:
            for ranking in atp["rankings"]:
                for entry in ranking.get("competitor_rankings", []):
                    name = entry.get("competitor", {}).get("name", "")
                    if name:
                        rankings[name.lower()] = {
                            "rank": entry.get("rank", 999),
                            "points": entry.get("points", 0),
                        }
        print(f"   ATP rankings loaded: {len(rankings)} players")
    except Exception as e:
        print(f"   ⚠️  Rankings fetch error: {e}")
    
    return rankings


def step_3_search_polymarket(pm_client):
    """Step 3: Find tennis markets on Polymarket."""
    print("\n🔎 STEP 3: Searching Polymarket for tennis markets...")
    
    markets = pm_client.find_tennis_markets()
    
    if markets:
        print(f"   Found {len(markets)} tennis market(s)!")
        for e in markets[:5]:
            print(f"   📎 {e.title}")
            for m in e.markets[:2]:
                print(f"      → {m.question}: YES {m.outcome_yes_price:.0%} | Vol ${m.volume:,.0f}")
    else:
        print("   ⚠️  No tennis markets found on Polymarket currently")
        print("   ℹ️  This is normal — tennis markets appear closer to match time")
        print("   ℹ️  Pipeline still runs swarm predictions for paper tracking")
    
    return markets


def step_4_run_swarm(swarm, fixtures, rankings, resolver=None):
    """Step 4: Run swarm prediction on each viable match."""
    print("\n🤖 STEP 4: Running 5-agent swarm on ATP/WTA matches...")
    
    predictions = []
    
    for fix in fixtures:
        # Resolve abbreviated names to full canonical names
        player_a = resolver.resolve(fix.player_a) if resolver else fix.player_a
        player_b = resolver.resolve(fix.player_b) if resolver else fix.player_b
        
        # Show resolution if name changed
        if player_a != fix.player_a or player_b != fix.player_b:
            resolved_parts = []
            if player_a != fix.player_a:
                resolved_parts.append(f"{fix.player_a} → {player_a}")
            if player_b != fix.player_b:
                resolved_parts.append(f"{fix.player_b} → {player_b}")
            print(f"   🔗 Name resolved: {', '.join(resolved_parts)}")
        
        # Lookup rankings
        rank_a = rankings.get(player_a.lower(), {}).get("rank", 80)
        rank_b = rankings.get(player_b.lower(), {}).get("rank", 80)
        pts_a = rankings.get(player_a.lower(), {}).get("points", 0)
        pts_b = rankings.get(player_b.lower(), {}).get("points", 0)
        
        # Determine tournament level
        tournament = fix.tournament.lower()
        if "grand slam" in tournament or "australian" in tournament or "french" in tournament or "wimbledon" in tournament or "us open" in tournament:
            level = "G"
        elif "masters" in tournament or "miami" in tournament or "indian wells" in tournament or "madrid" in tournament or "rome" in tournament:
            level = "M"
        elif "500" in fix.event_type.lower():
            level = "A"
        else:
            level = "B"
        
        # Determine surface
        if "clay" in tournament or "roland" in tournament or "rome" in tournament:
            surface = "Clay"
        elif "grass" in tournament or "wimbledon" in tournament:
            surface = "Grass"
        else:
            surface = "Hard"
        
        ctx = MatchContext(
            player_a=player_a,
            player_b=player_b,
            surface=surface,
            tourney_name=fix.tournament,
            tourney_level=level,
            round_name=fix.round_name or "R32",
            date=fix.date,
            rank_a=rank_a,
            rank_b=rank_b,
            rank_pts_a=pts_a,
            rank_pts_b=pts_b,
        )
        
        try:
            prediction = swarm.predict(ctx)
            predictions.append({
                "fixture": fix,
                "context": ctx,
                "prediction": prediction,
            })
            
            # Display result
            action_icon = {"BET_A": "🎯", "BET_B": "🎯", "SKIP": "⏸️"}.get(
                prediction.recommended_action, "❓")
            edge_str = f"{prediction.edge_vs_market:+.1%}" if prediction.edge_vs_market else "N/A"
            
            print(f"\n   {action_icon} {player_a} vs {player_b}")
            print(f"      Swarm: {player_a} {prediction.prob_a:.1%} | {player_b} {prediction.prob_b:.1%}")
            print(f"      Confidence: {prediction.confidence} | Edge: {edge_str}")
            print(f"      Action: {prediction.recommended_action}", end="")
            if prediction.kelly_bet_size > 0:
                print(f" | Kelly: ${prediction.kelly_bet_size:.2f}", end="")
            print()
            
        except Exception as e:
            print(f"   ⚠️  Swarm error on {player_a} vs {player_b}: {e}")
    
    # Summary
    bets = [p for p in predictions if p["prediction"].recommended_action != "SKIP"]
    print(f"\n   ━━━ Swarm Summary ━━━")
    print(f"   Analyzed: {len(predictions)} matches")
    print(f"   BET signals: {len(bets)}")
    print(f"   SKIP signals: {len(predictions) - len(bets)}")
    
    return predictions


def step_4b_filter_strategies(predictions, strategy_names):
    """Step 4B: Apply strategy layer to filter swarm predictions into bet decisions."""
    print(f"\n🎲 STEP 4B: Strategy filter ({', '.join(strategy_names)})...")
    
    strategies = [STRATEGY_REGISTRY[s] for s in strategy_names if s in STRATEGY_REGISTRY]
    if not strategies:
        print("   ⚠️  No valid strategies — falling back to swarm signals only")
        return predictions
    
    # Build MatchInput objects from swarm predictions
    strategy_signals = []
    
    for pred_data in predictions:
        pred = pred_data['prediction']
        fix = pred_data['fixture']
        ctx = pred_data['context']
        
        # Map swarm output to MatchInput for strategy evaluation
        # Use swarm prob as model_prob, and market_odds derived from edge
        model_prob_a = pred.prob_a
        # If we have market odds from edge, derive implied prob; otherwise assume fair odds
        if pred.edge_vs_market is not None and pred.edge_vs_market != 0:
            # edge = model_prob - implied_prob → implied_prob = model_prob - edge
            implied_prob_a = max(0.05, min(0.95, model_prob_a - pred.edge_vs_market))
        else:
            implied_prob_a = model_prob_a  # No market, assume fair
        
        market_odds_a = 1.0 / max(0.01, implied_prob_a)
        market_odds_b = 1.0 / max(0.01, 1 - implied_prob_a)
        
        match_input = MatchInput(
            player_a=ctx.player_a,
            player_b=ctx.player_b,
            prob_a=model_prob_a,
            prob_b=pred.prob_b,
            odds_a=market_odds_a,
            odds_b=market_odds_b,
            surface=ctx.surface,
            tourney_level=ctx.tourney_level,
            round_name=ctx.round_name,
            confidence=pred.confidence,
        )
        
        # Run each strategy
        match_decisions = []
        for strategy in strategies:
            decision = strategy.evaluate_match(match_input)
            if decision.should_bet:
                match_decisions.append({
                    'strategy': strategy.name,
                    'decision': decision,
                })
        
        # If ANY strategy says bet, include this match
        if match_decisions:
            pred_data['strategy_decisions'] = match_decisions
            strategy_signals.append(pred_data)
            
            best = match_decisions[0]  # First strategy that triggered
            d = best['decision']
            pick = ctx.player_a if d.pick == 'A' else ctx.player_b
            print(f"   🎯 {ctx.player_a} vs {ctx.player_b}")
            print(f"      Strategy: {best['strategy']} → {pick} "
                  f"(edge {d.edge:+.1%}, size ${d.bet_size:.0f})")
        else:
            pred_data['strategy_decisions'] = []
    
    print(f"\n   ━━━ Strategy Summary ━━━")
    print(f"   Swarm signals: {len(predictions)}")
    print(f"   Strategy-approved: {len(strategy_signals)}")
    print(f"   Filtered out: {len(predictions) - len(strategy_signals)}")
    
    return strategy_signals


def step_5_execute(trader, predictions, scan_only=False):
    """Step 5: Execute bets on Polymarket (or paper track)."""
    print(f"\n💰 STEP 5: Execution ({trader.mode} mode){'  [SCAN ONLY]' if scan_only else ''}")
    
    bets = [p for p in predictions if p["prediction"].recommended_action != "SKIP"]
    
    if not bets:
        print("   No actionable signals — all SKIP")
        return []
    
    if scan_only:
        print("   Scan-only mode — showing opportunities without executing")
        for b in bets:
            pred = b["prediction"]
            fix = b["fixture"]
            print(f"\n   🎯 SIGNAL: {fix.player_a} vs {fix.player_b}")
            print(f"      Pick: {fix.player_a if pred.recommended_action == 'BET_A' else fix.player_b}")
            print(f"      Prob: {max(pred.prob_a, pred.prob_b):.1%}")
            print(f"      Edge: {pred.edge_vs_market:+.1%}" if pred.edge_vs_market else "")
            print(f"      Kelly: ${pred.kelly_bet_size:.2f}")
        return []
    
    results = []
    daily_spent = 0.0
    
    for b in bets:
        pred = b["prediction"]
        fix = b["fixture"]
        
        # Determine pick
        if pred.recommended_action == "BET_A":
            pick_name = fix.player_a
            pick_prob = pred.prob_a
        else:
            pick_name = fix.player_b
            pick_prob = pred.prob_b
        
        # Calculate bet size (capped)
        conf_mult = CONFIDENCE_MULTIPLIER.get(pred.confidence, 0.25)
        bet_size = min(
            pred.kelly_bet_size * conf_mult,
            MAX_BET_PER_MATCH,
            MAX_DAILY_EXPOSURE - daily_spent,
        )
        
        if bet_size < 1.0:
            print(f"   ⏸️ {fix.player_a} vs {fix.player_b}: bet too small (${bet_size:.2f})")
            continue
        
        # Try to find matching Polymarket market
        # For now, paper-trade based on our model probabilities
        from execution.polymarket_live import Market
        
        synthetic_market = Market(
            condition_id=f"NF-{fix.event_key}",
            question=f"Will {pick_name} win {fix.tournament} {fix.round_name}?",
            yes_price=pick_prob,
            no_price=1 - pick_prob,
            volume=0,
            liquidity=0,
            active=True,
            token_yes="",
            token_no="",
            event_title=f"{fix.player_a} vs {fix.player_b}",
        )
        
        result = trader.place_bet(
            market=synthetic_market,
            side="YES",
            amount_usd=bet_size,
            price=pick_prob,
        )
        
        if result.success:
            daily_spent += bet_size
            results.append({
                "match": f"{fix.player_a} vs {fix.player_b}",
                "pick": pick_name,
                "prob": pick_prob,
                "edge": pred.edge_vs_market,
                "bet_size": bet_size,
                "confidence": pred.confidence,
                "order_id": result.order_id,
            })
    
    print(f"\n   ━━━ Execution Summary ━━━")
    print(f"   Orders placed: {len(results)}")
    print(f"   Daily exposure: ${daily_spent:.2f} / ${MAX_DAILY_EXPOSURE:.2f}")
    print(f"\n{trader.summary()}")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="NemoFish Live Execution Pipeline")
    parser.add_argument("--live", action="store_true", help="Enable LIVE trading (real $$$)")
    parser.add_argument("--scan-only", action="store_true", help="Scan only, no execution")
    parser.add_argument("--strategies", nargs="+", default=DEFAULT_STRATEGIES,
                        choices=list(STRATEGY_REGISTRY.keys()),
                        help=f"Strategies to use (default: {DEFAULT_STRATEGIES})")
    parser.add_argument("--no-strategy-filter", action="store_true",
                        help="Skip strategy filtering, use swarm signals directly")
    args = parser.parse_args()
    
    mode = "LIVE" if args.live else "PAPER"
    banner()
    print(f"  Mode: {mode}")
    print(f"  Strategies: {', '.join(args.strategies)}")
    
    # Initialize all components
    print("\n⚙️  Initializing components...")
    
    tennis_client = ApiTennisClient()
    print("   ✅ api-tennis.com client")
    
    sportradar_client = SportradarTennisClient()
    print("   ✅ Sportradar Tennis client")
    
    pm_read = PolymarketClient()
    print("   ✅ Polymarket reader")
    
    trader = PolymarketTrader(mode=mode)
    print(f"   ✅ Polymarket trader ({mode})")
    print(f"      API Key: {'✅ ' + trader.api_key[:12] + '...' if trader.api_key else '❌ Not set'}")
    print(f"      Wallet:  {'✅ ' + trader.wallet[:12] + '...' if trader.wallet else '❌ Not set'}")
    
    print("   🧠 Loading swarm (Elo engine from 74,906 matches + Sackmann)...")
    swarm = TennisSwarm()
    print("   ✅ 5-agent swarm ready")
    
    # Name resolver bridges abbreviated API names to full Elo/Sackmann names
    resolver = TennisNameResolver()
    resolver.load_from_elo(swarm.elo_engine)
    if swarm.sackmann:
        resolver.load_from_sackmann(swarm.sackmann)
    print(f"   ✅ Name resolver ({resolver.player_count:,} players)")
    
    # === RUN PIPELINE ===
    
    fixtures = step_1_fetch_fixtures(tennis_client)
    
    if not fixtures:
        print("\n❌ No ATP/WTA singles fixtures today. Try again on a match day.")
        return
    
    rankings = step_2_enrich_rankings(sportradar_client)
    pm_markets = step_3_search_polymarket(pm_read)
    predictions = step_4_run_swarm(swarm, fixtures, rankings, resolver=resolver)
    
    # Step 4B: Strategy filter
    if not args.no_strategy_filter:
        predictions = step_4b_filter_strategies(predictions, args.strategies)
    
    results = step_5_execute(trader, predictions, scan_only=args.scan_only)
    
    # === FINAL REPORT ===
    print("\n" + "═" * 65)
    print("  🐡 PIPELINE COMPLETE")
    print(f"  Fixtures scanned: {len(fixtures)}")
    print(f"  Predictions made: {len(predictions)}")
    print(f"  Bets executed: {len(results)}")
    print(f"  Mode: {mode}")
    print(f"  Time: {datetime.now().strftime('%H:%M:%S')}")
    print("═" * 65)
    
    # Save run report
    report = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "fixtures_scanned": len(fixtures),
        "predictions_made": len(predictions),
        "bets_executed": len(results),
        "results": results,
        "daily_summary": trader.get_balance(),
    }
    
    report_path = ROOT / "execution" / "last_run.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n📄 Report saved: {report_path}")


if __name__ == "__main__":
    main()
