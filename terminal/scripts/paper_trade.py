"""
NemoFish Paper Trading Engine
===============================
Full paper trading pipeline that connects:
  Swarm predictions → Risk Manager → P&L Tracker

Runs in paper mode first ($10K virtual bankroll).
Once validated (ROI > 5% over 100+ trades), can switch to live.

Usage:
    python3 scripts/paper_trade.py              # Full paper trading session
    python3 scripts/paper_trade.py --live       # Live mode (requires API keys)
"""

import sys
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.tennis_swarm import TennisSwarm, MatchContext, SwarmConsensus
from execution.risk_manager import RiskManager, TradeSignal, RiskDecision
from execution.pnl_tracker import PnLTracker
from models.kelly import KellyCriterion
from feeds.polymarket import PolymarketClient


class PaperTradingEngine:
    """
    Full paper trading pipeline.
    
    Flow:
    1. Swarm generates predictions for upcoming matches
    2. Each prediction becomes a TradeSignal
    3. Risk Manager evaluates each signal (9 checks)
    4. Approved signals are "executed" (paper)
    5. P&L Tracker records all results
    6. Dashboard shows real-time performance
    """

    def __init__(
        self,
        bankroll: float = 10000.0,
        mode: str = "paper",  # "paper" or "live"
    ):
        self.mode = mode
        self.initial_bankroll = bankroll

        print(f"{'='*65}")
        print(f"  🐡 NEMOFISH {'PAPER' if mode == 'paper' else 'LIVE'} TRADING ENGINE")
        print(f"  Bankroll: ${bankroll:,.2f} | Mode: {mode.upper()}")
        print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*65}")

        # Initialize components
        print("\n  Loading swarm...")
        self.swarm = TennisSwarm()

        self.risk = RiskManager(bankroll=bankroll)
        self.tracker = PnLTracker(initial_bankroll=bankroll)
        self.kelly = KellyCriterion(bankroll=bankroll)
        self.polymarket = PolymarketClient()

        print(f"  ✅ All systems online.\n")

    def create_signal(self, ctx: MatchContext, consensus: SwarmConsensus) -> TradeSignal:
        """Convert a swarm consensus into a trade signal."""
        if consensus.recommended_action == "BET_A":
            pick = ctx.player_a
            odds = ctx.odds_a or (1.0 / consensus.prob_a if consensus.prob_a > 0 else 2.0)
            model_prob = consensus.prob_a
        elif consensus.recommended_action == "BET_B":
            pick = ctx.player_b
            odds = ctx.odds_b or (1.0 / consensus.prob_b if consensus.prob_b > 0 else 2.0)
            model_prob = consensus.prob_b
        else:
            pick = ctx.player_a  # Default
            odds = ctx.odds_a or 2.0
            model_prob = consensus.prob_a

        market_prob = 1.0 / odds if odds > 0 else 0.5

        return TradeSignal(
            id=f"NF-{uuid.uuid4().hex[:8].upper()}",
            timestamp=datetime.now().isoformat(),
            sport="tennis",
            event=ctx.tourney_name,
            match=f"{ctx.player_a} vs {ctx.player_b}",
            pick=pick,
            side=consensus.recommended_action,
            odds=round(odds, 3),
            model_prob=round(model_prob, 4),
            market_prob=round(market_prob, 4),
            edge=round(consensus.edge_vs_market or (model_prob - market_prob), 4),
            confidence=consensus.confidence,
            kelly_raw=round(consensus.kelly_bet_size, 2),
            surface=ctx.surface,
            round_name=ctx.round_name,
            data_quality=consensus.data_quality_score,
            source="swarm",
        )

    def evaluate_and_execute(self, ctx: MatchContext) -> Optional[Dict]:
        """
        Full pipeline: predict → risk check → execute (paper).
        Returns trade result or None if skipped.
        """
        # Step 1: Get swarm prediction
        consensus = self.swarm.predict(ctx)

        if consensus.recommended_action == "SKIP":
            return {
                'status': 'SKIP',
                'match': f"{ctx.player_a} vs {ctx.player_b}",
                'reason': f"No edge ({consensus.edge_vs_market or 0:.1%})",
            }

        # Step 2: Create trade signal
        signal = self.create_signal(ctx, consensus)

        # Step 3: Risk check
        decision = self.risk.evaluate(signal)

        if not decision.approved:
            return {
                'status': 'REJECTED',
                'match': f"{ctx.player_a} vs {ctx.player_b}",
                'reason': f"Risk: {', '.join(decision.risk_flags)}",
            }

        # Step 4: Execute (paper — just record the position)
        position = self.risk.open_position(signal, decision.final_bet_size)

        return {
            'status': 'EXECUTED',
            'match': f"{ctx.player_a} vs {ctx.player_b}",
            'pick': signal.pick,
            'odds': signal.odds,
            'edge': signal.edge,
            'bet_size': decision.final_bet_size,
            'signal_id': signal.id,
            'confidence': signal.confidence,
            'position': position,
        }

    def resolve_trade(self, signal_id: str, won: bool):
        """Resolve a paper trade with the actual result."""
        for pos in self.risk.positions:
            if pos.signal.id == signal_id and pos.status == "OPEN":
                self.risk.close_position(pos, won)
                self.tracker.record_result(
                    trade_id=signal_id,
                    sport=pos.signal.sport,
                    event=pos.signal.event,
                    match=pos.signal.match,
                    pick=pos.signal.pick,
                    odds=pos.signal.odds,
                    model_prob=pos.signal.model_prob,
                    market_prob=pos.signal.market_prob,
                    edge=pos.signal.edge,
                    confidence=pos.signal.confidence,
                    bet_size=pos.bet_size,
                    won=won,
                    surface=pos.signal.surface,
                    round_name=pos.signal.round_name,
                )
                return pos.pnl
        return 0

    def run_miami_open_session(self):
        """
        Run a complete paper trading session for Miami Open.
        Analyzes all potential matchups and executes viable ones.
        """
        print(f"\n{'🌴'*20}")
        print(f"  MIAMI OPEN 2026 — PAPER TRADING SESSION")
        print(f"{'🌴'*20}\n")

        matches = [
            MatchContext(
                player_a="Jannik Sinner", player_b="Daniil Medvedev",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="SF", date="2026-03-28",
                rank_a=1, rank_b=5, seed_a=1, seed_b=4,
                odds_a=1.35, odds_b=3.40,
                days_since_last_match_a=3, days_since_last_match_b=3,
                matches_last_14d_a=4, matches_last_14d_b=4,
                recent_wins_a=8, recent_wins_b=6,
            ),
            MatchContext(
                player_a="Carlos Alcaraz", player_b="Alexander Zverev",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="QF", date="2026-03-27",
                rank_a=3, rank_b=2, seed_a=3, seed_b=2,
                odds_a=1.85, odds_b=2.05,
                days_since_last_match_a=2, days_since_last_match_b=4,
                matches_last_14d_a=5, matches_last_14d_b=3,
                recent_wins_a=7, recent_wins_b=7,
            ),
            MatchContext(
                player_a="Novak Djokovic", player_b="Carlos Alcaraz",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="QF", date="2026-03-26",
                rank_a=7, rank_b=3, seed_a=7, seed_b=3,
                odds_a=2.40, odds_b=1.60,
                days_since_last_match_a=5, days_since_last_match_b=3,
                matches_last_14d_a=2, matches_last_14d_b=4,
                recent_wins_a=6, recent_wins_b=7,
            ),
            MatchContext(
                player_a="Jannik Sinner", player_b="Carlos Alcaraz",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="F", date="2026-03-30",
                rank_a=1, rank_b=3, seed_a=1, seed_b=3,
                odds_a=1.55, odds_b=2.55,
                days_since_last_match_a=2, days_since_last_match_b=2,
                matches_last_14d_a=5, matches_last_14d_b=6,
                recent_wins_a=9, recent_wins_b=7,
            ),
            MatchContext(
                player_a="Daniil Medvedev", player_b="Alex de Minaur",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="R16", date="2026-03-24",
                rank_a=5, rank_b=8, seed_a=5, seed_b=8,
                odds_a=1.80, odds_b=2.10,
                days_since_last_match_a=3, days_since_last_match_b=3,
                matches_last_14d_a=3, matches_last_14d_b=3,
                recent_wins_a=6, recent_wins_b=5,
            ),
            MatchContext(
                player_a="Novak Djokovic", player_b="Taylor Fritz",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="R16", date="2026-03-25",
                rank_a=7, rank_b=4, seed_a=7, seed_b=4,
                odds_a=1.70, odds_b=2.25,
                days_since_last_match_a=5, days_since_last_match_b=3,
                matches_last_14d_a=2, matches_last_14d_b=4,
                recent_wins_a=6, recent_wins_b=7,
            ),
            MatchContext(
                player_a="Alexander Zverev", player_b="Holger Rune",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="QF", date="2026-03-27",
                rank_a=2, rank_b=9, seed_a=2, seed_b=9,
                odds_a=1.45, odds_b=2.90,
                days_since_last_match_a=3, days_since_last_match_b=3,
                matches_last_14d_a=4, matches_last_14d_b=4,
                recent_wins_a=7, recent_wins_b=6,
            ),
            MatchContext(
                player_a="Jack Draper", player_b="Grigor Dimitrov",
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name="R16", date="2026-03-24",
                rank_a=11, rank_b=10, seed_a=11, seed_b=10,
                odds_a=1.75, odds_b=2.15,
                days_since_last_match_a=4, days_since_last_match_b=4,
                matches_last_14d_a=3, matches_last_14d_b=3,
                recent_wins_a=7, recent_wins_b=6,
            ),
        ]

        executed = []
        skipped = []
        rejected = []

        for ctx in matches:
            result = self.evaluate_and_execute(ctx)

            if result['status'] == 'EXECUTED':
                executed.append(result)
                print(f"  ✅ {result['match']}: {result['pick']} @ {result['odds']:.2f} "
                      f"| ${result['bet_size']:.2f} | Edge {result['edge']:.1%} | [{result['signal_id']}]")
            elif result['status'] == 'REJECTED':
                rejected.append(result)
                print(f"  ⚠️  {result['match']}: REJECTED ({result['reason']})")
            else:
                skipped.append(result)
                print(f"  ⏸️  {result['match']}: SKIP ({result['reason']})")

        # Summary
        total_allocated = sum(r['bet_size'] for r in executed)
        print(f"\n{'='*65}")
        print(f"  SESSION SUMMARY")
        print(f"{'='*65}")
        print(f"  Executed:    {len(executed):>3} trades | ${total_allocated:>,.2f} allocated")
        print(f"  Rejected:    {len(rejected):>3} signals")
        print(f"  Skipped:     {len(skipped):>3} matches")
        print(f"  Exposure:    {total_allocated/self.risk.bankroll*100:.1f}% of bankroll")

        if executed:
            avg_edge = sum(r['edge'] for r in executed) / len(executed)
            print(f"  Avg edge:    {avg_edge:.1%}")
            print(f"\n  📝 Trade IDs for resolution:")
            for r in executed:
                print(f"     {r['signal_id']}: {r['match']} → {r['pick']}")

        self.risk.display_status()

        return executed

    def simulate_results(self, executed: List[Dict], outcomes: Dict[str, bool]):
        """
        Simulate results for paper trades.
        outcomes: {signal_id: True/False (won/lost)}
        """
        print(f"\n{'='*65}")
        print(f"  📊 RESOLVING TRADES")
        print(f"{'='*65}")

        for trade in executed:
            sid = trade['signal_id']
            if sid in outcomes:
                won = outcomes[sid]
                pnl = self.resolve_trade(sid, won)
                status = "✅ WON" if won else "❌ LOST"
                print(f"  {status}: {trade['match']} → {trade['pick']} | P&L: ${pnl:+.2f}")

        self.tracker.display_dashboard()
        self.risk.display_status()


# === Entry Point ===
if __name__ == "__main__":
    mode = "paper"
    if "--live" in sys.argv:
        mode = "live"
        print("⚠️  LIVE MODE — Real money at risk!")

    engine = PaperTradingEngine(bankroll=10000, mode=mode)
    
    # Run Miami Open session
    executed = engine.run_miami_open_session()

    if executed:
        # Simulate some outcomes for demo
        print(f"\n{'='*65}")
        print(f"  🎲 SIMULATING OUTCOMES (Paper Trading Demo)")
        print(f"{'='*65}")

        # Simulate: assume favorites win (based on our model)
        outcomes = {}
        for trade in executed:
            # 65% chance our picks win (matches our backtest win rate)
            import random
            random.seed(hash(trade['signal_id']) % 2**32)
            won = random.random() < 0.65
            outcomes[trade['signal_id']] = won

        engine.simulate_results(executed, outcomes)
