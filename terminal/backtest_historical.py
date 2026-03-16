#!/usr/bin/env python3
"""
NemoFish Historical Backtester v2
====================================
Enhanced backtest with:
  ✅ Surface-specific Elo (already in engine)
  ✅ Real P&L from betting odds (B365, Pinnacle, Max, Avg)
  ✅ Rookie detection (low-match players → reduced confidence)
  ✅ 2025-2026 data support

No data leakage:
  1. Elo trained on 2000 → (test_year - 1)
  2. Out-of-sample test on last N matches of test_year
  3. Random player slot assignment (no winner bias)

Usage:
  python3 terminal/backtest_historical.py --n 200 --year 2025
  python3 terminal/backtest_historical.py --n 200 --year 2026
  python3 terminal/backtest_historical.py --n 500 --year 2025  # Monster test
"""

import sys
import csv
import argparse
import random
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from models.tennis_elo import TennisEloEngine
from agents.tennis_swarm import TennisSwarm, MatchContext


# --- Rookie threshold ---
ROOKIE_MATCH_THRESHOLD = 15  # Players with < 15 matches in our Elo DB


@dataclass
class HistoricalMatch:
    """A match from JeffSackmann or tennis-data.co.uk CSV."""
    tourney_name: str
    surface: str
    tourney_level: str
    tourney_date: str
    round_name: str
    winner_name: str
    winner_rank: int
    winner_seed: Optional[int]
    loser_name: str
    loser_rank: int
    loser_seed: Optional[int]
    score: str
    best_of: int
    minutes: int
    # Betting odds (from tennis-data.co.uk)
    odds_winner_b365: Optional[float] = None
    odds_loser_b365: Optional[float] = None
    odds_winner_avg: Optional[float] = None
    odds_loser_avg: Optional[float] = None
    odds_winner_max: Optional[float] = None
    odds_loser_max: Optional[float] = None


def load_test_matches(data_dir: str, year: int, n: int, main_tour_only: bool = True) -> List[HistoricalMatch]:
    """Load the last N matches from a year's CSV (supports both JeffSackmann & tennis-data.co.uk)."""
    csv_path = Path(data_dir) / f"atp_matches_{year}.csv"
    odds_path = Path(data_dir) / f"atp_odds_{year}.csv"

    if not csv_path.exists():
        print(f"❌ File not found: {csv_path}")
        return []

    # Load odds data if available (separate file)
    odds_lookup = {}
    if odds_path.exists():
        with open(odds_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row.get('winner_name','')}__{row.get('loser_name','')}__{row.get('tourney_date','')}"
                odds_lookup[key] = row

    matches = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            level = row.get('tourney_level', '')

            # Filter to main tour only
            if main_tour_only and level not in ('G', 'M', 'A', 'B', 'F'):
                continue

            # Parse ranks safely
            try:
                w_rank = int(float(row.get('winner_rank', 999) or 999))
            except:
                w_rank = 999
            try:
                l_rank = int(float(row.get('loser_rank', 999) or 999))
            except:
                l_rank = 999

            # Parse seeds
            w_seed = None
            l_seed = None
            try:
                if row.get('winner_seed'):
                    w_seed = int(float(row['winner_seed']))
            except:
                pass
            try:
                if row.get('loser_seed'):
                    l_seed = int(float(row['loser_seed']))
            except:
                pass

            try:
                minutes = int(float(row.get('minutes', 0) or 0))
            except:
                minutes = 0

            # Try to get odds from odds file
            odds_key = f"{row.get('winner_name','')}__{row.get('loser_name','')}__{row.get('tourney_date','')}"
            odds = odds_lookup.get(odds_key, {})

            def safe_float(val):
                try:
                    return float(val) if val and val != '' else None
                except:
                    return None

            matches.append(HistoricalMatch(
                tourney_name=row.get('tourney_name', ''),
                surface=row.get('surface', 'Hard'),
                tourney_level=level,
                tourney_date=row.get('tourney_date', ''),
                round_name=row.get('round', 'R32'),
                winner_name=row.get('winner_name', '').strip(),
                winner_rank=w_rank,
                winner_seed=w_seed,
                loser_name=row.get('loser_name', '').strip(),
                loser_rank=l_rank,
                loser_seed=l_seed,
                score=row.get('score', ''),
                best_of=int(row.get('best_of', 3) or 3),
                minutes=minutes,
                odds_winner_b365=safe_float(odds.get('odds_winner_b365')),
                odds_loser_b365=safe_float(odds.get('odds_loser_b365')),
                odds_winner_avg=safe_float(odds.get('odds_winner_avg')),
                odds_loser_avg=safe_float(odds.get('odds_loser_avg')),
                odds_winner_max=safe_float(odds.get('odds_winner_max')),
                odds_loser_max=safe_float(odds.get('odds_loser_max')),
            ))

    # Take last N matches
    if len(matches) > n:
        matches = matches[-n:]

    return matches


def is_rookie(engine: TennisEloEngine, player_name: str) -> bool:
    """Check if player is a rookie (too few matches in our Elo DB)."""
    rating = engine.get_player(player_name)
    if not rating:
        return True
    return rating.matches_played < ROOKIE_MATCH_THRESHOLD


def run_backtest(test_year: int = 2025, n_matches: int = 200):
    """Run the full enhanced historical backtest."""

    print("═" * 70)
    print("  🐡 NEMOFISH — ENHANCED HISTORICAL BACKTEST v2")
    print(f"  Testing on last {n_matches} ATP matches of {test_year}")
    print(f"  Elo trained on: 2000 – {test_year - 1} (NO data leakage)")
    print(f"  Features: Surface Elo ✅ | Real Odds P&L ✅ | Rookie detect ✅")
    print("═" * 70)

    data_dir = str(ROOT / "data" / "tennis" / "tennis_atp")

    # === STEP 1: Train Elo on data BEFORE test year ===
    print(f"\n⏳ Training Elo engine (2000–{test_year - 1})...")
    elo_engine = TennisEloEngine(data_dir)
    elo_engine.load_and_process(start_year=2000, end_year=test_year - 1)
    print(f"   ✅ {len(elo_engine.ratings)} players rated")

    # === STEP 2: Initialize swarm ===
    print("\n🧠 Initializing swarm...")
    swarm = TennisSwarm(elo_engine=elo_engine)
    print(f"   ✅ Swarm ready | Sackmann: {'loaded' if swarm.sackmann else 'unavailable'}")

    # === STEP 3: Load test matches ===
    print(f"\n📋 Loading test matches from {test_year}...")
    test_matches = load_test_matches(data_dir, test_year, n_matches)
    print(f"   ✅ {len(test_matches)} matches loaded")

    # Count matches with odds
    has_odds = sum(1 for m in test_matches if m.odds_winner_avg is not None)
    print(f"   📊 {has_odds}/{len(test_matches)} matches have betting odds")

    if not test_matches:
        print("❌ No test matches found!")
        return

    # === STEP 4: Run predictions ===
    print(f"\n🎾 Running predictions (blind — no result knowledge)...\n")

    results = []
    total_correct = 0
    rookie_count = 0
    rookie_correct = 0

    # Betting metrics
    total_bet_count = 0
    total_bet_correct = 0
    total_pnl = 0.0
    total_wagered = 0.0
    bets_by_edge = {"large": [], "medium": [], "small": []}

    for i, match in enumerate(test_matches):
        # Random player assignment (prevent winner bias)
        random.seed(hash(match.winner_name + match.loser_name + match.tourney_date))

        if random.random() > 0.5:
            player_a, player_b = match.winner_name, match.loser_name
            rank_a, rank_b = match.winner_rank, match.loser_rank
            seed_a, seed_b = match.winner_seed, match.loser_seed
            actual_winner = "A"
            odds_actual_winner = match.odds_winner_avg
            odds_actual_loser = match.odds_loser_avg
            odds_a = match.odds_winner_avg
            odds_b = match.odds_loser_avg
        else:
            player_a, player_b = match.loser_name, match.winner_name
            rank_a, rank_b = match.loser_rank, match.winner_rank
            seed_a, seed_b = match.loser_seed, match.winner_seed
            actual_winner = "B"
            odds_actual_winner = match.odds_winner_avg
            odds_actual_loser = match.odds_loser_avg
            odds_a = match.odds_loser_avg
            odds_b = match.odds_winner_avg

        # Rookie detection
        a_is_rookie = is_rookie(elo_engine, player_a)
        b_is_rookie = is_rookie(elo_engine, player_b)
        has_rookie = a_is_rookie or b_is_rookie

        # Build context
        ctx = MatchContext(
            player_a=player_a,
            player_b=player_b,
            surface=match.surface or "Hard",
            tourney_name=match.tourney_name,
            tourney_level=match.tourney_level,
            round_name=match.round_name,
            date=match.tourney_date,
            rank_a=rank_a,
            rank_b=rank_b,
            seed_a=seed_a,
            seed_b=seed_b,
            best_of=match.best_of,
        )

        # Swarm predicts
        prediction = swarm.predict(ctx)

        # Adjust confidence down for rookies
        confidence = prediction.confidence
        if has_rookie and confidence == "HIGH":
            confidence = "MEDIUM"
        if has_rookie:
            rookie_count += 1

        # Determine correctness
        predicted_winner = "A" if prediction.prob_a >= 0.5 else "B"
        correct = (predicted_winner == actual_winner)
        if correct:
            total_correct += 1
            if has_rookie:
                rookie_correct += 1

        # === REAL P&L from odds ===
        bet_result = None
        bet_pnl = 0.0
        model_edge = 0.0

        # Calculate edge vs market odds
        if odds_a and odds_b:
            implied_a = 1.0 / odds_a
            implied_b = 1.0 / odds_b

            if predicted_winner == "A":
                model_edge = prediction.prob_a - implied_a
                our_odds = odds_a
            else:
                model_edge = prediction.prob_b - implied_b
                our_odds = odds_b

            # Place bet if edge > 3%
            if model_edge >= 0.03:
                bet_size = 100.0  # Flat $100 bets for simplicity
                total_bet_count += 1
                total_wagered += bet_size

                if predicted_winner == "A":
                    bet_won = (actual_winner == "A")
                else:
                    bet_won = (actual_winner == "B")

                if bet_won:
                    bet_pnl = bet_size * (our_odds - 1)  # Real payout from odds
                    total_bet_correct += 1
                else:
                    bet_pnl = -bet_size

                total_pnl += bet_pnl
                bet_result = "WON" if bet_won else "LOST"

                # Categorize by edge size
                if model_edge >= 0.10:
                    bets_by_edge["large"].append(bet_pnl)
                elif model_edge >= 0.06:
                    bets_by_edge["medium"].append(bet_pnl)
                else:
                    bets_by_edge["small"].append(bet_pnl)

        # Display
        prob_display = prediction.prob_a if predicted_winner == "A" else prediction.prob_b
        correct_icon = "✅" if correct else "❌"
        rookie_icon = " 🆕" if has_rookie else ""
        bet_icon = ""
        if bet_result:
            bet_icon = f" | 💰 {bet_result} ${bet_pnl:+.0f} (edge:{model_edge:.0%})"

        actual_name = player_a if actual_winner == "A" else player_b
        predicted_name = player_a if predicted_winner == "A" else player_b

        print(f"  {i+1:3d}. {correct_icon} {player_a} vs {player_b}")
        print(f"       → {predicted_name} ({prob_display:.0%}) | ✓ {actual_name} | {confidence}{rookie_icon}{bet_icon}")

        results.append({
            "match": f"{player_a} vs {player_b}",
            "tournament": match.tourney_name,
            "surface": match.surface,
            "round": match.round_name,
            "predicted": predicted_name,
            "predicted_prob": round(prob_display, 4),
            "actual": actual_name,
            "correct": correct,
            "action": prediction.recommended_action,
            "confidence": confidence,
            "bet_result": bet_result,
            "bet_pnl": round(bet_pnl, 2),
            "model_edge": round(model_edge, 4),
            "has_rookie": has_rookie,
        })

    # === STEP 5: Report ===
    accuracy = total_correct / len(test_matches) * 100

    # Accuracy by confidence
    by_conf = {}
    for r in results:
        c = r["confidence"]
        if c not in by_conf:
            by_conf[c] = {"total": 0, "correct": 0}
        by_conf[c]["total"] += 1
        if r["correct"]:
            by_conf[c]["correct"] += 1

    # Accuracy by surface
    by_surface = {}
    for r in results:
        s = r["surface"]
        if s not in by_surface:
            by_surface[s] = {"total": 0, "correct": 0}
        by_surface[s]["total"] += 1
        if r["correct"]:
            by_surface[s]["correct"] += 1

    # Accuracy by round
    by_round = {}
    for r in results:
        rd = r["round"]
        if rd not in by_round:
            by_round[rd] = {"total": 0, "correct": 0}
        by_round[rd]["total"] += 1
        if r["correct"]:
            by_round[rd]["correct"] += 1

    # Rookie impact
    non_rookie_correct = total_correct - rookie_correct
    non_rookie_total = len(test_matches) - rookie_count
    non_rookie_acc = non_rookie_correct / non_rookie_total * 100 if non_rookie_total > 0 else 0

    print(f"\n{'═' * 70}")
    print(f"  📊 NEMOFISH BACKTEST RESULTS v2")
    print(f"{'═' * 70}")
    print(f"\n  Test Set: {len(test_matches)} ATP matches ({test_year})")
    print(f"  Elo Training: 2000–{test_year - 1} (out-of-sample)")
    print(f"  Matches with odds: {has_odds}/{len(test_matches)}")

    print(f"\n  ┌─────────────────────────────────────────────┐")
    print(f"  │  PREDICTION ACCURACY:  {accuracy:.1f}%                │")
    print(f"  │  Correct: {total_correct}/{len(test_matches)}                            │")
    print(f"  │  Random baseline: 50.0%                     │")
    print(f"  │  Edge vs random: +{accuracy - 50:.1f}pp                 │")
    print(f"  └─────────────────────────────────────────────┘")

    print(f"\n  By Confidence:")
    for conf in ["ELITE", "HIGH", "MEDIUM", "LOW"]:
        if conf in by_conf:
            d = by_conf[conf]
            acc = d["correct"] / d["total"] * 100 if d["total"] > 0 else 0
            bar = "█" * int(acc / 5) + "░" * (20 - int(acc / 5))
            print(f"    {conf:8s}: {d['correct']:3d}/{d['total']:3d} = {acc:4.0f}%  {bar}")

    print(f"\n  By Surface:")
    for s in ["Hard", "Clay", "Grass", "Carpet"]:
        if s in by_surface:
            d = by_surface[s]
            acc = d["correct"] / d["total"] * 100
            print(f"    {s:8s}: {d['correct']:3d}/{d['total']:3d} = {acc:.0f}%")

    print(f"\n  By Round:")
    for rd in ["F", "SF", "QF", "R16", "R32", "R64", "R128", "RR", "1st Round", "2nd Round", "3rd Round", "4th Round", "Quarterfinals", "Semifinals", "The Final"]:
        if rd in by_round:
            d = by_round[rd]
            acc = d["correct"] / d["total"] * 100
            print(f"    {rd:14s}: {d['correct']:3d}/{d['total']:3d} = {acc:.0f}%")

    print(f"\n  🆕 Rookie Impact:")
    print(f"    Matches with rookies:    {rookie_count} ({rookie_count/len(test_matches)*100:.0f}%)")
    if rookie_count > 0:
        print(f"    Rookie accuracy:         {rookie_correct}/{rookie_count} = {rookie_correct/rookie_count*100:.0f}%")
    print(f"    Non-rookie accuracy:     {non_rookie_correct}/{non_rookie_total} = {non_rookie_acc:.0f}%")

    if total_bet_count > 0:
        bet_accuracy = total_bet_correct / total_bet_count * 100
        roi = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0
        print(f"\n  ┌─────────────────────────────────────────────┐")
        print(f"  │  💰 REAL P&L (from actual betting odds)      │")
        print(f"  │  ─────────────────────────────────────────── │")
        print(f"  │  Bets Placed:    {total_bet_count:3d}                        │")
        print(f"  │  Win Rate:       {bet_accuracy:.1f}%                      │")
        print(f"  │  Total Wagered:  ${total_wagered:>10,.0f}              │")
        print(f"  │  P&L:            ${total_pnl:>+10,.0f}              │")
        print(f"  │  ROI:            {roi:>+8.1f}%                   │")
        print(f"  └─────────────────────────────────────────────┘")

        print(f"\n  P&L by Edge Size:")
        for edge_name, edge_bets in bets_by_edge.items():
            if edge_bets:
                pnl = sum(edge_bets)
                wins = sum(1 for b in edge_bets if b > 0)
                total = len(edge_bets)
                print(f"    {edge_name:8s}: {wins}/{total} wins | P&L: ${pnl:+,.0f}")
    else:
        print(f"\n  No bets placed (edge threshold: 3%)")
        print(f"  All matches fell below the minimum edge requirement")

    print(f"\n{'═' * 70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NemoFish Enhanced Backtest v2")
    parser.add_argument("--n", type=int, default=200, help="Number of matches to test")
    parser.add_argument("--year", type=int, default=2025, help="Test year")
    args = parser.parse_args()

    run_backtest(test_year=args.year, n_matches=args.n)
