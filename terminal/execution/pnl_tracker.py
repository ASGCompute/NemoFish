"""
NemoFish P&L Tracker
=====================
Persistent trade journal and performance analytics.
Saves all trades to JSON for analysis and reporting.

Metrics:
  - Cumulative P&L (USD + BTC equivalent)
  - Win rate by sport, surface, confidence level
  - Sharpe ratio, max drawdown, Kelly ratio
  - Rolling 30-day performance
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path
import numpy as np


@dataclass
class Trade:
    """A completed trade record."""
    id: str
    timestamp: str
    sport: str
    event: str
    match: str
    pick: str
    odds: float
    model_prob: float
    market_prob: float
    edge: float
    confidence: str
    bet_size: float
    won: bool
    pnl: float
    bankroll_after: float
    surface: str = ""
    round_name: str = ""
    source: str = "swarm"
    notes: str = ""


class PnLTracker:
    """
    Persistent P&L tracker with analytics.
    
    Usage:
        tracker = PnLTracker(initial_bankroll=5000)
        tracker.record_trade(trade)
        tracker.display_dashboard()
        tracker.save()
    """

    def __init__(
        self,
        initial_bankroll: float = 5000.0,
        data_dir: str = None,
        btc_price: float = 71754.0,  # Current BTC price for conversion
    ):
        self.initial_bankroll = initial_bankroll
        self.bankroll = initial_bankroll
        self.btc_price = btc_price
        self.trades: List[Trade] = []

        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "data")
        self.data_dir = data_dir
        self.journal_path = os.path.join(data_dir, "trade_journal.json")

        os.makedirs(data_dir, exist_ok=True)
        self._load()

    def _load(self):
        """Load trade journal from disk."""
        if os.path.exists(self.journal_path):
            try:
                with open(self.journal_path, 'r') as f:
                    data = json.load(f)
                self.trades = [Trade(**t) for t in data.get('trades', [])]
                self.bankroll = data.get('bankroll', self.initial_bankroll)
                self.initial_bankroll = data.get('initial_bankroll', self.initial_bankroll)
                print(f"Loaded {len(self.trades)} trades from journal")
            except Exception as e:
                print(f"Failed to load journal: {e}")

    def save(self):
        """Save trade journal to disk."""
        data = {
            'initial_bankroll': self.initial_bankroll,
            'bankroll': round(self.bankroll, 2),
            'btc_price': self.btc_price,
            'last_updated': datetime.now().isoformat(),
            'trades': [asdict(t) for t in self.trades],
        }
        with open(self.journal_path, 'w') as f:
            json.dump(data, f, indent=2)

    def record_trade(self, trade: Trade):
        """Record a completed trade."""
        self.trades.append(trade)
        self.bankroll = trade.bankroll_after
        self.save()

    def record_result(
        self,
        trade_id: str, sport: str, event: str, match: str,
        pick: str, odds: float, model_prob: float, market_prob: float,
        edge: float, confidence: str, bet_size: float, won: bool,
        surface: str = "", round_name: str = "", notes: str = "",
    ) -> Trade:
        """Quick-record a trade result."""
        pnl = bet_size * (odds - 1) if won else -bet_size
        self.bankroll += pnl

        trade = Trade(
            id=trade_id,
            timestamp=datetime.now().isoformat(),
            sport=sport, event=event, match=match, pick=pick,
            odds=odds, model_prob=model_prob, market_prob=market_prob,
            edge=edge, confidence=confidence, bet_size=bet_size,
            won=won, pnl=round(pnl, 2),
            bankroll_after=round(self.bankroll, 2),
            surface=surface, round_name=round_name, notes=notes,
        )
        self.record_trade(trade)
        return trade

    # === Analytics ===

    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    def total_staked(self) -> float:
        return sum(t.bet_size for t in self.trades)

    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.won) / len(self.trades)

    def roi(self) -> float:
        staked = self.total_staked()
        return self.total_pnl() / staked if staked > 0 else 0.0

    def max_drawdown(self) -> float:
        """Calculate maximum drawdown from peak."""
        if not self.trades:
            return 0.0
        peak = self.initial_bankroll
        max_dd = 0.0
        balance = self.initial_bankroll
        for t in self.trades:
            balance += t.pnl
            peak = max(peak, balance)
            dd = (peak - balance) / peak
            max_dd = max(max_dd, dd)
        return max_dd

    def sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        """Calculate Sharpe ratio of daily returns."""
        if len(self.trades) < 2:
            return 0.0
        returns = [t.pnl / t.bet_size for t in self.trades if t.bet_size > 0]
        if not returns:
            return 0.0
        avg = np.mean(returns)
        std = np.std(returns)
        return (avg - risk_free_rate) / std if std > 0 else 0.0

    def by_sport(self) -> Dict:
        """Performance breakdown by sport."""
        result = {}
        sports = set(t.sport for t in self.trades)
        for sport in sports:
            trades = [t for t in self.trades if t.sport == sport]
            wins = sum(1 for t in trades if t.won)
            pnl = sum(t.pnl for t in trades)
            result[sport] = {
                'bets': len(trades),
                'wins': wins,
                'win_rate': f"{wins/len(trades)*100:.1f}%",
                'pnl': round(pnl, 2),
            }
        return result

    def by_confidence(self) -> Dict:
        """Performance breakdown by confidence level."""
        result = {}
        levels = set(t.confidence for t in self.trades)
        for level in levels:
            trades = [t for t in self.trades if t.confidence == level]
            wins = sum(1 for t in trades if t.won)
            pnl = sum(t.pnl for t in trades)
            result[level] = {
                'bets': len(trades),
                'wins': wins,
                'win_rate': f"{wins/len(trades)*100:.1f}%",
                'pnl': round(pnl, 2),
            }
        return result

    def display_dashboard(self):
        """Print a comprehensive performance dashboard."""
        print(f"\n{'='*60}")
        print(f"  💰 NEMOFISH P&L DASHBOARD")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")

        # Portfolio
        total_return = (self.bankroll / self.initial_bankroll - 1) * 100
        btc_value = self.bankroll / self.btc_price

        print(f"\n  PORTFOLIO")
        print(f"  {'─'*40}")
        print(f"  Bankroll:      ${self.bankroll:>10,.2f} ({total_return:+.1f}%)")
        print(f"  In BTC:        ₿{btc_value:>10.6f}")
        print(f"  Initial:       ${self.initial_bankroll:>10,.2f}")
        print(f"  Total P&L:     ${self.total_pnl():>+10,.2f}")

        if self.trades:
            print(f"\n  PERFORMANCE")
            print(f"  {'─'*40}")
            print(f"  Total bets:    {len(self.trades):>10}")
            print(f"  Win rate:      {self.win_rate()*100:>10.1f}%")
            print(f"  ROI:           {self.roi()*100:>+10.1f}%")
            print(f"  Sharpe:        {self.sharpe_ratio():>10.2f}")
            print(f"  Max drawdown:  {self.max_drawdown()*100:>10.1f}%")

            # By sport
            by_sport = self.by_sport()
            if by_sport:
                print(f"\n  BY SPORT")
                print(f"  {'─'*40}")
                for sport, data in by_sport.items():
                    print(f"  {sport:<12}: {data['bets']:>3} bets | "
                          f"WR {data['win_rate']:>5} | P&L ${data['pnl']:>+,.2f}")

            # By confidence
            by_conf = self.by_confidence()
            if by_conf:
                print(f"\n  BY CONFIDENCE")
                print(f"  {'─'*40}")
                for level in ['ELITE', 'HIGH', 'MEDIUM', 'LOW']:
                    if level in by_conf:
                        data = by_conf[level]
                        print(f"  {level:<12}: {data['bets']:>3} bets | "
                              f"WR {data['win_rate']:>5} | P&L ${data['pnl']:>+,.2f}")

            # Recent trades
            print(f"\n  RECENT TRADES")
            print(f"  {'─'*40}")
            for t in self.trades[-5:]:
                status = "✅" if t.won else "❌"
                print(f"  {status} {t.match}: {t.pick} @ {t.odds:.2f} → "
                      f"${t.pnl:+.2f} | Edge {t.edge:.1%}")
        else:
            print(f"\n  No trades recorded yet.")

        print(f"{'='*60}")


# === CLI Demo ===
if __name__ == "__main__":
    tracker = PnLTracker(initial_bankroll=5000)

    # Simulate some paper trades
    tracker.record_result(
        "PT-001", "tennis", "Miami Open 2026", "Sinner vs Alcaraz",
        "Jannik Sinner", 1.55, 0.693, 0.645, 0.048, "HIGH",
        169.22, True, surface="Hard", round_name="F",
    )
    tracker.record_result(
        "PT-002", "tennis", "Miami Open 2026", "Medvedev vs de Minaur",
        "Daniil Medvedev", 1.80, 0.675, 0.556, 0.119, "LOW",
        250.00, True, surface="Hard", round_name="R16",
    )
    tracker.record_result(
        "PT-003", "tennis", "Miami Open 2026", "Djokovic vs Alcaraz",
        "Novak Djokovic", 2.40, 0.552, 0.417, 0.135, "LOW",
        250.00, False, surface="Hard", round_name="QF",
    )

    tracker.display_dashboard()
