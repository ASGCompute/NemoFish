"""
Walk-Forward Validation for Tennis Betting Models
====================================================
Implements time-series-correct backtesting that avoids look-ahead bias.

Traditional k-fold cross-validation LEAKS future data into training.
Walk-forward uses a sliding window:
  - Train: past N months of data
  - Predict: next 1 week
  - Slide forward, retrain, repeat

This is the ONLY honest way to evaluate betting model ROI.

Based on: tennis_betting_recommendations.md P0 requirement #3

Usage:
    validator = WalkForwardValidator(
        model_class=TennisXGBoostModel,
        train_months=36,
        predict_days=7,
    )
    results = validator.run(start_year=2022, end_year=2024)
    validator.print_report(results)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass


@dataclass
class WalkForwardPeriod:
    """Results for a single walk-forward window."""
    period_start: str
    period_end: str
    train_matches: int
    predict_matches: int
    bets_placed: int
    correct: int
    roi: float          # Return on investment for this period
    clv: float          # Average CLV for this period
    total_staked: float
    total_return: float


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward validation results."""
    periods: List[WalkForwardPeriod]
    total_matches: int
    total_bets: int
    total_correct: int
    accuracy: float
    roi: float
    sharpe_ratio: float
    max_drawdown: float
    win_streak_max: int
    loss_streak_max: int


class WalkForwardValidator:
    """
    Walk-Forward validation engine.
    
    Prevents look-ahead bias by strictly ordering:
    Train → Predict → Slide → Retrain → Predict → ...
    """

    def __init__(
        self,
        data_dir: str = None,
        train_months: int = 36,
        predict_days: int = 7,
        min_edge: float = 0.03,
        kelly_fraction: float = 0.25,
    ):
        self.data_dir = Path(data_dir) if data_dir else \
            Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp"
        self.train_months = train_months
        self.predict_days = predict_days
        self.min_edge = min_edge
        self.kelly_fraction = kelly_fraction

    def load_matches(self, start_year: int = 2010, end_year: int = 2026) -> pd.DataFrame:
        """Load and prepare match data with odds."""
        all_data = []
        for year in range(start_year, end_year + 1):
            path = self.data_dir / f"atp_matches_{year}.csv"
            if path.exists():
                try:
                    df = pd.read_csv(path, low_memory=False)
                    all_data.append(df)
                except Exception:
                    continue

        if not all_data:
            print("❌ No match data found")
            return pd.DataFrame()

        matches = pd.concat(all_data, ignore_index=True)
        matches['tourney_date'] = pd.to_datetime(
            matches['tourney_date'], format='%Y%m%d', errors='coerce'
        )
        matches = matches.dropna(subset=['tourney_date', 'winner_name', 'loser_name'])
        matches = matches.sort_values('tourney_date').reset_index(drop=True)

        print(f"📊 Loaded {len(matches):,} matches ({start_year}-{end_year})")
        return matches

    def run(
        self,
        matches: pd.DataFrame = None,
        start_year: int = 2022,
        end_year: int = 2024,
        model_predict_fn: Callable = None,
    ) -> WalkForwardResult:
        """
        Run walk-forward validation.
        
        Args:
            matches: Pre-loaded match data (or loads automatically)
            start_year: Start of validation period
            end_year: End of validation period
            model_predict_fn: Optional custom prediction function
                             fn(train_df, test_match) -> (prob_a, edge)
        """
        if matches is None:
            matches = self.load_matches(start_year=start_year - 3, end_year=end_year)

        if matches.empty:
            return WalkForwardResult([], 0, 0, 0, 0, 0, 0, 0, 0, 0)

        # Define validation window
        val_start = pd.Timestamp(f"{start_year}-01-01")
        val_end = pd.Timestamp(f"{end_year}-12-31")

        periods = []
        current = val_start
        bankroll = 1000.0
        peak = bankroll
        max_dd = 0.0
        period_returns = []

        print(f"\n🔄 Walk-Forward: {start_year} → {end_year}")
        print(f"   Train window: {self.train_months} months")
        print(f"   Predict window: {self.predict_days} days")
        print(f"   Min edge: {self.min_edge:.0%}")

        while current < val_end:
            window_end = current + timedelta(days=self.predict_days)

            # Training data: everything before current window
            train_cutoff = current - timedelta(days=1)
            train_start = current - timedelta(days=self.train_months * 30)
            train = matches[
                (matches['tourney_date'] >= train_start) &
                (matches['tourney_date'] <= train_cutoff)
            ]

            # Test data: current window
            test = matches[
                (matches['tourney_date'] >= current) &
                (matches['tourney_date'] < window_end)
            ]

            if len(test) == 0:
                current = window_end
                continue

            # Simple Elo-based prediction for walk-forward
            bets = 0
            correct = 0
            staked = 0.0
            returned = 0.0

            # Build Elo from training data
            from models.tennis_elo import TennisEloEngine
            elo = TennisEloEngine()

            for _, row in train.iterrows():
                w = row.get('winner_name')
                l = row.get('loser_name')
                s = row.get('surface', 'Hard')
                lvl = row.get('tourney_level', 'B')
                d = str(row.get('tourney_date', ''))[:10]
                score = str(row.get('score', '')) if pd.notna(row.get('score')) else None
                if pd.notna(w) and pd.notna(l):
                    elo.update_elo(w, l, s, lvl, d, score=score)

            # Predict each test match
            for _, row in test.iterrows():
                w = row.get('winner_name')
                l = row.get('loser_name')
                surface = row.get('surface', 'Hard')

                if pd.isna(w) or pd.isna(l):
                    continue

                # Get odds if available
                odds_w = row.get('AvgW') or row.get('B365W')
                odds_l = row.get('AvgL') or row.get('B365L')

                if not odds_w or not odds_l or pd.isna(odds_w) or pd.isna(odds_l):
                    continue

                odds_w = float(odds_w)
                odds_l = float(odds_l)

                # Model prediction
                prob_a = elo.predict_match(w, l, surface)

                # Check edge for both players
                implied_a = 1.0 / odds_w if odds_w > 0 else 0.5
                implied_b = 1.0 / odds_l if odds_l > 0 else 0.5

                edge_a = prob_a - implied_a
                edge_b = (1 - prob_a) - implied_b

                if edge_a > self.min_edge:
                    # Bet on winner
                    kelly = max(0, (prob_a * (odds_w - 1) - (1 - prob_a)) / (odds_w - 1))
                    bet = self.kelly_fraction * kelly * bankroll
                    bet = min(bet, bankroll * 0.05)  # Max 5% per bet

                    if bet > 0:
                        bets += 1
                        staked += bet
                        # Winner is always player A in this data
                        correct += 1
                        returned += bet * odds_w
                        bankroll += bet * (odds_w - 1)

                elif edge_b > self.min_edge:
                    # Bet on loser
                    kelly = max(0, ((1-prob_a) * (odds_l - 1) - prob_a) / (odds_l - 1))
                    bet = self.kelly_fraction * kelly * bankroll
                    bet = min(bet, bankroll * 0.05)

                    if bet > 0:
                        bets += 1
                        staked += bet
                        # Loser lost, so our bet lost
                        bankroll -= bet

                # Update Elo with this match result
                score = str(row.get('score', '')) if pd.notna(row.get('score')) else None
                elo.update_elo(w, l, surface, row.get('tourney_level', 'B'),
                             str(row.get('tourney_date', ''))[:10], score=score)

            # Record period
            roi = ((returned - staked) / staked) if staked > 0 else 0
            period_returns.append(roi)

            # Track drawdown
            peak = max(peak, bankroll)
            dd = (peak - bankroll) / peak
            max_dd = max(max_dd, dd)

            periods.append(WalkForwardPeriod(
                period_start=current.strftime('%Y-%m-%d'),
                period_end=window_end.strftime('%Y-%m-%d'),
                train_matches=len(train),
                predict_matches=len(test),
                bets_placed=bets,
                correct=correct,
                roi=roi,
                clv=0.0,
                total_staked=staked,
                total_return=returned,
            ))

            current = window_end

        # Aggregate
        total_bets = sum(p.bets_placed for p in periods)
        total_correct = sum(p.correct for p in periods)
        total_matches = sum(p.predict_matches for p in periods)
        accuracy = total_correct / total_bets if total_bets > 0 else 0

        total_staked = sum(p.total_staked for p in periods)
        total_returned = sum(p.total_return for p in periods)
        overall_roi = ((total_returned - total_staked) / total_staked) if total_staked > 0 else 0

        # Sharpe ratio
        if period_returns:
            mean_r = np.mean(period_returns)
            std_r = np.std(period_returns) if len(period_returns) > 1 else 1
            sharpe = (mean_r / std_r) * np.sqrt(52) if std_r > 0 else 0
        else:
            sharpe = 0

        return WalkForwardResult(
            periods=periods,
            total_matches=total_matches,
            total_bets=total_bets,
            total_correct=total_correct,
            accuracy=accuracy,
            roi=overall_roi,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_streak_max=0,
            loss_streak_max=0,
        )

    def print_report(self, result: WalkForwardResult):
        """Print formatted walk-forward validation report."""
        print("\n" + "═" * 60)
        print("  📊 WALK-FORWARD VALIDATION REPORT")
        print("═" * 60)
        print(f"  Periods analyzed:  {len(result.periods)}")
        print(f"  Total matches:     {result.total_matches:,}")
        print(f"  Total bets:        {result.total_bets}")
        print(f"  Accuracy:          {result.accuracy:.1%}")
        print(f"  ROI:               {result.roi:+.2%}")
        print(f"  Sharpe Ratio:      {result.sharpe_ratio:.2f}")
        print(f"  Max Drawdown:      {result.max_drawdown:.1%}")

        if result.roi > 0.02:
            print(f"\n  🟢 PROFITABLE — ROI {result.roi:+.2%}")
        elif result.roi > 0:
            print(f"\n  🟡 MARGINAL — ROI {result.roi:+.2%}")
        else:
            print(f"\n  🔴 UNPROFITABLE — ROI {result.roi:+.2%}")
        print("═" * 60)

        # Per-quarter breakdown
        if result.periods:
            print("\n  Quarterly breakdown:")
            quarter_data = {}
            for p in result.periods:
                q = p.period_start[:7]  # YYYY-MM
                if q not in quarter_data:
                    quarter_data[q] = {'bets': 0, 'staked': 0, 'returned': 0}
                quarter_data[q]['bets'] += p.bets_placed
                quarter_data[q]['staked'] += p.total_staked
                quarter_data[q]['returned'] += p.total_return

            for month, d in sorted(quarter_data.items())[:12]:
                roi = ((d['returned'] - d['staked']) / d['staked']) if d['staked'] > 0 else 0
                bar = "█" * max(0, int(roi * 100)) if roi > 0 else "░" * max(0, int(-roi * 100))
                print(f"    {month}: {d['bets']:3d} bets | ROI {roi:+.1%} {bar}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    validator = WalkForwardValidator(train_months=36, predict_days=7)
    result = validator.run(start_year=2023, end_year=2024)
    validator.print_report(result)
