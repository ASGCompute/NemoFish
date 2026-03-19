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
from strategies import STRATEGY_REGISTRY as _FULL_REGISTRY
from strategies.strategy_base import MatchInput

# Build CLI-compatible instance map from unified registry
STRATEGY_REGISTRY = {name: entry['instance'] for name, entry in _FULL_REGISTRY.items()}

# Default strategy set — only proven profitable strategies
DEFAULT_STRATEGIES = ['atp_confidence_5']

# === Execution Classes ===
from dataclasses import dataclass as _dc, field as _field

@_dc
class ExecutionClass:
    """Defines rules for each execution mode."""
    name: str
    label: str
    max_stake: float
    max_daily: float
    model_required: bool
    trader_mode: str   # "PAPER" or "LIVE"
    description: str

EXEC_INFRA_SMOKE = ExecutionClass(
    name="INFRA_SMOKE", label="SMOKE_TEST",
    max_stake=1.0, max_daily=1.0,
    model_required=False, trader_mode="PAPER",
    description="Infrastructure canary — $1 fixed, no model, h2h only",
)
EXEC_PAPER_MODEL = ExecutionClass(
    name="PAPER_MODEL", label="PAPER",
    max_stake=5.0, max_daily=20.0,
    model_required=True, trader_mode="PAPER",
    description="Swarm-gated paper trading — full pipeline, no real money",
)
EXEC_LIVE_CANARY = ExecutionClass(
    name="LIVE_CANARY", label="LIVE_CANARY",
    max_stake=1.0, max_daily=4.0,
    model_required=True, trader_mode="LIVE",
    description="Live canary — $1/bet max, $4/day cap, swarm-gated",
)
EXEC_LIVE_FULL = ExecutionClass(
    name="LIVE_FULL", label="LIVE_FULL",
    max_stake=5.0, max_daily=20.0,
    model_required=True, trader_mode="LIVE",
    description="Full live — model-gated, Kelly sizing, all strategies",
)

EXEC_CLASSES = {
    "INFRA_SMOKE": EXEC_INFRA_SMOKE,
    "PAPER_MODEL": EXEC_PAPER_MODEL,
    "LIVE_CANARY": EXEC_LIVE_CANARY,
    "LIVE_FULL": EXEC_LIVE_FULL,
}

# === Source of Truth — loaded from config.yaml ===
_CONFIG_PATH = ROOT / "config.yaml"
def _load_bankroll() -> float:
    """Load bankroll from config.yaml (single source of truth)."""
    if _CONFIG_PATH.exists():
        try:
            import yaml
            cfg = yaml.safe_load(_CONFIG_PATH.read_text())
            return float(cfg.get("bankroll", {}).get("initial_usd", 20.0))
        except ImportError:
            # Fallback: parse initial_usd from YAML without pyyaml
            for line in _CONFIG_PATH.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("initial_usd:"):
                    val = stripped.split(":")[1].strip().split("#")[0].strip()
                    try:
                        return float(val)
                    except ValueError:
                        pass
        except Exception:
            pass
    return 20.0

BANKROLL = _load_bankroll()

# === Canary Go-Live Rules (derived from execution class) ===
CANARY_MAX_STAKE = EXEC_LIVE_CANARY.max_stake
CANARY_MAX_DAILY = EXEC_LIVE_CANARY.max_daily
CANARY_MAX_CONCURRENT = 1       # 1 live order at a time

# === Config ===
MIN_EDGE_THRESHOLD = 0.03       # 3% minimum edge to place bet
MAX_BET_PER_MATCH = 5.0         # Max $5 per position (paper) — 25% of bankroll
MAX_DAILY_EXPOSURE = BANKROLL   # Max daily = BANKROLL
CONFIDENCE_MULTIPLIER = {
    "ELITE": 1.0,
    "HIGH": 0.75,
    "MEDIUM": 0.50,
    "LOW": 0.25,
}


def banner(exec_class: ExecutionClass = EXEC_PAPER_MODEL):
    print("═" * 65)
    print("  🐡 NEMOFISH — LIVE EXECUTION PIPELINE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Bankroll: ${BANKROLL:.0f}")
    print(f"  Execution: {exec_class.name} — {exec_class.description}")
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
        # Determine tour for gender-aware resolution
        tour = "WTA" if "wta" in fix.event_type.lower() else "ATP"

        # Resolve abbreviated names to full canonical names
        if resolver:
            res_a = resolver.resolve(fix.player_a, tour=tour)
            res_b = resolver.resolve(fix.player_b, tour=tour)
            player_a, conf_a = res_a.name, res_a.confidence
            player_b, conf_b = res_b.name, res_b.confidence

            # FAIL-CLOSED: skip match if either player is ambiguous/unresolved
            if conf_a in ('AMBIGUOUS', 'UNRESOLVED') or conf_b in ('AMBIGUOUS', 'UNRESOLVED'):
                bad_parts = []
                if conf_a in ('AMBIGUOUS', 'UNRESOLVED'):
                    bad_parts.append(f"{fix.player_a} [{conf_a}]")
                if conf_b in ('AMBIGUOUS', 'UNRESOLVED'):
                    bad_parts.append(f"{fix.player_b} [{conf_b}]")
                print(f"   ❌ UNRESOLVED_PLAYER: {', '.join(bad_parts)} — skipping match")
                predictions.append({
                    "match": f"{fix.player_a} vs {fix.player_b}",
                    "tournament": fix.tournament,
                    "recommended_action": "SKIP",
                    "reason": f"UNRESOLVED_PLAYER: {', '.join(bad_parts)}",
                    "edge": None,
                })
                continue
        else:
            player_a = fix.player_a
            player_b = fix.player_b
            conf_a = conf_b = 'EXACT'

        # Show resolution if name changed
        if player_a != fix.player_a or player_b != fix.player_b:
            resolved_parts = []
            if player_a != fix.player_a:
                resolved_parts.append(f"{fix.player_a} → {player_a} [{conf_a}]")
            if player_b != fix.player_b:
                resolved_parts.append(f"{fix.player_b} → {player_b} [{conf_b}]")
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

    # Summary — handle both normal predictions and UNRESOLVED_PLAYER dicts
    def _is_bet(p):
        if "prediction" in p:
            return p["prediction"].recommended_action != "SKIP"
        return p.get("recommended_action") != "SKIP"
    
    unresolved = [p for p in predictions if p.get("reason", "").startswith("UNRESOLVED_PLAYER")]
    bets = [p for p in predictions if _is_bet(p)]
    with_odds = [p for p in predictions if p.get("odds_source", "NO_ODDS") != "NO_ODDS"]
    print(f"\n   ━━━ Swarm Summary ━━━")
    print(f"   Analyzed: {len(predictions)} matches")
    print(f"   With real odds: {len(with_odds)}")
    print(f"   BET signals: {len(bets)}")
    print(f"   SKIP signals: {len(predictions) - len(bets) - len(unresolved)}")
    print(f"   UNRESOLVED_PLAYER: {len(unresolved)} (fail-closed)")

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
        # Skip UNRESOLVED_PLAYER entries — no prediction to filter
        if 'prediction' not in pred_data:
            strategy_signals.append(pred_data)
            continue

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

    # Filter out UNRESOLVED_PLAYER entries (they have no 'prediction' key)
    modeled = [p for p in predictions if "prediction" in p]
    bets = [p for p in modeled if p["prediction"].recommended_action != "SKIP"]

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


def smoke_test(pm_client, trader, scan_only=False, match_selector=None, condition_id=None):
    """
    Infrastructure canary: $1 bet on a specific h2h tennis match market.
    
    Requirements:
      - Must be a head-to-head match market ("Will X beat Y?")
      - No outright/futures ("Will X win tournament?")
      - Price must be in (0.01, 0.99) — no dead/resolved markets
      - Must specify --smoke-match "Player A vs Player B" or --smoke-condition <id>
    
    Bypasses swarm, strategy, and odds enrichment.
    Labels bet as SMOKE_TEST in journal.
    """
    print("\n🔧 SMOKE TEST — Infrastructure Canary")
    print("═" * 65)
    print("  Purpose: Verify order path works end-to-end")
    print("  Amount:  $1.00 (fixed)")
    print("  Label:   SMOKE_TEST (not model-driven)")
    print("  Filter:  h2h match markets only, price in (0.01, 0.99)")
    print("═" * 65)

    if not match_selector and not condition_id:
        print("\n   ❌ Must specify --smoke-match 'Player A vs Player B' or --smoke-condition <id>")
        print("   Example: --smoke --smoke-match 'Djokovic vs Alcaraz'")
        return

    # Search Polymarket for tennis h2h markets
    print("\n📡 Finding h2h tennis match markets...")
    events = pm_client.find_tennis_markets()
    h2h_keywords = ["beat", "win against", "defeat", " vs ", " v. ", " to win"]
    outright_keywords = ["winner", "champion", "win the", "to win 20", "grand slam", "tournament"]

    h2h_markets = []
    for event in events:
        for m in event.markets:
            q = m.question.lower() if m.question else ""
            # Filter: must look like h2h, not outright
            is_h2h = any(kw in q for kw in h2h_keywords)
            is_outright = any(kw in q for kw in outright_keywords)
            # Price sanity
            price_ok = (0.01 < m.outcome_yes_price < 0.99) if m.outcome_yes_price else False
            # Active with tokens
            has_tokens = bool(m.condition_id and m.token_id_yes and m.token_id_no)
            
            if has_tokens and price_ok and (is_h2h and not is_outright):
                h2h_markets.append({
                    "event_title": event.title,
                    "question": m.question,
                    "condition_id": m.condition_id,
                    "yes_price": m.outcome_yes_price,
                    "no_price": m.outcome_no_price,
                    "volume": m.volume or 0,
                    "liquidity": m.liquidity or 0,
                    "token_yes": m.token_id_yes,
                    "token_no": m.token_id_no,
                })

    print(f"   Found {len(h2h_markets)} h2h match markets (filtered from {sum(len(e.markets) for e in events)} total)")

    if not h2h_markets:
        print("   ❌ No qualifying h2h match markets found")
        print("   Markets must be: h2h match, price in (0.01,0.99), with valid tokens")
        return

    # Select target market
    target = None

    if condition_id:
        for m in h2h_markets:
            if m["condition_id"] == condition_id:
                target = m
                break
        if not target:
            print(f"   ❌ Condition ID {condition_id} not found in h2h markets")
            print("   Available h2h markets:")
            for m in sorted(h2h_markets, key=lambda x: -x["volume"])[:10]:
                print(f"     {m['question']} (vol=${m['volume']:,.0f}, cid={m['condition_id'][:20]}...)")
            return

    elif match_selector:
        # Fuzzy match on player names from --smoke-match "Player A vs Player B"
        selector_lower = match_selector.lower().replace(" vs ", " ").replace(" v ", " ")
        selector_parts = [p.strip() for p in selector_lower.split()]
        
        scored = []
        for m in h2h_markets:
            q_lower = m["question"].lower()
            # Count how many selector words appear in the question
            hits = sum(1 for p in selector_parts if p in q_lower)
            if hits >= len(selector_parts) * 0.5:  # At least half the words match
                scored.append((hits, m))
        
        scored.sort(key=lambda x: -x[0])
        if scored:
            target = scored[0][1]
        else:
            print(f"   ❌ No h2h market matching '{match_selector}'")
            print("   Available h2h markets:")
            for m in sorted(h2h_markets, key=lambda x: -x["volume"])[:10]:
                print(f"     {m['question']} (vol=${m['volume']:,.0f})")
            return

    print(f"\n   🎯 Target: {target['event_title']}")
    print(f"      Question: {target['question']}")
    print(f"      YES price: {target['yes_price']:.2%}")
    print(f"      NO price:  {target['no_price']:.2%}")
    print(f"      Volume: ${target['volume']:,.0f}")
    print(f"      Condition: {target['condition_id'][:30]}...")

    if scan_only:
        print(f"\n   📋 SCAN ONLY — would place $1.00 YES at {target['yes_price']:.4f}")
        print("   ✅ Smoke test preview complete. Use --smoke --live to execute.")
        return

    # Place $1 bet (paper mode)
    print(f"\n   💵 Placing $1.00 YES at {target['yes_price']:.4f} (PAPER)...")

    # Construct a Market object for the trader
    from execution.polymarket_live import Market
    smoke_market = Market(
        condition_id=target["condition_id"],
        question=target["question"],
        yes_price=target["yes_price"],
        no_price=target["no_price"],
        volume=target["volume"],
        liquidity=target["liquidity"],
        active=True,
        token_yes=target["token_yes"],
        token_no=target["token_no"],
        event_title=target["event_title"],
    )

    result = trader.place_bet(
        market=smoke_market,
        side="YES",
        amount_usd=1.0,
        price=target["yes_price"],
    )

    if result.success:
        print(f"   ✅ SMOKE TEST SUCCESS")
        print(f"      Order ID: {result.order_id}")
        print(f"      Status: {result.status}")
    else:
        print(f"   ❌ SMOKE TEST FAILED: {result.error}")


def main():
    parser = argparse.ArgumentParser(description="NemoFish Live Execution Pipeline")
    parser.add_argument("--live", action="store_true", help="Enable LIVE trading (real $$$)")
    parser.add_argument("--scan-only", action="store_true", help="Scan only, no execution")
    parser.add_argument("--smoke", action="store_true",
                        help="Infra canary: $1 bet on h2h match market, no model")
    parser.add_argument("--smoke-match", type=str, default=None,
                        help="Player names for smoke target (e.g. 'Djokovic vs Alcaraz')")
    parser.add_argument("--smoke-condition", type=str, default=None,
                        help="Polymarket condition_id for smoke target")
    parser.add_argument("--with-strategies", action="store_true",
                        help="Opt-in: apply strategy filter after swarm (default: swarm-only)")
    parser.add_argument("--strategies", nargs="+", default=DEFAULT_STRATEGIES,
                        choices=list(STRATEGY_REGISTRY.keys()),
                        help=f"Strategies (only with --with-strategies)")
    args = parser.parse_args()

    mode = "LIVE" if args.live else "PAPER"

    # Resolve execution class
    if args.smoke:
        exec_class = EXEC_INFRA_SMOKE
    elif args.live and getattr(args, 'full', False):
        exec_class = EXEC_LIVE_FULL
    elif args.live:
        exec_class = EXEC_LIVE_CANARY
    else:
        exec_class = EXEC_PAPER_MODEL

    # === GO-LIVE GATE ===
    # LIVE_CANARY and LIVE_FULL require at least 1 live-approved strategy
    if exec_class.trader_mode == "LIVE":
        from strategies import get_live_approved, get_by_status
        approved = get_live_approved()
        validated = get_by_status('validated')
        if not approved:
            print("\n" + "═" * 60)
            print("  ❌ GO-LIVE GATE: BLOCKED")
            print("  " + "─" * 56)
            print(f"  No live-approved strategies found.")
            if validated:
                names = [n for n, _ in validated]
                print(f"  Validated (need founder sign-off): {', '.join(names)}")
            else:
                print(f"  No validated strategies either — run backtest first.")
            print(f"\n  To proceed:")
            print(f"    1. python3 backtest_historical.py --n 200 --year 2026")
            print(f"    2. Review results, promote to live-approved")
            print(f"    3. Rerun with --live")
            print("═" * 60)
            sys.exit(1)

    banner(exec_class)
    print(f"  Mode: {mode}")
    if args.with_strategies:
        print(f"  Strategies: {', '.join(args.strategies)}")
    else:
        print(f"  Gate: swarm-only (use --with-strategies to add strategy filter)")
    if exec_class.trader_mode == "LIVE":
        print(f"  🔴 LIMITS: ${exec_class.max_stake}/bet, ${exec_class.max_daily}/day, {CANARY_MAX_CONCURRENT} concurrent")

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

    trader = PolymarketTrader(mode=mode, bankroll=BANKROLL)
    print(f"   ✅ Polymarket trader ({mode}, bankroll=${BANKROLL:.0f})")
    print(f"      API Key: {'✅ ' + trader.api_key[:12] + '...' if trader.api_key else '❌ Not set'}")
    print(f"      Wallet:  {'✅ ' + trader.wallet[:12] + '...' if trader.wallet else '❌ Not set'}")

    # === SMOKE TEST: intercept early ===
    if args.smoke:
        smoke_test(pm_read, trader,
                   scan_only=args.scan_only,
                   match_selector=args.smoke_match,
                   condition_id=args.smoke_condition)
        return

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

    # Fixture provider resilience: fallback to Odds API
    if fixtures is None and odds_client.api_key:
        print("\n🔄 FALLBACK: Trying Odds API for fixtures...")
        try:
            odds_matches = odds_client.get_tennis_odds()
            if odds_matches:
                from dataclasses import dataclass as _dc
                # Convert Odds API matches to fixture-like objects
                fixtures = []
                for o in odds_matches:
                    class _FallbackFixture:
                        pass
                    f = _FallbackFixture()
                    f.player_a = o.home_player
                    f.player_b = o.away_player
                    f.tournament = o.sport
                    f.round_name = ""
                    f.date = datetime.now().strftime("%Y-%m-%d")
                    f.time = ""
                    f.event_key = ""
                    f.event_type = "atp singles"  # Odds API already filtered
                    fixtures.append(f)
                print(f"   ✅ Fallback: {len(fixtures)} matches from Odds API")
        except Exception as e:
            print(f"   ❌ Odds API fallback also failed: {e}")
            fixtures = None

    if fixtures is None:
        print("\n❌ FAIL-CLOSED: All fixture sources failed. Pipeline aborted.")
        _save_artifact(run_dir, "run_summary", {
            "status": "ABORTED",
            "reason": "all_fixture_sources_failed",
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

    # Step 4B: Strategy filter (opt-in only)
    if args.with_strategies:
        predictions = step_4b_filter_strategies(predictions, args.strategies)
    else:
        print("\n🎲 STEP 4B: Skipped (swarm-only gate — use --with-strategies to enable)")

    # Save risk decisions — handle both modeled and UNRESOLVED entries
    def _to_risk_dict(p):
        if "prediction" in p:
            return {
                "match": f"{p['fixture'].player_a} vs {p['fixture'].player_b}",
                "action": p["prediction"].recommended_action,
                "prob_a": p["prediction"].prob_a,
                "prob_b": p["prediction"].prob_b,
                "edge": p["prediction"].edge_vs_market,
                "confidence": p["prediction"].confidence,
                "kelly": p["prediction"].kelly_bet_size,
                "odds_source": p.get("odds_source", "NO_ODDS"),
                "data_quality": p["prediction"].data_quality_score,
            }
        else:
            # UNRESOLVED_PLAYER entry
            return {
                "match": p.get("match", "unknown"),
                "action": "SKIP",
                "reason": p.get("reason", "UNRESOLVED_PLAYER"),
            }
    _save_artifact(run_dir, "risk_decisions", [_to_risk_dict(p) for p in predictions])

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
