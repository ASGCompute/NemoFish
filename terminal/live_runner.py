#!/usr/bin/env python3
"""
NemoFish Live Runner — End-to-End Pipeline
============================================
Connects REAL data sources → Swarm prediction → Polymarket execution.

Pipeline:
  1. Fetch today's fixtures from api-tennis.com
  2. Enrich with Sportradar rankings + competitor data
  2B. Fetch real-time odds from The Odds API → inject into MatchContext
  3. Search Polymarket for matching tennis markets
  4. Run 5-agent swarm on each viable match (with real odds)
  4B. Apply strategy filter
  5. Match fixture to real Polymarket market → execute (or skip NO_MARKET)

Fail-closed policy:
  - No odds → NO_ODDS, skip
  - No market match → NO_MARKET, skip
  - Source error → abort pipeline

Canary rules (--live):
  - Fixed $1 max per bet
  - $4 daily cap
  - 1 concurrent order max
  - No Kelly in live

Usage:
  python3 terminal/live_runner.py              # Full pipeline (PAPER mode)
  python3 terminal/live_runner.py --live       # LIVE mode (real $$$)
  python3 terminal/live_runner.py --scan-only  # Just scan, don't bet
"""

import sys
import json
import os
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import asdict
from difflib import SequenceMatcher

# Path setup
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Load .env from project root
_ENV_PATH = ROOT.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from feeds.api_tennis import ApiTennisClient
from feeds.sportradar_tennis import SportradarTennisClient
from feeds.polymarket import PolymarketClient
from feeds.name_resolver import TennisNameResolver
from feeds.odds_api import OddsAPIClient
from agents.tennis_swarm import TennisSwarm, MatchContext
from execution.polymarket_live import PolymarketTrader, Market
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
    'kelly_quarter': KellyStrategy(kelly_fraction=0.25),
    'skemp_value': SkempValueOnlyStrategy(),
    'skemp_predict_value': SkempPredictedWinValueStrategy(),
}

# Default strategy set — only proven profitable strategies
DEFAULT_STRATEGIES = ['atp_confidence_5']

# === Canary Go-Live Rules ===
CANARY_MAX_STAKE = 1.0          # $1 max per bet in live
CANARY_MAX_DAILY = 4.0          # $4 total daily exposure in live
CANARY_MAX_CONCURRENT = 1       # 1 live order at a time

# === Config ===
MIN_EDGE_THRESHOLD = 0.03       # 3% minimum edge to place bet
MAX_BET_PER_MATCH = 50.0        # Max $50 per position (paper)
MAX_DAILY_EXPOSURE = 200.0      # Max $200 total daily (paper)
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


# === Run Artifact Saving ===

def _ensure_run_dir():
    """Create timestamped run directory for artifacts."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "execution" / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _save_artifact(run_dir, name, data):
    """Save a JSON artifact to the run directory."""
    path = run_dir / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    print(f"   💾 Saved: {path.name}")
    return path


# === Polymarket Market Matching ===

def _normalize_name(name: str) -> str:
    """Normalize player name for matching: lowercase, strip dots/initials."""
    name = name.strip().lower()
    # Remove common suffixes/prefixes
    name = name.replace(".", "").replace("-", " ")
    parts = name.split()
    # Filter out single-letter initials
    parts = [p for p in parts if len(p) > 1]
    return " ".join(parts)


def match_fixture_to_polymarket(fixture, pm_markets, pm_events=None):
    """
    Match a fixture (player_a vs player_b) to a real Polymarket market.

    Args:
        fixture: ApiTennisMatch with player_a, player_b
        pm_markets: List of Market objects from PolymarketTrader
        pm_events: List of PolymarketEvent objects from PolymarketClient

    Returns:
        Market with real condition_id/token_yes/token_no, or None
    """
    pa_norm = _normalize_name(fixture.player_a)
    pb_norm = _normalize_name(fixture.player_b)

    # Extract last names for matching
    pa_last = pa_norm.split()[-1] if pa_norm.split() else pa_norm
    pb_last = pb_norm.split()[-1] if pb_norm.split() else pb_norm

    best_market = None
    best_score = 0.0

    # Search through trader markets (Market objects)
    for market in (pm_markets or []):
        title = (market.event_title + " " + market.question).lower()
        slug = market.event_slug.lower() if hasattr(market, 'event_slug') else ""

        searchable = title + " " + slug

        # Both players must appear in the market title/question
        pa_found = pa_last in searchable
        pb_found = pb_last in searchable

        if pa_found and pb_found:
            # Score by name similarity
            score_a = SequenceMatcher(None, pa_norm, searchable).ratio()
            score_b = SequenceMatcher(None, pb_norm, searchable).ratio()
            score = score_a + score_b

            # Require real tokens
            if market.token_yes and market.token_no and market.condition_id:
                if score > best_score:
                    best_score = score
                    best_market = market

    # Also search through events (PolymarketEvent objects)
    for event in (pm_events or []):
        title = event.title.lower()
        slug = event.slug.lower() if hasattr(event, 'slug') else ""
        searchable = title + " " + slug

        pa_found = pa_last in searchable
        pb_found = pb_last in searchable

        if pa_found and pb_found:
            # Find best market within this event
            for m in event.markets:
                if m.token_id_yes and m.token_id_no and m.condition_id:
                    score = SequenceMatcher(None, pa_norm + " " + pb_norm, searchable).ratio()
                    if score > best_score:
                        best_score = score
                        # Convert PolymarketMarket to Market
                        best_market = Market(
                            condition_id=m.condition_id,
                            question=m.question,
                            yes_price=m.outcome_yes_price,
                            no_price=m.outcome_no_price,
                            volume=m.volume,
                            liquidity=m.liquidity,
                            active=m.active,
                            token_yes=m.token_id_yes,
                            token_no=m.token_id_no,
                            event_title=event.title,
                            event_slug=event.slug if hasattr(event, 'slug') else "",
                        )

    return best_market


# === Pipeline Steps ===

def step_1_fetch_fixtures(tennis_client):
    """Step 1: Get today's real fixtures from api-tennis.com."""
    print("\n📡 STEP 1: Fetching fixtures from api-tennis.com...")

    if not tennis_client.api_key:
        print("   ❌ FAIL-CLOSED: API_TENNIS_KEY not configured")
        return None  # Signal source failure

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        fixtures = tennis_client.get_fixtures(date_start=today, date_stop=today)
    except Exception as e:
        print(f"   ❌ FAIL-CLOSED: Fixtures fetch failed: {e}")
        return None

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
    if not sportradar_client.api_key:
        print("   ⚠️  SPORTRADAR_API_KEY not configured — rankings unavailable")
        return rankings

    try:
        raw = sportradar_client.get_rankings()
        # raw is Dict[str, List[SRRanking]]
        if isinstance(raw, dict):
            for tour_key, entries in raw.items():
                for entry in entries:
                    # entry is SRRanking dataclass
                    name = entry.player_name if hasattr(entry, 'player_name') else ""
                    if name:
                        rankings[name.lower()] = {
                            "rank": entry.rank if hasattr(entry, 'rank') else 999,
                            "points": entry.points if hasattr(entry, 'points') else 0,
                        }
        print(f"   ATP/WTA rankings loaded: {len(rankings)} players")
    except Exception as e:
        print(f"   ⚠️  Rankings fetch error: {e}")

    return rankings


def step_3_search_polymarket(pm_client, pm_trader):
    """Step 3: Find tennis markets on Polymarket."""
    print("\n🔎 STEP 3: Searching Polymarket for tennis markets...")

    # Get events from read client
    events = pm_client.find_tennis_markets()
    # Get markets from trader client  
    trader_markets = pm_trader.find_tennis_markets()

    total = len(events) + len(trader_markets)

    if events:
        print(f"   Found {len(events)} tennis event(s) via reader!")
        for e in events[:5]:
            print(f"   📎 {e.title}")
            for m in e.markets[:2]:
                print(f"      → {m.question}: YES {m.outcome_yes_price:.0%} | Vol ${m.volume:,.0f}")

    if trader_markets:
        print(f"   Found {len(trader_markets)} tennis market(s) via trader!")
        for m in trader_markets[:5]:
            print(f"   📎 {m.event_title}: {m.question}")
            print(f"      YES {m.yes_price:.0%} | NO {m.no_price:.0%} | Vol ${m.volume:,.0f}")

    if total == 0:
        print("   ⚠️  No tennis markets found on Polymarket currently")
        print("   ℹ️  This is normal — tennis markets appear closer to match time")
        print("   ℹ️  Fixtures will be marked NO_MARKET in execution")

    return events, trader_markets


def step_4_run_swarm(swarm, fixtures, rankings, live_odds, resolver=None):
    """Step 4: Run swarm prediction on each viable match (with real odds injected)."""
    print("\n🤖 STEP 4: Running swarm on ATP/WTA matches...")

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

        # Lookup rankings — NO silent defaults
        rank_data_a = rankings.get(player_a.lower(), None)
        rank_data_b = rankings.get(player_b.lower(), None)

        if rank_data_a:
            rank_a = rank_data_a["rank"]
            pts_a = rank_data_a["points"]
        else:
            rank_a = 999  # Explicit: unranked
            pts_a = 0

        if rank_data_b:
            rank_b = rank_data_b["rank"]
            pts_b = rank_data_b["points"]
        else:
            rank_b = 999
            pts_b = 0

        # === INJECT REAL ODDS ===
        odds_a = None
        odds_b = None
        odds_source = "NO_ODDS"

        # Try matching by player names in live_odds dict
        key = tuple(sorted([player_a.lower(), player_b.lower()]))
        if key in live_odds:
            match_odds = live_odds[key]
            # Determine which is home/away
            if player_a.lower() in match_odds.home_player.lower() or \
               match_odds.home_player.lower() in player_a.lower():
                odds_a = match_odds.avg_odds_home
                odds_b = match_odds.avg_odds_away
            else:
                odds_a = match_odds.avg_odds_away
                odds_b = match_odds.avg_odds_home
            odds_source = f"odds_api ({len(match_odds.bookmakers)} bookmakers)"
        else:
            # Try fuzzy match on last names
            pa_last = player_a.split()[-1].lower() if player_a.split() else ""
            pb_last = player_b.split()[-1].lower() if player_b.split() else ""
            for odds_key, match_odds in live_odds.items():
                home_last = match_odds.home_player.split()[-1].lower() if match_odds.home_player else ""
                away_last = match_odds.away_player.split()[-1].lower() if match_odds.away_player else ""
                if (pa_last == home_last and pb_last == away_last):
                    odds_a = match_odds.avg_odds_home
                    odds_b = match_odds.avg_odds_away
                    odds_source = f"odds_api_fuzzy ({len(match_odds.bookmakers)} bookmakers)"
                    break
                elif (pa_last == away_last and pb_last == home_last):
                    odds_a = match_odds.avg_odds_away
                    odds_b = match_odds.avg_odds_home
                    odds_source = f"odds_api_fuzzy ({len(match_odds.bookmakers)} bookmakers)"
                    break

        # Also try api-tennis odds for the match
        # (already have the fixture, can fetch odds by event_key)

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
            odds_a=odds_a,   # Real odds injected!
            odds_b=odds_b,   # Real odds injected!
        )

        try:
            prediction = swarm.predict(ctx)
            predictions.append({
                "fixture": fix,
                "context": ctx,
                "prediction": prediction,
                "odds_source": odds_source,
            })

            # Display result
            action_icon = {"BET_A": "🎯", "BET_B": "🎯", "SKIP": "⏸️"}.get(
                prediction.recommended_action, "❓")
            edge_str = f"{prediction.edge_vs_market:+.1%}" if prediction.edge_vs_market else "N/A"

            odds_disp = f"[{odds_a:.2f}/{odds_b:.2f}]" if odds_a else "[NO_ODDS]"

            print(f"\n   {action_icon} {player_a} vs {player_b} {odds_disp}")
            print(f"      Swarm: {player_a} {prediction.prob_a:.1%} | {player_b} {prediction.prob_b:.1%}")
            print(f"      Confidence: {prediction.confidence} | Edge: {edge_str} | Odds: {odds_source}")
            print(f"      Action: {prediction.recommended_action}", end="")
            if prediction.kelly_bet_size > 0:
                print(f" | Kelly: ${prediction.kelly_bet_size:.2f}", end="")
            print()

        except Exception as e:
            print(f"   ⚠️  Swarm error on {player_a} vs {player_b}: {e}")

    # Summary
    bets = [p for p in predictions if p["prediction"].recommended_action != "SKIP"]
    with_odds = [p for p in predictions if p.get("odds_source", "NO_ODDS") != "NO_ODDS"]
    print(f"\n   ━━━ Swarm Summary ━━━")
    print(f"   Analyzed: {len(predictions)} matches")
    print(f"   With real odds: {len(with_odds)}")
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
        model_prob_a = pred.prob_a

        # Use REAL market odds if available, otherwise derive from edge
        if ctx.odds_a and ctx.odds_b:
            market_odds_a = ctx.odds_a
            market_odds_b = ctx.odds_b
        elif pred.edge_vs_market is not None and pred.edge_vs_market != 0:
            implied_prob_a = max(0.05, min(0.95, model_prob_a - pred.edge_vs_market))
            market_odds_a = 1.0 / max(0.01, implied_prob_a)
            market_odds_b = 1.0 / max(0.01, 1 - implied_prob_a)
        else:
            market_odds_a = 1.0 / max(0.01, model_prob_a)
            market_odds_b = 1.0 / max(0.01, 1 - model_prob_a)

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

            best = match_decisions[0]
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


def step_5_execute(trader, predictions, pm_events, pm_trader_markets, scan_only=False, is_live=False):
    """Step 5: Execute bets — ONLY on real matched Polymarket markets."""
    mode_str = "LIVE 🔴" if is_live else trader.mode
    print(f"\n💰 STEP 5: Execution ({mode_str}){'  [SCAN ONLY]' if scan_only else ''}")

    bets = [p for p in predictions if p["prediction"].recommended_action != "SKIP"]

    if not bets:
        print("   No actionable signals — all SKIP")
        return []

    # Determine limits
    if is_live:
        max_stake = CANARY_MAX_STAKE
        max_daily = CANARY_MAX_DAILY
        max_concurrent = CANARY_MAX_CONCURRENT
        print(f"   🔴 CANARY MODE: ${max_stake} max/bet, ${max_daily} daily cap, {max_concurrent} concurrent")
    else:
        max_stake = MAX_BET_PER_MATCH
        max_daily = MAX_DAILY_EXPOSURE
        max_concurrent = 999

    results = []
    daily_spent = 0.0
    matched_count = 0
    unmatched_count = 0

    for b in bets:
        pred = b["prediction"]
        fix = b["fixture"]
        ctx = b["context"]
        odds_source = b.get("odds_source", "NO_ODDS")

        # === FAIL-CLOSED: No odds → skip ===
        if odds_source == "NO_ODDS":
            print(f"\n   ⏸️ {fix.player_a} vs {fix.player_b}: NO_ODDS — skip (fail-closed)")
            continue

        # Determine pick
        if pred.recommended_action == "BET_A":
            pick_name = fix.player_a
            pick_prob = pred.prob_a
        else:
            pick_name = fix.player_b
            pick_prob = pred.prob_b

        # === MATCH TO REAL POLYMARKET MARKET ===
        matched_market = match_fixture_to_polymarket(fix, pm_trader_markets, pm_events)

        if not matched_market:
            unmatched_count += 1
            print(f"\n   ⏸️ {fix.player_a} vs {fix.player_b}: NO_MARKET — skip (fail-closed)")
            continue

        matched_count += 1

        # Validate market has real tokens
        if not matched_market.token_yes or not matched_market.token_no:
            print(f"\n   ⏸️ {fix.player_a} vs {fix.player_b}: NO_TOKENS — skip")
            continue

        if not matched_market.condition_id:
            print(f"\n   ⏸️ {fix.player_a} vs {fix.player_b}: NO_CONDITION_ID — skip")
            continue

        # Calculate bet size
        if is_live:
            bet_size = min(CANARY_MAX_STAKE, max_daily - daily_spent)
        else:
            conf_mult = CONFIDENCE_MULTIPLIER.get(pred.confidence, 0.25)
            bet_size = min(
                pred.kelly_bet_size * conf_mult,
                max_stake,
                max_daily - daily_spent,
            )

        if bet_size < 0.50:
            print(f"   ⏸️ {fix.player_a} vs {fix.player_b}: bet too small (${bet_size:.2f})")
            continue

        # Check concurrent limit
        if is_live and len(results) >= max_concurrent:
            print(f"   ⏸️ Concurrent limit reached ({max_concurrent}) — stop")
            break

        if scan_only:
            print(f"\n   🎯 SIGNAL: {fix.player_a} vs {fix.player_b}")
            print(f"      Pick: {pick_name}")
            print(f"      Prob: {pick_prob:.1%}")
            print(f"      Edge: {pred.edge_vs_market:+.1%}" if pred.edge_vs_market else "")
            print(f"      Bet: ${bet_size:.2f}")
            print(f"      Market: {matched_market.question}")
            print(f"      Condition: {matched_market.condition_id[:20]}...")
            print(f"      YES price: {matched_market.yes_price:.0%}")
            continue

        # === EXECUTE ON REAL MARKET ===
        result = trader.place_bet(
            market=matched_market,
            side="YES" if pred.recommended_action == "BET_A" else "NO",
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
                "market_condition_id": matched_market.condition_id,
                "market_question": matched_market.question,
                "odds_source": odds_source,
            })

    print(f"\n   ━━━ Execution Summary ━━━")
    print(f"   Market matched: {matched_count}")
    print(f"   No market: {unmatched_count}")
    print(f"   Orders placed: {len(results)}")
    print(f"   Daily exposure: ${daily_spent:.2f} / ${max_daily:.2f}")
    if not scan_only:
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
    if args.live:
        print(f"  🔴 CANARY RULES: ${CANARY_MAX_STAKE}/bet, ${CANARY_MAX_DAILY}/day, {CANARY_MAX_CONCURRENT} concurrent")

    # Create run artifact directory
    run_dir = _ensure_run_dir()
    print(f"  Run dir: {run_dir}")

    # Initialize all components
    print("\n⚙️  Initializing components...")

    tennis_client = ApiTennisClient()
    if tennis_client.api_key:
        print(f"   ✅ api-tennis.com client (key: {tennis_client.api_key[:8]}...)")
    else:
        print("   ❌ api-tennis.com: API_TENNIS_KEY not set!")

    sportradar_client = SportradarTennisClient()
    if sportradar_client.api_key:
        print(f"   ✅ Sportradar Tennis client (key: {sportradar_client.api_key[:8]}...)")
    else:
        print("   ⚠️  Sportradar: SPORTRADAR_API_KEY not set (rankings unavailable)")

    pm_read = PolymarketClient()
    print("   ✅ Polymarket reader")

    trader = PolymarketTrader(mode=mode)
    print(f"   ✅ Polymarket trader ({mode})")
    print(f"      API Key: {'✅ ' + trader.api_key[:12] + '...' if trader.api_key else '❌ Not set'}")
    print(f"      Wallet:  {'✅ ' + trader.wallet[:12] + '...' if trader.wallet else '❌ Not set'}")

    print("   🧠 Loading swarm (Elo engine from Sackmann data)...")
    swarm = TennisSwarm()
    print("   ✅ Swarm ready")

    # Name resolver bridges abbreviated API names to full Elo/Sackmann names
    resolver = TennisNameResolver()
    resolver.load_from_elo(swarm.elo)
    if hasattr(swarm, 'sackmann') and swarm.sackmann:
        resolver.load_from_sackmann(swarm.sackmann)
    print(f"   ✅ Name resolver ({resolver.player_count:,} players)")

    # Real-time odds from The Odds API
    odds_client = OddsAPIClient()
    if odds_client.api_key:
        print(f"   ✅ Odds API client (key: {odds_client.api_key[:8]}...)")
    else:
        print("   ⚠️  Odds API not configured (set ODDS_API_KEY for real odds)")

    # === RUN PIPELINE ===

    fixtures = step_1_fetch_fixtures(tennis_client)

    if fixtures is None:
        print("\n❌ FAIL-CLOSED: Fixture source failed. Pipeline aborted.")
        _save_artifact(run_dir, "run_summary", {
            "status": "ABORTED",
            "reason": "fixture_source_failed",
            "timestamp": datetime.now().isoformat(),
        })
        return

    if not fixtures:
        print("\n❌ No ATP/WTA singles fixtures today. Try again on a match day.")
        _save_artifact(run_dir, "run_summary", {
            "status": "NO_FIXTURES",
            "timestamp": datetime.now().isoformat(),
        })
        return

    # Save fixtures snapshot
    _save_artifact(run_dir, "fixtures", [
        {"player_a": f.player_a, "player_b": f.player_b,
         "tournament": f.tournament, "round": f.round_name,
         "date": f.date, "time": f.time, "event_key": f.event_key,
         "event_type": f.event_type}
        for f in fixtures
    ])

    rankings = step_2_enrich_rankings(sportradar_client)

    # Step 2B: Fetch real-time odds
    live_odds = {}
    if odds_client.api_key:
        print("\n📈 STEP 2B: Fetching real-time odds...")
        try:
            odds_list = odds_client.get_tennis_odds()
            for o in odds_list:
                # Index by lowercase player names pair
                key = tuple(sorted([o.home_player.lower(), o.away_player.lower()]))
                live_odds[key] = o
            print(f"   Found odds for {len(live_odds)} matches")
            if odds_list:
                odds_client.save_odds_snapshot(odds_list)
                _save_artifact(run_dir, "odds_snapshot", [
                    {"home": o.home_player, "away": o.away_player,
                     "avg_home": o.avg_odds_home, "avg_away": o.avg_odds_away,
                     "best_home": o.best_odds_home, "best_away": o.best_odds_away,
                     "implied_home": o.implied_prob_home, "implied_away": o.implied_prob_away,
                     "bookmakers": len(o.bookmakers), "sport": o.sport}
                    for o in odds_list
                ])
        except Exception as e:
            print(f"   ⚠️  Odds API error: {e}")
    else:
        print("\n📈 STEP 2B: Skipped — no ODDS_API_KEY")

    pm_events, pm_trader_markets = step_3_search_polymarket(pm_read, trader)

    # Save matched markets snapshot
    _save_artifact(run_dir, "polymarket_markets", {
        "events": [{"title": e.title, "slug": e.slug, "markets": len(e.markets)} for e in pm_events],
        "trader_markets": [{"question": m.question, "event": m.event_title,
                           "yes_price": m.yes_price, "volume": m.volume,
                           "condition_id": m.condition_id[:20] if m.condition_id else ""}
                          for m in pm_trader_markets],
    })

    predictions = step_4_run_swarm(swarm, fixtures, rankings, live_odds, resolver=resolver)

    # Step 4B: Strategy filter
    if not args.no_strategy_filter:
        predictions = step_4b_filter_strategies(predictions, args.strategies)

    # Save risk decisions
    _save_artifact(run_dir, "risk_decisions", [
        {"match": f"{p['fixture'].player_a} vs {p['fixture'].player_b}",
         "action": p["prediction"].recommended_action,
         "prob_a": p["prediction"].prob_a,
         "prob_b": p["prediction"].prob_b,
         "edge": p["prediction"].edge_vs_market,
         "confidence": p["prediction"].confidence,
         "kelly": p["prediction"].kelly_bet_size,
         "odds_source": p.get("odds_source", "NO_ODDS"),
         "data_quality": p["prediction"].data_quality_score}
        for p in predictions
    ])

    results = step_5_execute(
        trader, predictions, pm_events, pm_trader_markets,
        scan_only=args.scan_only, is_live=args.live,
    )

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
        "scan_only": args.scan_only,
        "fixtures_scanned": len(fixtures),
        "predictions_made": len(predictions),
        "bets_executed": len(results),
        "results": results,
        "daily_summary": trader.get_balance(),
        "odds_matches": len(live_odds),
        "polymarket_events": len(pm_events),
        "polymarket_trader_markets": len(pm_trader_markets),
    }

    _save_artifact(run_dir, "run_summary", report)

    # Also save to legacy location
    report_path = ROOT / "execution" / "last_run.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n📄 Report saved: {report_path}")
    print(f"📁 Full run artifacts: {run_dir}")


if __name__ == "__main__":
    main()
