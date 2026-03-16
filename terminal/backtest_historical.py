#!/usr/bin/env python3
"""
NemoFish Historical Backtester
================================
Validates swarm prediction accuracy on REAL historical matches.

Methodology (no data leakage):
  1. Train Elo engine on matches from 2000 to (test_year - 1)
  2. Load JeffSackmann data up to (test_year - 1)  
  3. Take last N matches from test_year as out-of-sample set
  4. For each match: swarm predicts WITHOUT knowing the result
  5. Compare prediction to actual outcome
  6. Calculate accuracy, P&L, ROI

Usage:
  python3 terminal/backtest_historical.py              # Last 50 ATP matches of 2024
  python3 terminal/backtest_historical.py --n 100      # Last 100 matches
  python3 terminal/backtest_historical.py --year 2023  # Test on 2023
"""

import sys
import csv
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from models.tennis_elo import TennisEloEngine
from agents.tennis_swarm import TennisSwarm, MatchContext


@dataclass
class HistoricalMatch:
    """A match from the JeffSackmann CSV."""
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


def load_test_matches(data_dir: str, year: int, n: int, main_tour_only: bool = True) -> List[HistoricalMatch]:
    """Load the last N matches from a year's CSV."""
    csv_path = Path(data_dir) / f"atp_matches_{year}.csv"
    if not csv_path.exists():
        print(f"❌ File not found: {csv_path}")
        return []

    matches = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            level = row.get('tourney_level', '')
            
            # Filter to main tour only (G=Grand Slam, M=Masters, A=ATP500, B=ATP250)
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
            ))

    # Take last N matches (sorted by tourney_date in CSV)
    if len(matches) > n:
        matches = matches[-n:]
    
    return matches


def run_backtest(test_year: int = 2024, n_matches: int = 50):
    """Run the full historical backtest."""

    print("═" * 70)
    print("  🐡 NEMOFISH — HISTORICAL BACKTEST")
    print(f"  Testing on last {n_matches} ATP main-tour matches of {test_year}")
    print(f"  Elo trained on: 2000 – {test_year - 1} (NO data leakage)")
    print("═" * 70)

    data_dir = str(ROOT / "data" / "tennis" / "tennis_atp")

    # === STEP 1: Train Elo on data BEFORE test year ===
    print(f"\n⏳ Training Elo engine (2000–{test_year - 1})...")
    elo_engine = TennisEloEngine(data_dir)
    elo_engine.load_and_process(start_year=2000, end_year=test_year - 1)
    print(f"   ✅ {len(elo_engine.ratings)} players rated")

    # === STEP 2: Initialize swarm with pre-test Elo ===
    print("\n🧠 Initializing swarm (no test-year data)...")
    swarm = TennisSwarm(elo_engine=elo_engine)
    print(f"   ✅ Swarm ready | Sackmann: {'loaded' if swarm.sackmann else 'unavailable'}")

    # === STEP 3: Load test matches ===
    print(f"\n📋 Loading test matches from {test_year}...")
    test_matches = load_test_matches(data_dir, test_year, n_matches)
    print(f"   ✅ {len(test_matches)} matches loaded for testing")

    if not test_matches:
        print("❌ No test matches found!")
        return

    # Show sample
    print(f"\n   First: {test_matches[0].winner_name} def {test_matches[0].loser_name} ({test_matches[0].tourney_name})")
    print(f"   Last:  {test_matches[-1].winner_name} def {test_matches[-1].loser_name} ({test_matches[-1].tourney_name})")

    # === STEP 4: Predict each match WITHOUT knowing result ===
    print(f"\n🎾 Running swarm predictions (blind — no result knowledge)...\n")

    results = []
    total_correct = 0
    total_bet_correct = 0
    total_bet_count = 0
    total_pnl = 0.0
    total_wagered = 0.0

    for i, match in enumerate(test_matches):
        # CRITICAL: Randomly assign player_a / player_b
        # (in the CSV, winner is always first — we must not leak this)
        # Simulate: swarm sees playerA vs playerB, doesn't know who won
        import random
        random.seed(hash(match.winner_name + match.loser_name + match.tourney_date))
        
        if random.random() > 0.5:
            player_a = match.winner_name
            player_b = match.loser_name
            rank_a = match.winner_rank
            rank_b = match.loser_rank
            seed_a = match.winner_seed
            seed_b = match.loser_seed
            actual_winner = "A"
        else:
            player_a = match.loser_name
            player_b = match.winner_name
            rank_a = match.loser_rank
            rank_b = match.winner_rank
            seed_a = match.loser_seed
            seed_b = match.winner_seed
            actual_winner = "B"

        # Build context (as if we're predicting before the match)
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

        # Determine if prediction was correct
        predicted_winner = "A" if prediction.prob_a >= 0.5 else "B"
        correct = (predicted_winner == actual_winner)
        if correct:
            total_correct += 1

        # Simulate betting (if swarm recommends BET)
        bet_result = None
        bet_pnl = 0.0
        if prediction.recommended_action != "SKIP":
            total_bet_count += 1
            bet_size = min(prediction.kelly_bet_size, 50.0)  # Cap at $50
            total_wagered += bet_size

            # Determine if we bet on the right side
            if prediction.recommended_action == "BET_A":
                bet_won = (actual_winner == "A")
            else:
                bet_won = (actual_winner == "B")

            if bet_won:
                # Simplified: win at fair odds
                win_prob = max(prediction.prob_a, prediction.prob_b)
                payout = bet_size / win_prob  # Fair odds payout
                bet_pnl = payout - bet_size
                total_bet_correct += 1
            else:
                bet_pnl = -bet_size

            total_pnl += bet_pnl
            bet_result = "WON" if bet_won else "LOST"

        # Display
        prob_display = prediction.prob_a if predicted_winner == "A" else prediction.prob_b
        correct_icon = "✅" if correct else "❌"
        bet_icon = ""
        if bet_result:
            bet_icon = f" | 💰 {bet_result} ${bet_pnl:+.1f}"
        
        # Show the actual winner name for clarity
        actual_name = player_a if actual_winner == "A" else player_b
        predicted_name = player_a if predicted_winner == "A" else player_b

        print(f"  {i+1:2d}. {correct_icon} {player_a} vs {player_b}")
        print(f"      Predicted: {predicted_name} ({prob_display:.0%}) | Actual: {actual_name} | {prediction.confidence}{bet_icon}")

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
            "confidence": prediction.confidence,
            "bet_result": bet_result,
            "bet_pnl": round(bet_pnl, 2),
        })

    # === STEP 5: Report ===
    accuracy = total_correct / len(test_matches) * 100
    
    # Accuracy by confidence level
    by_conf = {}
    for r in results:
        c = r["confidence"]
        if c not in by_conf:
            by_conf[c] = {"total": 0, "correct": 0}
        by_conf[c]["total"] += 1
        if r["correct"]:
            by_conf[c]["correct"] += 1

    print(f"\n{'═' * 70}")
    print(f"  📊 BACKTEST RESULTS")
    print(f"{'═' * 70}")
    print(f"\n  Test Set: {len(test_matches)} ATP main-tour matches ({test_year})")
    print(f"  Elo Training: 2000–{test_year - 1} (out-of-sample)")
    print(f"\n  ┌─────────────────────────────────────────────┐")
    print(f"  │  PREDICTION ACCURACY:  {accuracy:.1f}%                │")
    print(f"  │  Correct: {total_correct}/{len(test_matches)}                            │")
    print(f"  └─────────────────────────────────────────────┘")
    
    print(f"\n  Accuracy by Confidence:")
    for conf in ["ELITE", "HIGH", "MEDIUM", "LOW"]:
        if conf in by_conf:
            d = by_conf[conf]
            acc = d["correct"] / d["total"] * 100 if d["total"] > 0 else 0
            print(f"    {conf:8s}: {d['correct']}/{d['total']} = {acc:.0f}%")
    
    if total_bet_count > 0:
        bet_accuracy = total_bet_correct / total_bet_count * 100
        roi = (total_pnl / total_wagered * 100) if total_wagered > 0 else 0
        print(f"\n  ┌─────────────────────────────────────────────┐")
        print(f"  │  BETTING PERFORMANCE:                       │")
        print(f"  │  Bets Placed:    {total_bet_count:3d}                        │")
        print(f"  │  Win Rate:       {bet_accuracy:.1f}%                      │")
        print(f"  │  Total Wagered:  ${total_wagered:,.2f}                │")
        print(f"  │  P&L:            ${total_pnl:+,.2f}                │")
        print(f"  │  ROI:            {roi:+.1f}%                       │")
        print(f"  └─────────────────────────────────────────────┘")
    else:
        print(f"\n  No BET signals generated (all matches below edge threshold)")
        print(f"  This is expected for most matches — the swarm is conservative")

    print(f"\n  Surface Breakdown:")
    surfaces = {}
    for r in results:
        s = r["surface"]
        if s not in surfaces:
            surfaces[s] = {"total": 0, "correct": 0}
        surfaces[s]["total"] += 1
        if r["correct"]:
            surfaces[s]["correct"] += 1
    for s, d in sorted(surfaces.items()):
        acc = d["correct"] / d["total"] * 100
        print(f"    {s:8s}: {d['correct']}/{d['total']} = {acc:.0f}%")

    print(f"\n  Round Breakdown:")
    rounds = {}
    for r in results:
        rd = r["round"]
        if rd not in rounds:
            rounds[rd] = {"total": 0, "correct": 0}
        rounds[rd]["total"] += 1
        if r["correct"]:
            rounds[rd]["correct"] += 1
    for rd in ["F", "SF", "QF", "R16", "R32", "R64", "R128", "RR"]:
        if rd in rounds:
            d = rounds[rd]
            acc = d["correct"] / d["total"] * 100
            print(f"    {rd:8s}: {d['correct']}/{d['total']} = {acc:.0f}%")

    print(f"\n{'═' * 70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NemoFish Historical Backtest")
    parser.add_argument("--n", type=int, default=50, help="Number of matches to test")
    parser.add_argument("--year", type=int, default=2024, help="Test year")
    args = parser.parse_args()
    
    run_backtest(test_year=args.year, n_matches=args.n)
