"""
Tennis Backtest v3 — Clean Single-Side
========================================
For each match, our model predicts who wins.
We compare that prediction to market implied probability.
We only bet when: (1) edge >= threshold AND (2) model confidence >= 55%

Measures:
- Win rate (correct predictions)
- ROI at flat staking
- P&L by edge bucket
- Performance by surface, tourney level, round
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.tennis_elo import TennisEloEngine


def run_backtest():
    sackmann_dir = Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp"

    elo = TennisEloEngine(str(sackmann_dir))

    # Warmup: 2000-2019
    print("Warming up Elo (2000-2019)...")
    warmup_matches = []
    for year in range(2000, 2020):
        fp = sackmann_dir / f"atp_matches_{year}.csv"
        if fp.exists():
            df = pd.read_csv(fp, low_memory=False)
            warmup_matches.append(df)

    warm = pd.concat(warmup_matches, ignore_index=True)
    warm['tourney_date'] = pd.to_datetime(warm['tourney_date'], format='%Y%m%d', errors='coerce')
    warm = warm.dropna(subset=['tourney_date']).sort_values('tourney_date')

    for _, row in warm.iterrows():
        w, l = row.get('winner_name'), row.get('loser_name')
        if pd.notna(w) and pd.notna(l):
            elo.update_elo(w, l, row.get('surface', 'Hard'),
                          row.get('tourney_level', 'B'), str(row['tourney_date'])[:10])

    print(f"Warmed up: {len(elo.ratings)} players\n")

    # Backtest parameters
    FLAT_BET = 100
    MIN_EDGES = [0.03, 0.05, 0.08, 0.10]
    
    all_bets = []

    for year in range(2020, 2025):
        fp = sackmann_dir / f"atp_matches_{year}.csv"
        if not fp.exists():
            continue

        matches = pd.read_csv(fp, low_memory=False)
        matches['tourney_date'] = pd.to_datetime(
            matches['tourney_date'], format='%Y%m%d', errors='coerce'
        )
        matches = matches.dropna(subset=['tourney_date', 'winner_name', 'loser_name'])
        matches = matches.sort_values('tourney_date')

        for _, row in matches.iterrows():
            winner = row['winner_name']
            loser = row['loser_name']
            surface = row.get('surface', 'Hard')
            level = row.get('tourney_level', 'B')
            rnd = row.get('round', '')
            date_str = str(row['tourney_date'])[:10]
            w_rank = row.get('winner_rank')
            l_rank = row.get('loser_rank')

            if pd.isna(w_rank) or pd.isna(l_rank) or w_rank <= 0 or l_rank <= 0:
                elo.update_elo(winner, loser, surface, level, date_str)
                continue

            # Model: predict who wins
            # prob_w = probability that player listed as "winner" wins
            prob_w = elo.predict_match(winner, loser, surface)

            # Market: implied prob from rank ratio
            total_rank = w_rank + l_rank
            market_prob_w = np.clip(l_rank / total_rank, 0.05, 0.95)

            # Decide which side to bet on
            if prob_w >= 0.5:
                # Model says WINNER wins
                our_pick = winner
                our_prob = prob_w
                their_prob = market_prob_w
                market_odds = 1.0 / their_prob
                actually_won = True  # Winner won by definition
            else:
                # Model says LOSER wins (upset prediction!)  
                our_pick = loser
                our_prob = 1.0 - prob_w
                their_prob = 1.0 - market_prob_w
                market_odds = 1.0 / their_prob if their_prob > 0.01 else 50.0
                actually_won = False  # Our pick (loser) did NOT win

            edge = our_prob - their_prob

            if edge > 0 and our_prob >= 0.55:
                # Calculate P&L
                if actually_won:
                    profit = FLAT_BET * (market_odds - 1)
                else:
                    profit = -FLAT_BET

                all_bets.append({
                    'year': year,
                    'date': date_str,
                    'pick': our_pick,
                    'opponent': loser if our_pick == winner else winner,
                    'surface': surface,
                    'level': level,
                    'round': rnd,
                    'our_prob': our_prob,
                    'market_prob': their_prob,
                    'edge': edge,
                    'odds': market_odds,
                    'won': actually_won,
                    'profit': profit,
                    'bet_type': 'FAVORITE' if our_pick == winner else 'UPSET',
                })

            elo.update_elo(winner, loser, surface, level, date_str)

    df = pd.DataFrame(all_bets)
    
    # === Results by Min Edge Threshold ===
    print("=" * 70)
    print("  RESULTS BY MINIMUM EDGE THRESHOLD (Flat $100/bet)")
    print("=" * 70)
    
    for min_edge in MIN_EDGES:
        subset = df[df['edge'] >= min_edge]
        if len(subset) == 0:
            continue
        n = len(subset)
        wins = subset['won'].sum()
        wr = wins / n * 100
        total_profit = subset['profit'].sum()
        roi = total_profit / (n * FLAT_BET) * 100
        avg_odds = subset['odds'].mean()
        
        print(f"\n  Min Edge ≥ {min_edge:.0%}:")
        print(f"    Bets: {n:>5} | Wins: {wins:>5} ({wr:.1f}%)")
        print(f"    P&L:  ${total_profit:>+,.2f} | ROI: {roi:>+.1f}%")
        print(f"    Avg odds: {avg_odds:.3f} | Avg edge: {subset['edge'].mean():.1%}")
        
        # Favorites vs Upsets
        fav = subset[subset['bet_type'] == 'FAVORITE']
        ups = subset[subset['bet_type'] == 'UPSET']
        if len(fav) > 0:
            fav_wr = fav['won'].mean() * 100
            fav_roi = fav['profit'].sum() / (len(fav) * FLAT_BET) * 100
            print(f"    Favorites: {len(fav)} bets, {fav_wr:.1f}% win, ROI {fav_roi:+.1f}%")
        if len(ups) > 0:
            ups_wr = ups['won'].mean() * 100
            ups_roi = ups['profit'].sum() / (len(ups) * FLAT_BET) * 100
            print(f"    Upsets:    {len(ups)} bets, {ups_wr:.1f}% win, ROI {ups_roi:+.1f}%")

    # === Year by Year (5% edge) ===
    print(f"\n{'='*70}")
    print(f"  YEAR BY YEAR (Edge ≥ 5%)")
    print(f"{'='*70}")
    
    mid = df[df['edge'] >= 0.05]
    for year in range(2020, 2025):
        y = mid[mid['year'] == year]
        if len(y) == 0:
            continue
        n = len(y)
        wins = y['won'].sum()
        prof = y['profit'].sum()
        print(f"  {year}: {n:>4} bets | {wins:>4} wins ({wins/n*100:.1f}%) | "
              f"P&L: ${prof:>+,.2f} | ROI: {prof/(n*FLAT_BET)*100:>+.1f}%")

    # === By Surface ===
    print(f"\n{'='*70}")
    print(f"  BY SURFACE (Edge ≥ 5%)")
    print(f"{'='*70}")
    
    for surface in ['Hard', 'Clay', 'Grass']:
        s = mid[mid['surface'] == surface]
        if len(s) == 0:
            continue
        n = len(s)
        wins = s['won'].sum()
        prof = s['profit'].sum()
        print(f"  {surface:>5}: {n:>4} bets | {wins:>4} wins ({wins/n*100:.1f}%) | "
              f"P&L: ${prof:>+,.2f} | ROI: {prof/(n*FLAT_BET)*100:>+.1f}%")

    # === By Tournament Level ===
    print(f"\n{'='*70}")
    print(f"  BY TOURNAMENT LEVEL (Edge ≥ 5%)")
    print(f"{'='*70}")
    
    level_names = {'G': 'Grand Slam', 'M': 'Masters 1000', 'A': 'ATP 500',
                   'B': 'ATP 250', 'D': 'Davis Cup', 'F': 'Tour Finals'}
    for lv in ['G', 'M', 'A', 'B']:
        l = mid[mid['level'] == lv]
        if len(l) == 0:
            continue
        n = len(l)
        wins = l['won'].sum()
        prof = l['profit'].sum()
        print(f"  {level_names.get(lv, lv):>14}: {n:>4} bets | {wins:>4} wins ({wins/n*100:.1f}%) | "
              f"P&L: ${prof:>+,.2f} | ROI: {prof/(n*FLAT_BET)*100:>+.1f}%")

    # === Edge Bucket Analysis ===
    print(f"\n{'='*70}")
    print(f"  EDGE BUCKET ANALYSIS")
    print(f"{'='*70}")
    
    buckets = [(0.03, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 1.0)]
    for lo, hi in buckets:
        b = df[(df['edge'] >= lo) & (df['edge'] < hi)]
        if len(b) == 0:
            continue
        n = len(b)
        wins = b['won'].sum()
        prof = b['profit'].sum()
        roi = prof / (n * FLAT_BET) * 100
        print(f"  {lo:.0%}-{hi:.0%}: {n:>5} bets | {wins:>5} wins ({wins/n*100:.1f}%) | "
              f"P&L: ${prof:>+,.2f} | ROI: {roi:>+.1f}%")


if __name__ == "__main__":
    print("=" * 70)
    print("  NEMOFISH TENNIS BACKTEST v3 (Clean Single-Side)")
    print("  $100 flat staking | Elo Model vs Rank-Based Market")
    print("=" * 70)
    print()
    run_backtest()
