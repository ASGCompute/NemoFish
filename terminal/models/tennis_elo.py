"""
Surface-Adjusted Weighted Elo (WElo) Rating System for Tennis
=================================================================
Computes dynamic Elo ratings per surface (Clay, Grass, Hard, Indoor)
plus overall Elo. Uses **margin-weighted** updates (WElo) where dominant
wins (6-0 6-0) give more credit than close wins (7-6 7-6).

Based on:
  - JeffSackmann data (95K+ ATP matches since 1968)
  - Angelini et al. 2022 — WElo with margin of victory (Tier 1, ROI 3.56%)
"""

import math
import re
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime


# --- Constants ---
INITIAL_ELO = 1500.0
SURFACES = ["Hard", "Clay", "Grass", "Carpet"]  # Carpet mapped to Indoor

# K-factor by tournament level (higher = faster adaptation)
K_FACTORS = {
    "G": 48,       # Grand Slam
    "M": 36,       # Masters 1000
    "A": 28,       # ATP 500
    "B": 24,       # ATP 250
    "F": 40,       # Tour Finals
    "D": 20,       # Davis Cup
    "C": 16,       # Challenger
    "S": 12,       # Satellite/ITF
}
DEFAULT_K = 24


@dataclass
class PlayerRating:
    """Stores per-surface and overall Elo for a player."""
    name: str
    overall: float = INITIAL_ELO
    hard: float = INITIAL_ELO
    clay: float = INITIAL_ELO
    grass: float = INITIAL_ELO
    indoor: float = INITIAL_ELO
    matches_played: int = 0
    last_match_date: Optional[str] = None

    def get_surface_elo(self, surface: str) -> float:
        surface_map = {
            "Hard": self.hard,
            "Clay": self.clay,
            "Grass": self.grass,
            "Carpet": self.indoor,
            "Indoor": self.indoor,
        }
        return surface_map.get(surface, self.overall)

    def set_surface_elo(self, surface: str, value: float):
        if surface == "Hard":
            self.hard = value
        elif surface == "Clay":
            self.clay = value
        elif surface == "Grass":
            self.grass = value
        elif surface in ("Carpet", "Indoor"):
            self.indoor = value

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "overall": round(self.overall, 1),
            "hard": round(self.hard, 1),
            "clay": round(self.clay, 1),
            "grass": round(self.grass, 1),
            "indoor": round(self.indoor, 1),
            "matches": self.matches_played,
            "last_match": self.last_match_date,
        }


class TennisEloEngine:
    """
    Computes Surface-Adjusted Elo ratings from JeffSackmann data.
    
    Usage:
        engine = TennisEloEngine()
        engine.load_and_process()  # Process all historical matches
        
        # Get current ratings
        sinner = engine.get_player("Jannik Sinner")
        print(f"Overall: {sinner.overall}, Hard: {sinner.hard}")
        
        # Predict match outcome
        prob = engine.predict_match("Jannik Sinner", "Daniil Medvedev", "Hard")
        print(f"Sinner win probability on Hard: {prob:.1%}")
    """

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp")
        self.data_dir = Path(data_dir)
        self.ratings: Dict[str, PlayerRating] = {}

    def _get_or_create(self, player_name: str) -> PlayerRating:
        if player_name not in self.ratings:
            self.ratings[player_name] = PlayerRating(name=player_name)
        return self.ratings[player_name]

    @staticmethod
    def expected_score(rating_a: float, rating_b: float) -> float:
        """Standard Elo expected score formula."""
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

    def _get_k_factor(self, tourney_level: str, matches_played: int) -> float:
        """
        K-factor with newcomer boost: players with < 30 matches
        get 1.5x K to converge faster.
        """
        base_k = K_FACTORS.get(tourney_level, DEFAULT_K)
        if matches_played < 30:
            base_k *= 1.5
        return base_k

    @staticmethod
    def _parse_score_margin(score: str) -> float:
        """
        Parse tennis score into a WElo margin weight.
        
        WElo formula (Angelini et al. 2022):
          margin = (sets_won / total_sets) * (games_won / total_games)
        
        Examples:
          "6-0 6-0"     → 1.0 * 1.0  = 1.00 (dominant)
          "6-3 6-2"     → 1.0 * 0.71 = 0.71
          "7-6 7-6"     → 1.0 * 0.52 = 0.52 (close)
          "6-4 4-6 7-5" → 0.67 * 0.53 = 0.35 (close 3-setter)
          "6-0 6-0 6-0" → 1.0 * 1.0  = 1.00 (dominant Bo5)
          
        Returns 1.0 (standard Elo) if score cannot be parsed.
        """
        if not score or not isinstance(score, str):
            return 1.0
        
        try:
            sets_won = 0
            sets_lost = 0
            games_won = 0
            games_lost = 0
            
            # Split into sets, handle tiebreak notation like "7-6(5)"
            for set_score in score.strip().split():
                # Remove tiebreak details and retirement markers
                clean = re.sub(r'\([^)]*\)', '', set_score).strip()
                if not clean or '-' not in clean:
                    continue
                    
                parts = clean.split('-')
                if len(parts) != 2:
                    continue
                
                try:
                    g_w = int(parts[0])
                    g_l = int(parts[1])
                except ValueError:
                    continue
                
                games_won += g_w
                games_lost += g_l
                
                if g_w > g_l:
                    sets_won += 1
                else:
                    sets_lost += 1
            
            total_sets = sets_won + sets_lost
            total_games = games_won + games_lost
            
            if total_sets == 0 or total_games == 0:
                return 1.0
            
            set_ratio = sets_won / total_sets
            game_ratio = games_won / total_games
            
            return set_ratio * game_ratio
            
        except Exception:
            return 1.0

    def update_elo(
        self,
        winner_name: str,
        loser_name: str,
        surface: str,
        tourney_level: str,
        match_date: str,
        score: str = None,
    ):
        """
        Update Elo ratings after a single match result (WElo).
        Updates BOTH overall and surface-specific ratings.
        
        WElo: Uses margin of victory to weight the update.
        Dominant wins (6-0 6-0) produce larger rating changes
        than close wins (7-6 7-6). Falls back to standard Elo
        if score is not available.
        """
        winner = self._get_or_create(winner_name)
        loser = self._get_or_create(loser_name)

        # WElo margin weight (Angelini et al. 2022)
        margin = self._parse_score_margin(score) if score else 1.0

        # --- Overall Elo (WElo) ---
        k_w = self._get_k_factor(tourney_level, winner.matches_played)
        k_l = self._get_k_factor(tourney_level, loser.matches_played)

        exp_w = self.expected_score(winner.overall, loser.overall)
        exp_l = 1.0 - exp_w

        # WElo: actual score = margin (not 1.0)
        winner.overall += k_w * (margin - exp_w)
        loser.overall += k_l * ((1.0 - margin) - exp_l)

        # --- Surface-Specific Elo (also WElo) ---
        if surface in ("Hard", "Clay", "Grass", "Carpet", "Indoor"):
            w_surf = winner.get_surface_elo(surface)
            l_surf = loser.get_surface_elo(surface)

            exp_ws = self.expected_score(w_surf, l_surf)

            # Surface K is slightly higher to adapt faster to surface form
            k_surf = self._get_k_factor(tourney_level, winner.matches_played) * 1.1
            winner.set_surface_elo(surface, w_surf + k_surf * (margin - exp_ws))
            loser.set_surface_elo(surface, l_surf + k_surf * ((1.0 - margin) - (1.0 - exp_ws)))

        # Update metadata
        winner.matches_played += 1
        loser.matches_played += 1
        winner.last_match_date = match_date
        loser.last_match_date = match_date

    def predict_match(
        self,
        player_a: str,
        player_b: str,
        surface: str,
        blend_weight: float = 0.6,
    ) -> float:
        """
        Predict win probability for player_a vs player_b on given surface.
        
        Uses blended probability: 60% surface Elo + 40% overall Elo
        (configurable via blend_weight).
        
        Returns: probability that player_a wins (0.0 to 1.0)
        """
        a = self._get_or_create(player_a)
        b = self._get_or_create(player_b)

        # Overall prediction
        prob_overall = self.expected_score(a.overall, b.overall)

        # Surface prediction
        a_surf = a.get_surface_elo(surface)
        b_surf = b.get_surface_elo(surface)
        prob_surface = self.expected_score(a_surf, b_surf)

        # Blend: surface-weighted prediction
        return blend_weight * prob_surface + (1 - blend_weight) * prob_overall

    def load_and_process(self, start_year: int = 2000, end_year: int = 2026):
        """
        Load JeffSackmann ATP match CSVs and process all matches chronologically.
        Files: atp_matches_YYYY.csv
        """
        all_matches = []

        for year in range(start_year, end_year + 1):
            filepath = self.data_dir / f"atp_matches_{year}.csv"
            if not filepath.exists():
                continue
            try:
                df = pd.read_csv(filepath, low_memory=False)
                df["year"] = year
                all_matches.append(df)
            except Exception as e:
                print(f"Warning: Could not load {filepath}: {e}")

        if not all_matches:
            print("No match data found!")
            return

        matches = pd.concat(all_matches, ignore_index=True)

        # Parse dates and sort chronologically
        matches["tourney_date"] = pd.to_datetime(
            matches["tourney_date"], format="%Y%m%d", errors="coerce"
        )
        matches = matches.dropna(subset=["tourney_date"])
        matches = matches.sort_values("tourney_date").reset_index(drop=True)

        print(f"Processing {len(matches):,} matches ({start_year}-{end_year})...")

        for _, row in matches.iterrows():
            winner = row.get("winner_name")
            loser = row.get("loser_name")
            surface = row.get("surface", "Hard")
            level = row.get("tourney_level", "B")
            date_str = str(row.get("tourney_date", ""))[:10]

            if pd.isna(winner) or pd.isna(loser):
                continue

            # Pass score for WElo margin weighting
            score = str(row.get("score", "")) if pd.notna(row.get("score")) else None
            self.update_elo(winner, loser, surface, level, date_str, score=score)

        print(f"Ratings computed for {len(self.ratings):,} players.")

    def get_player(self, name: str) -> Optional[PlayerRating]:
        return self.ratings.get(name)

    def get_top_players(self, n: int = 50, surface: str = None) -> pd.DataFrame:
        """Get top N players by overall or surface Elo."""
        data = []
        for player in self.ratings.values():
            if player.matches_played < 20:
                continue
            entry = player.to_dict()
            if surface:
                entry["sort_key"] = player.get_surface_elo(surface)
            else:
                entry["sort_key"] = player.overall
            data.append(entry)

        df = pd.DataFrame(data)
        if df.empty:
            return df
        return df.sort_values("sort_key", ascending=False).head(n).reset_index(drop=True)

    def find_edge(
        self,
        player_a: str,
        player_b: str,
        surface: str,
        market_odds_a: float,
    ) -> Dict:
        """
        Compare model probability vs market odds to find edge.
        
        Args:
            player_a: Player A name
            player_b: Player B name
            surface: Court surface
            market_odds_a: Decimal odds for player A (e.g., 1.80)
            
        Returns: dict with model_prob, market_prob, edge, recommendation
        """
        model_prob = self.predict_match(player_a, player_b, surface)
        market_prob = 1.0 / market_odds_a  # Convert decimal odds to implied prob

        edge = model_prob - market_prob

        return {
            "player_a": player_a,
            "player_b": player_b,
            "surface": surface,
            "model_prob_a": round(model_prob, 4),
            "market_prob_a": round(market_prob, 4),
            "edge": round(edge, 4),
            "edge_pct": f"{edge*100:.1f}%",
            "recommendation": "BET" if edge >= 0.03 else "SKIP",
            "confidence": "HIGH" if edge >= 0.08 else "MEDIUM" if edge >= 0.05 else "LOW",
        }


# --- CLI Usage ---
if __name__ == "__main__":
    engine = TennisEloEngine()
    engine.load_and_process(start_year=2000)

    print("\n=== TOP 20 PLAYERS (Overall Elo) ===")
    top = engine.get_top_players(20)
    print(top[["name", "overall", "hard", "clay", "grass"]].to_string(index=False))

    print("\n=== TOP 10 HARD COURT SPECIALISTS ===")
    hard = engine.get_top_players(10, surface="Hard")
    print(hard[["name", "overall", "hard", "clay", "grass"]].to_string(index=False))

    # Example prediction: Sinner vs Medvedev on Hard
    print("\n=== MATCH PREDICTION ===")
    prob = engine.predict_match("Jannik Sinner", "Daniil Medvedev", "Hard")
    print(f"Sinner vs Medvedev (Hard): Sinner {prob:.1%} | Medvedev {1-prob:.1%}")

    # Example edge finding
    edge = engine.find_edge("Jannik Sinner", "Daniil Medvedev", "Hard", 1.65)
    print(f"\nEdge analysis: {edge}")
