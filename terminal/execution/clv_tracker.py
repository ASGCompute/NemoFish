"""
Closing Line Value (CLV) Tracker
==================================
Tracks whether our model systematically beats the closing line.

If we consistently place bets at better odds than the final closing line,
we are GUARANTEED to be profitable long-term (regardless of individual
match outcomes).

Usage:
    tracker = CLVTracker()
    tracker.record_bet("Sinner vs Alcaraz", odds_at_bet=1.85, pick="A")
    # ... later, at match start ...
    tracker.record_closing_line("Sinner vs Alcaraz", closing_odds=1.75)
    print(tracker.summary())
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict


@dataclass
class BetRecord:
    """Single bet record with CLV tracking."""
    match_id: str
    timestamp: str
    player_a: str
    player_b: str
    pick: str                   # "A" or "B"
    odds_at_bet: float          # Odds when we placed the bet
    closing_odds: Optional[float] = None  # Final line at match start
    result: Optional[str] = None  # "win" / "loss" / None (pending)
    bet_size: float = 0.0
    strategy_name: str = ""
    model_prob: float = 0.0

    @property
    def clv(self) -> Optional[float]:
        """CLV = (our_odds / closing_odds) - 1. Positive = edge confirmed."""
        if self.closing_odds and self.closing_odds > 0:
            return (self.odds_at_bet / self.closing_odds) - 1.0
        return None

    @property
    def clv_pct(self) -> Optional[str]:
        """CLV as percentage string."""
        c = self.clv
        return f"{c:+.2%}" if c is not None else "N/A"


class CLVTracker:
    """
    Tracks Closing Line Value across all bets.
    
    CLV is the ONLY metric that guarantees long-term profitability.
    If avg CLV > 0 consistently, the system has real edge.
    """

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir) if data_dir else \
            Path(__file__).parent.parent / "data" / "clv"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bets: List[BetRecord] = []
        self._load()

    def record_bet(
        self,
        match_id: str,
        player_a: str,
        player_b: str,
        pick: str,
        odds_at_bet: float,
        bet_size: float = 0.0,
        strategy_name: str = "",
        model_prob: float = 0.0,
    ) -> BetRecord:
        """Record a bet at the time of placement."""
        rec = BetRecord(
            match_id=match_id,
            timestamp=datetime.now().isoformat(),
            player_a=player_a,
            player_b=player_b,
            pick=pick,
            odds_at_bet=odds_at_bet,
            bet_size=bet_size,
            strategy_name=strategy_name,
            model_prob=model_prob,
        )
        self.bets.append(rec)
        self._save()
        return rec

    def record_closing_line(self, match_id: str, closing_odds: float):
        """Record the closing line when match starts."""
        for bet in reversed(self.bets):
            if bet.match_id == match_id and bet.closing_odds is None:
                bet.closing_odds = closing_odds
                self._save()
                return
        print(f"⚠️  No bet found for match_id={match_id}")

    def record_result(self, match_id: str, result: str):
        """Record match result ('win' or 'loss')."""
        for bet in reversed(self.bets):
            if bet.match_id == match_id and bet.result is None:
                bet.result = result
                self._save()
                return

    def summary(self) -> Dict:
        """Generate CLV tracking summary."""
        completed = [b for b in self.bets if b.closing_odds is not None]
        if not completed:
            return {
                "total_bets": len(self.bets),
                "clv_tracked": 0,
                "avg_clv": None,
                "positive_clv_pct": None,
                "verdict": "No closing lines recorded yet",
            }

        clv_values = [b.clv for b in completed if b.clv is not None]
        positive = [c for c in clv_values if c > 0]

        wins = len([b for b in completed if b.result == "win"])
        losses = len([b for b in completed if b.result == "loss"])
        
        avg_clv = sum(clv_values) / len(clv_values) if clv_values else 0
        pos_pct = len(positive) / len(clv_values) if clv_values else 0

        if avg_clv > 0.02:
            verdict = "🟢 STRONG EDGE — consistently beating closing line"
        elif avg_clv > 0:
            verdict = "🟡 MARGINAL EDGE — positive but small CLV"
        else:
            verdict = "🔴 NO EDGE — model is not beating the market"

        return {
            "total_bets": len(self.bets),
            "clv_tracked": len(completed),
            "avg_clv": round(avg_clv, 4),
            "avg_clv_pct": f"{avg_clv:+.2%}",
            "positive_clv_pct": f"{pos_pct:.0%}",
            "wins": wins,
            "losses": losses,
            "win_rate": f"{wins/(wins+losses):.1%}" if (wins + losses) > 0 else "N/A",
            "verdict": verdict,
        }

    def print_report(self):
        """Print formatted CLV report."""
        s = self.summary()
        print("\n" + "═" * 50)
        print("  📊 CLV TRACKING REPORT")
        print("═" * 50)
        print(f"  Total bets:     {s['total_bets']}")
        print(f"  CLV tracked:    {s['clv_tracked']}")
        if s['avg_clv'] is not None:
            print(f"  Avg CLV:        {s['avg_clv_pct']}")
            print(f"  Positive CLV:   {s['positive_clv_pct']}")
            print(f"  W/L:            {s.get('wins', 0)}/{s.get('losses', 0)}")
            print(f"  Win rate:       {s.get('win_rate', 'N/A')}")
        print(f"\n  {s['verdict']}")
        print("═" * 50)

    def _save(self):
        """Save bets to JSON file."""
        path = self.data_dir / "clv_history.json"
        data = [asdict(b) for b in self.bets]
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load(self):
        """Load existing bets from JSON."""
        path = self.data_dir / "clv_history.json"
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                self.bets = [BetRecord(**d) for d in data]
            except Exception:
                self.bets = []


if __name__ == "__main__":
    # Demo
    tracker = CLVTracker()
    
    # Simulate a bet
    tracker.record_bet(
        match_id="sinner-alcaraz-20240315",
        player_a="Jannik Sinner",
        player_b="Carlos Alcaraz",
        pick="A",
        odds_at_bet=1.85,
        bet_size=25.0,
        strategy_name="atp_confidence_5",
        model_prob=0.58,
    )
    
    # Closing line came in at 1.75 (our odds were better!)
    tracker.record_closing_line("sinner-alcaraz-20240315", closing_odds=1.75)
    tracker.record_result("sinner-alcaraz-20240315", "win")
    
    tracker.print_report()
