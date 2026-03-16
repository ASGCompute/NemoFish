"""
Miami Open 2026 Live Scanner
==============================
Fetches real-time tennis data and produces actionable predictions.

Data sources:
  1. JeffSackmann Elo ratings (historical base)
  2. ATP rankings (from data files)  
  3. Polymarket (if tennis markets exist)
  4. Web search for latest odds & draw

Output: ranked list of bet signals with edge, confidence, Kelly sizing.
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.tennis_elo import TennisEloEngine
from models.kelly import KellyCriterion
from agents.tennis_swarm import TennisSwarm, MatchContext, SwarmConsensus
from feeds.polymarket import PolymarketClient


class MiamiOpenScanner:
    """
    Live prediction scanner for Miami Open 2026.
    
    Usage:
        scanner = MiamiOpenScanner()
        scanner.run_full_analysis()
    """

    # Known Miami Open 2026 likely draw based on rankings
    # These would be updated with real draw when published
    TOP_SEEDS = [
        {"name": "Jannik Sinner", "rank": 1, "seed": 1},
        {"name": "Alexander Zverev", "rank": 2, "seed": 2},
        {"name": "Carlos Alcaraz", "rank": 3, "seed": 3},
        {"name": "Taylor Fritz", "rank": 4, "seed": 4},
        {"name": "Daniil Medvedev", "rank": 5, "seed": 5},
        {"name": "Casper Ruud", "rank": 6, "seed": 6},
        {"name": "Novak Djokovic", "rank": 7, "seed": 7},
        {"name": "Alex de Minaur", "rank": 8, "seed": 8},
        {"name": "Holger Rune", "rank": 9, "seed": 9},
        {"name": "Grigor Dimitrov", "rank": 10, "seed": 10},
        {"name": "Jack Draper", "rank": 11, "seed": 11},
        {"name": "Tommy Paul", "rank": 12, "seed": 12},
        {"name": "Stefanos Tsitsipas", "rank": 13, "seed": 13},
        {"name": "Frances Tiafoe", "rank": 14, "seed": 14},
        {"name": "Ugo Humbert", "rank": 15, "seed": 15},
        {"name": "Sebastian Korda", "rank": 16, "seed": 16},
    ]

    # Likely high-interest matchups based on draw sections
    KEY_MATCHUPS = [
        # Format: (player_a, player_b, round, estimated_odds_a, estimated_odds_b)
        ("Jannik Sinner", "Alexander Zverev", "F", 1.55, 2.55),
        ("Jannik Sinner", "Carlos Alcaraz", "F", 1.55, 2.55),
        ("Alexander Zverev", "Carlos Alcaraz", "SF", 1.90, 1.95),
        ("Jannik Sinner", "Daniil Medvedev", "SF", 1.35, 3.40),
        ("Carlos Alcaraz", "Daniil Medvedev", "QF", 1.55, 2.55),
        ("Novak Djokovic", "Taylor Fritz", "R16", 1.70, 2.25),
        ("Novak Djokovic", "Carlos Alcaraz", "QF", 2.40, 1.60),
        ("Jannik Sinner", "Taylor Fritz", "QF", 1.30, 3.80),
        ("Alexander Zverev", "Holger Rune", "QF", 1.45, 2.90),
        ("Jack Draper", "Grigor Dimitrov", "R16", 1.75, 2.15),
        ("Daniil Medvedev", "Alex de Minaur", "R16", 1.80, 2.10),
        ("Stefanos Tsitsipas", "Tommy Paul", "R32", 2.10, 1.80),
        ("Holger Rune", "Sebastian Korda", "R32", 1.65, 2.35),
        ("Casper Ruud", "Ugo Humbert", "R16", 2.00, 1.85),
    ]

    def __init__(self):
        print("🌴 Initializing Miami Open Scanner...")
        self.swarm = TennisSwarm()
        self.kelly = KellyCriterion(bankroll=5000)
        print("✅ Scanner ready.\n")

    def analyze_matchup(
        self, player_a: str, player_b: str,
        round_name: str, odds_a: float, odds_b: float,
        **kwargs
    ) -> SwarmConsensus:
        """Analyze a single matchup through the swarm."""
        # Find player data
        seed_a = next((p['seed'] for p in self.TOP_SEEDS if p['name'] == player_a), None)
        seed_b = next((p['seed'] for p in self.TOP_SEEDS if p['name'] == player_b), None)
        rank_a = next((p['rank'] for p in self.TOP_SEEDS if p['name'] == player_a), 30)
        rank_b = next((p['rank'] for p in self.TOP_SEEDS if p['name'] == player_b), 30)

        ctx = MatchContext(
            player_a=player_a,
            player_b=player_b,
            surface="Hard",
            tourney_name="Miami Open 2026",
            tourney_level="M",
            round_name=round_name,
            date="2026-03-17",
            rank_a=rank_a,
            rank_b=rank_b,
            seed_a=seed_a,
            seed_b=seed_b,
            odds_a=odds_a,
            odds_b=odds_b,
            days_since_last_match_a=kwargs.get('rest_a', 4),
            days_since_last_match_b=kwargs.get('rest_b', 4),
            matches_last_14d_a=kwargs.get('load_a', 3),
            matches_last_14d_b=kwargs.get('load_b', 3),
            recent_wins_a=kwargs.get('form_a', 7),
            recent_wins_b=kwargs.get('form_b', 7),
        )

        return self.swarm.predict(ctx)

    def run_full_analysis(self):
        """Analyze all key matchups and rank by edge."""
        print("=" * 70)
        print("  🌴 MIAMI OPEN 2026 — NEMOFISH PREDICTION ENGINE")
        print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"  Mode: SWARM CONSENSUS (5 agents, weighted voting)")
        print(f"  Bankroll: ${self.kelly.bankroll:,.2f} | Kelly: Quarter (25%)")
        print("=" * 70)

        results = []

        for pa, pb, rnd, odds_a, odds_b in self.KEY_MATCHUPS:
            consensus = self.analyze_matchup(pa, pb, rnd, odds_a, odds_b)
            results.append((pa, pb, rnd, odds_a, odds_b, consensus))

        # Sort by absolute edge (best opportunities first)
        results.sort(key=lambda x: abs(x[5].edge_vs_market or 0), reverse=True)

        # === BET SIGNALS ===
        bet_signals = [r for r in results if r[5].recommended_action != "SKIP"]
        skip_signals = [r for r in results if r[5].recommended_action == "SKIP"]

        if bet_signals:
            print(f"\n  💰 BET SIGNALS ({len(bet_signals)} opportunities)")
            print("  " + "-" * 66)
            for pa, pb, rnd, odds_a, odds_b, c in bet_signals:
                pick = pa if c.recommended_action == "BET_A" else pb
                odds = odds_a if c.recommended_action == "BET_A" else odds_b
                edge = abs(c.edge_vs_market or 0) * 100

                print(f"\n  🔥 {pa} vs {pb} | {rnd}")
                print(f"     PICK: {pick} @ {odds:.2f}")
                print(f"     Model: {pa} {c.prob_a:.1%} | {pb} {c.prob_b:.1%}")
                print(f"     Edge: +{edge:.1f}% | Confidence: {c.confidence}")
                print(f"     Data Quality: {c.data_quality_score:.0%}")
                print(f"     Kelly Bet: ${c.kelly_bet_size:.2f}")
                
                # Vote breakdown
                for v in c.agent_votes:
                    status = "✅" if (v.prob_a > 0.5 and c.recommended_action == "BET_A") or \
                                    (v.prob_a < 0.5 and c.recommended_action == "BET_B") else "❌"
                    print(f"       {status} {v.agent_role}: {pa} {v.prob_a:.0%}")

        print(f"\n  ⏸️  SKIP ({len(skip_signals)} matches — no edge)")
        print("  " + "-" * 66)
        for pa, pb, rnd, odds_a, odds_b, c in skip_signals:
            edge = (c.edge_vs_market or 0) * 100
            print(f"     {pa} vs {pb} ({rnd}) | {pa} {c.prob_a:.1%} | "
                  f"Edge: {edge:+.1f}% | {c.confidence}")

        # === SUMMARY ===
        total_kelly = sum(c.kelly_bet_size for _, _, _, _, _, c in bet_signals)
        total_bets = len(bet_signals)
        avg_edge = np.mean([abs(c.edge_vs_market or 0) for _, _, _, _, _, c in bet_signals]) * 100 if bet_signals else 0

        print(f"\n{'='*70}")
        print(f"  📊 SUMMARY")
        print(f"{'='*70}")
        print(f"  Matches analyzed:  {len(results)}")
        print(f"  Bet signals:       {total_bets}")
        print(f"  Total Kelly size:  ${total_kelly:.2f}")
        print(f"  Average edge:      {avg_edge:.1f}%")
        print(f"  Bankroll at risk:  {total_kelly/self.kelly.bankroll*100:.1f}%")
        print(f"\n  ⚠️  Miami Open draw not yet published.")
        print(f"  Update odds when R1/R2 matchups are confirmed!")
        print(f"{'='*70}")

        return results

    def quick_predict(self, player_a: str, player_b: str, odds_a: float = None, odds_b: float = None):
        """Quick prediction for any matchup."""
        round_name = "R32"  # Default
        if not odds_a:
            odds_a = 1.80
        if not odds_b:
            odds_b = 2.10

        result = self.analyze_matchup(player_a, player_b, round_name, odds_a, odds_b)
        self.swarm.predict_and_display(
            MatchContext(
                player_a=player_a, player_b=player_b,
                surface="Hard", tourney_name="Miami Open 2026",
                tourney_level="M", round_name=round_name,
                date="2026-03-17",
                rank_a=next((p['rank'] for p in self.TOP_SEEDS if p['name'] == player_a), 30),
                rank_b=next((p['rank'] for p in self.TOP_SEEDS if p['name'] == player_b), 30),
                odds_a=odds_a, odds_b=odds_b,
            )
        )
        return result


# === Entry Point ===
if __name__ == "__main__":
    scanner = MiamiOpenScanner()
    scanner.run_full_analysis()
