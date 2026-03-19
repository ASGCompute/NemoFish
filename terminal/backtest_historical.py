#!/usr/bin/env python3
"""
NemoFish Historical Backtester v3 — Multi-Strategy
====================================================
Enhanced backtest with pluggable strategy architecture:
  ✅ Surface-specific Elo (already in engine)
  ✅ Real P&L from betting odds (B365, Pinnacle, Max, Avg)
  ✅ Rookie detection (low-match players → reduced confidence)
  ✅ 2025-2026 data support
  ✅ Multiple strategies tested in parallel
  ✅ ATPBetting two-pass confidence filtering
  ✅ Side-by-side comparison report

No data leakage:
  1. Elo trained on 2000 → (test_year - 1)
  2. Out-of-sample test on last N matches of test_year
  3. Random player slot assignment (no winner bias)

Usage:
  python3 terminal/backtest_historical.py --n 200 --year 2025
  python3 terminal/backtest_historical.py --n 200 --year 2026
  python3 terminal/backtest_historical.py --n 200 --year 2025 --strategies all
"""

import sys
import csv
import argparse
import random
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional
from collections import defaultdict

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from models.tennis_elo import TennisEloEngine
from agents.tennis_swarm import TennisSwarm, MatchContext
from strategies.strategy_base import BettingStrategy, BetDecision, MatchInput
from strategies.value_confirmation import ValueConfirmationStrategy
from strategies.atp_confidence import ATPConfidenceStrategy
from strategies.edge_threshold import EdgeThresholdStrategy
from strategies.kelly_strategy import KellyStrategy
from strategies.skemp_value import (
    SkempValueOnlyStrategy,
    SkempPredictedWinValueStrategy,
    SkempInverseStrategy,
)


# --- Rookie threshold ---
ROOKIE_MATCH_THRESHOLD = 15


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
    odds_winner_b365: Optional[float] = None
    odds_loser_b365: Optional[float] = None
    odds_winner_avg: Optional[float] = None
    odds_loser_avg: Optional[float] = None
    odds_winner_max: Optional[float] = None
    odds_loser_max: Optional[float] = None


def load_test_matches(data_dir: str, year: int, n: int, main_tour_only: bool = True) -> List[HistoricalMatch]:
    """Load the last N matches from a year's CSV."""
    csv_path = Path(data_dir) / f"atp_matches_{year}.csv"
    odds_path = Path(data_dir) / f"atp_odds_{year}.csv"

    if not csv_path.exists():
        print(f"❌ File not found: {csv_path}")
        return []

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
            if main_tour_only and level not in ('G', 'M', 'A', 'B', 'F'):
                continue

            try:
                w_rank = int(float(row.get('winner_rank', 999) or 999))
            except:
                w_rank = 999
            try:
                l_rank = int(float(row.get('loser_rank', 999) or 999))
            except:
                l_rank = 999

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

    if len(matches) > n:
        matches = matches[-n:]

    return matches


def is_rookie(engine: TennisEloEngine, player_name: str) -> bool:
    """Check if player is a rookie (too few matches in our Elo DB)."""
    rating = engine.get_player(player_name)
    if not rating:
        return True
    return rating.matches_played < ROOKIE_MATCH_THRESHOLD


def get_default_strategies() -> List[BettingStrategy]:
    """Get all default strategies for multi-strategy testing."""
    return [
        ValueConfirmationStrategy(min_model_prob=0.55),
        ATPConfidenceStrategy(top_pct=0.05),
        ATPConfidenceStrategy(top_pct=0.10),
        ATPConfidenceStrategy(top_pct=0.15),
        EdgeThresholdStrategy(min_edge=0.03, max_edge=0.30),
        EdgeThresholdStrategy(min_edge=0.05, max_edge=0.20),
        KellyStrategy(kelly_fraction=0.25, bankroll=20),
        # skemp15/Tennis-Betting-Model strategies
        SkempValueOnlyStrategy(),
        SkempPredictedWinValueStrategy(),
        SkempInverseStrategy(),
    ]


def run_backtest(test_year: int = 2025, n_matches: int = 200, strategies: List[BettingStrategy] = None):
    """Run the full multi-strategy backtest."""

    if strategies is None:
        strategies = get_default_strategies()

    print("═" * 70)
    print("  🐡 NEMOFISH — MULTI-STRATEGY BACKTEST v3")
    print(f"  Testing on last {n_matches} ATP matches of {test_year}")
    print(f"  Elo trained on: 2000 – {test_year - 1} (NO data leakage)")
    print(f"  Strategies: {len(strategies)}")
    for s in strategies:
        print(f"    • {s.name}: {s.description}")
    print("═" * 70)

    data_dir = str(ROOT / "data" / "tennis" / "tennis_atp")

    # === STEP 1: Train Elo ===
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

    has_odds = sum(1 for m in test_matches if m.odds_winner_avg is not None)
    print(f"   📊 {has_odds}/{len(test_matches)} matches have betting odds")

    if not test_matches:
        print("❌ No test matches found!")
        return

    # === STEP 4: Run predictions + strategy evaluations ===
    print(f"\n🎾 Running predictions (blind — no result knowledge)...\n")

    # Track per-strategy results
    strategy_tracker: Dict[str, dict] = {}
    for s in strategies:
        strategy_tracker[s.name] = {
            "decisions": [],      # BetDecision for each match
            "bet_count": 0,
            "bet_correct": 0,
            "total_pnl": 0.0,
            "total_wagered": 0.0,
            "pnl_history": [],
        }

    # Also track prediction accuracy
    total_correct = 0
    rookie_count = 0
    results = []  # Per-match result details

    for i, match in enumerate(test_matches):
        # Random player assignment
        random.seed(hash(match.winner_name + match.loser_name + match.tourney_date))

        if random.random() > 0.5:
            player_a, player_b = match.winner_name, match.loser_name
            rank_a, rank_b = match.winner_rank, match.loser_rank
            seed_a, seed_b = match.winner_seed, match.loser_seed
            actual_winner = "A"
            odds_a = match.odds_winner_avg
            odds_b = match.odds_loser_avg
        else:
            player_a, player_b = match.loser_name, match.winner_name
            rank_a, rank_b = match.loser_rank, match.winner_rank
            seed_a, seed_b = match.loser_seed, match.winner_seed
            actual_winner = "B"
            odds_a = match.odds_loser_avg
            odds_b = match.odds_winner_avg

        # Rookie detection
        a_is_rookie = is_rookie(elo_engine, player_a)
        b_is_rookie = is_rookie(elo_engine, player_b)
        has_rookie_flag = a_is_rookie or b_is_rookie
        if has_rookie_flag:
            rookie_count += 1

        # Build context for swarm
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

        # Adjust confidence for rookies
        confidence = prediction.confidence
        if has_rookie_flag and confidence == "HIGH":
            confidence = "MEDIUM"

        # Check prediction accuracy
        predicted_winner = "A" if prediction.prob_a >= 0.5 else "B"
        correct = (predicted_winner == actual_winner)
        if correct:
            total_correct += 1

        # Build standardized MatchInput for strategies
        match_input = MatchInput(
            player_a=player_a,
            player_b=player_b,
            prob_a=prediction.prob_a,
            prob_b=prediction.prob_b,
            odds_a=odds_a,
            odds_b=odds_b,
            surface=match.surface or "Hard",
            tourney_name=match.tourney_name,
            tourney_level=match.tourney_level,
            round_name=match.round_name,
            confidence=confidence,
            has_rookie=has_rookie_flag,
            kelly_raw=prediction.kelly_bet_size if hasattr(prediction, 'kelly_bet_size') else 0.0,
        )

        # Evaluate each strategy (Phase 1 for two-pass strategies)
        for s in strategies:
            decision = s.evaluate_match(match_input)
            strategy_tracker[s.name]["decisions"].append(decision)

        # Display prediction
        prob_display = prediction.prob_a if predicted_winner == "A" else prediction.prob_b
        correct_icon = "✅" if correct else "❌"
        rookie_icon = " 🆕" if has_rookie_flag else ""
        actual_name = player_a if actual_winner == "A" else player_b
        predicted_name = player_a if predicted_winner == "A" else player_b

        print(f"  {i+1:3d}. {correct_icon} {player_a} vs {player_b}")
        print(f"       → {predicted_name} ({prob_display:.0%}) | ✓ {actual_name} | {confidence}{rookie_icon}")

        results.append({
            "match": f"{player_a} vs {player_b}",
            "tournament": match.tourney_name,
            "surface": match.surface,
            "round": match.round_name,
            "predicted": predicted_name,
            "predicted_prob": round(prob_display, 4),
            "actual": actual_name,
            "actual_winner": actual_winner,
            "correct": correct,
            "confidence": confidence,
            "has_rookie": has_rookie_flag,
            "odds_a": odds_a,
            "odds_b": odds_b,
        })

    # === STEP 5: Phase 2 — Apply ATPBetting top-N% filter ===
    for s in strategies:
        if isinstance(s, ATPConfidenceStrategy):
            decisions = strategy_tracker[s.name]["decisions"]
            filtered = ATPConfidenceStrategy.filter_top_n(decisions, s.top_pct)
            strategy_tracker[s.name]["decisions"] = filtered

    # === STEP 6: Compute P&L for each strategy ===
    for s in strategies:
        tracker = strategy_tracker[s.name]
        for idx, decision in enumerate(tracker["decisions"]):
            if not decision.should_bet:
                continue

            r = results[idx]
            actual_winner = r["actual_winner"]

            tracker["bet_count"] += 1
            tracker["total_wagered"] += decision.bet_size

            bet_won = (decision.pick == actual_winner)
            if bet_won:
                pnl = decision.bet_size * (decision.our_odds - 1)
                tracker["bet_correct"] += 1
            else:
                pnl = -decision.bet_size

            tracker["total_pnl"] += pnl
            tracker["pnl_history"].append(pnl)

    # === STEP 7: Print Report ===
    accuracy = total_correct / len(test_matches) * 100 if test_matches else 0

    # Accuracy breakdown by confidence
    by_conf = {}
    for r in results:
        c = r["confidence"]
        if c not in by_conf:
            by_conf[c] = {"total": 0, "correct": 0}
        by_conf[c]["total"] += 1
        if r["correct"]:
            by_conf[c]["correct"] += 1

    # Accuracy breakdown by surface
    by_surface = {}
    for r in results:
        s = r["surface"]
        if s not in by_surface:
            by_surface[s] = {"total": 0, "correct": 0}
        by_surface[s]["total"] += 1
        if r["correct"]:
            by_surface[s]["correct"] += 1

    non_rookie_correct = sum(1 for r in results if r["correct"] and not r["has_rookie"])
    non_rookie_total = sum(1 for r in results if not r["has_rookie"])
    non_rookie_acc = non_rookie_correct / non_rookie_total * 100 if non_rookie_total > 0 else 0

    print(f"\n{'═' * 70}")
    print(f"  📊 NEMOFISH BACKTEST RESULTS v3 — MULTI-STRATEGY")
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
    for s_name in ["Hard", "Clay", "Grass", "Carpet"]:
        if s_name in by_surface:
            d = by_surface[s_name]
            acc = d["correct"] / d["total"] * 100
            print(f"    {s_name:8s}: {d['correct']:3d}/{d['total']:3d} = {acc:.0f}%")

    print(f"\n  🆕 Rookie Impact:")
    print(f"    Matches with rookies:    {rookie_count} ({rookie_count/len(test_matches)*100:.0f}%)" if test_matches else "")
    print(f"    Non-rookie accuracy:     {non_rookie_correct}/{non_rookie_total} = {non_rookie_acc:.0f}%")

    # === STRATEGY COMPARISON TABLE ===
    print(f"\n{'═' * 70}")
    print(f"  💰 STRATEGY COMPARISON — REAL P&L")
    print(f"{'═' * 70}")
    print(f"\n  {'Strategy':<30} {'Bets':>5} {'Wins':>5} {'WR':>6} {'Wagered':>10} {'P&L':>10} {'ROI':>8}")
    print(f"  {'─'*30} {'─'*5} {'─'*5} {'─'*6} {'─'*10} {'─'*10} {'─'*8}")

    for s in strategies:
        t = strategy_tracker[s.name]
        if t["bet_count"] > 0:
            wr = t["bet_correct"] / t["bet_count"] * 100
            roi = t["total_pnl"] / t["total_wagered"] * 100 if t["total_wagered"] > 0 else 0
            pnl_icon = "📈" if t["total_pnl"] > 0 else "📉"
            print(f"  {s.name:<30} {t['bet_count']:>5} {t['bet_correct']:>5} {wr:>5.1f}% ${t['total_wagered']:>9,.0f} ${t['total_pnl']:>+9,.0f} {roi:>+7.1f}%  {pnl_icon}")
        else:
            print(f"  {s.name:<30} {'—':>5} {'—':>5} {'—':>6} {'—':>10} {'—':>10} {'—':>8}")

    # Find best strategy
    best = None
    best_roi = -float('inf')
    for s in strategies:
        t = strategy_tracker[s.name]
        if t["bet_count"] > 0:
            roi = t["total_pnl"] / t["total_wagered"] * 100
            if roi > best_roi:
                best_roi = roi
                best = s.name

    if best:
        print(f"\n  🏆 BEST STRATEGY: {best} (ROI: {best_roi:+.1f}%)")

    # Per-strategy detail
    for s in strategies:
        t = strategy_tracker[s.name]
        if t["bet_count"] > 0 and t["pnl_history"]:
            import numpy as np
            pnl_arr = np.array(t["pnl_history"])
            # Max drawdown
            cumulative = np.cumsum(pnl_arr)
            peak = np.maximum.accumulate(cumulative)
            drawdown = peak - cumulative
            max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0

            # Sharpe (per-bet)
            mean_ret = float(pnl_arr.mean())
            std_ret = float(pnl_arr.std()) if len(pnl_arr) > 1 else 1.0
            sharpe = mean_ret / std_ret if std_ret > 0 else 0

            print(f"\n  📊 {s.name}:")
            print(f"     Max Drawdown: ${max_dd:,.0f}")
            print(f"     Avg P&L/bet:  ${mean_ret:+,.1f}")
            print(f"     Sharpe Ratio: {sharpe:.3f}")

    # === STEP 8: Save JSON results with validation ===
    import json as _json
    from datetime import datetime as _dt
    from strategies.strategy_validator import validate_strategy

    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "execution" / "runs" / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    json_results = {
        "timestamp": _dt.now().isoformat(),
        "test_year": test_year,
        "n_matches": len(test_matches),
        "matches_with_odds": has_odds,
        "prediction_accuracy": round(accuracy, 1),
        "strategies": {},
    }

    for s in strategies:
        t = strategy_tracker[s.name]
        if t["bet_count"] > 0 and t["pnl_history"]:
            import numpy as np
            pnl_arr = np.array(t["pnl_history"])
            cumulative = np.cumsum(pnl_arr)
            peak = np.maximum.accumulate(cumulative)
            drawdown = peak - cumulative
            max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0
            mean_ret = float(pnl_arr.mean())
            std_ret = float(pnl_arr.std()) if len(pnl_arr) > 1 else 1.0
            sharpe = mean_ret / std_ret if std_ret > 0 else 0
            roi = t["total_pnl"] / t["total_wagered"] * 100 if t["total_wagered"] > 0 else 0

            # Validate
            v = validate_strategy(
                name=s.name,
                bets=t["bet_count"],
                wins=t["bet_correct"],
                roi=roi,
                sharpe=sharpe,
                max_drawdown=max_dd,
                wagered=t["total_wagered"],
                pnl=t["total_pnl"],
            )

            json_results["strategies"][s.name] = {
                "bets": t["bet_count"],
                "wins": t["bet_correct"],
                "win_rate": round(t["bet_correct"] / t["bet_count"] * 100, 1),
                "wagered": round(t["total_wagered"], 2),
                "pnl": round(t["total_pnl"], 2),
                "roi": round(roi, 1),
                "sharpe": round(sharpe, 3),
                "max_drawdown": round(max_dd, 2),
                "avg_pnl_per_bet": round(mean_ret, 2),
                "validation": {
                    "passes": v.passes,
                    "status": v.status,
                    "fail_reasons": v.fail_reasons,
                },
            }
        else:
            json_results["strategies"][s.name] = {
                "bets": 0, "wins": 0, "roi": 0, "sharpe": 0,
                "max_drawdown": 0, "wagered": 0, "pnl": 0,
                "validation": {
                    "passes": False,
                    "status": "research",
                    "fail_reasons": ["no_bets"],
                },
            }

    results_path = run_dir / "backtest_results.json"
    results_path.write_text(_json.dumps(json_results, indent=2, default=str))
    print(f"\n  💾 Results saved: {results_path}")

    # Also save as latest for easy access
    latest_path = ROOT / "execution" / "backtest_results.json"
    latest_path.write_text(_json.dumps(json_results, indent=2, default=str))
    print(f"  💾 Latest copy: {latest_path}")

    # Print validation summary
    print(f"\n  🔬 VALIDATION SUMMARY")
    print(f"  {'─' * 50}")
    for sname, sdata in json_results["strategies"].items():
        v = sdata["validation"]
        icon = "✅" if v["passes"] else "❌"
        reason = f" ({'; '.join(v['fail_reasons'])})" if v['fail_reasons'] else ""
        print(f"  {icon} {sname}: {v['status']}{reason}")

    print(f"\n{'═' * 70}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NemoFish Multi-Strategy Backtest v3")
    parser.add_argument("--n", type=int, default=200, help="Number of matches to test")
    parser.add_argument("--year", type=int, default=2025, help="Test year")
    parser.add_argument("--strategies", type=str, default="all",
                        help="Which strategies to test: all, confirm, atp, edge, kelly, skemp, inverse")
    args = parser.parse_args()

    # Parse strategy selection
    strats = None
    if args.strategies != "all":
        strats = []
        for name in args.strategies.split(","):
            name = name.strip().lower()
            if name == "confirm":
                strats.append(ValueConfirmationStrategy())
            elif name == "atp":
                strats.append(ATPConfidenceStrategy(top_pct=0.10))
            elif name == "edge":
                strats.append(EdgeThresholdStrategy())
            elif name == "kelly":
                strats.append(KellyStrategy())
            elif name == "skemp":
                strats.append(SkempPredictedWinValueStrategy())
            elif name == "value":
                strats.append(SkempValueOnlyStrategy())
            elif name == "inverse":
                strats.append(SkempInverseStrategy())

    run_backtest(test_year=args.year, n_matches=args.n, strategies=strats)
