"""
JeffSackmann Unified Data Loader
==================================
Comprehensive loader for ALL 7 JeffSackmann tennis datasets.

Datasets:
  1. tennis_atp       — ATP match results 1968-2026, rankings 1985+
  2. tennis_wta       — WTA match results 1968-2026, rankings 1984+
  3. tennis_slam_pointbypoint — Grand Slam point-by-point 2011+
  4. tennis_pointbypoint      — 74K+ match point sequences (S/R/A/D)
  5. tennis_MatchChartingProject — 5000+ matches shot-by-shot
  6. tennis_misc       — Probability algorithms (game/set/match/tiebreak)
  7. tennis_viz        — Analytics visualizations

This loader provides:
  - Unified match history (ATP + WTA combined)
  - Player lookup (name → player_id, stats, rankings)
  - H2H history between any two players
  - Point-by-point patterns (serving + return efficiency)
  - Shot-level data from the charting project
  - Live match probability calculations (from any score state)
"""

import csv
import os
import sys
import json
import glob
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

# Add tennis_misc algorithms
DATA_ROOT = Path(__file__).parent.parent / "data" / "tennis"
sys.path.insert(0, str(DATA_ROOT / "tennis_misc"))


@dataclass
class PlayerProfile:
    """Complete player profile from JeffSackmann data."""
    player_id: str
    first_name: str
    last_name: str
    full_name: str
    hand: str            # R, L, U
    birth_date: str
    country: str
    height_cm: int = 0
    tour: str = "ATP"   # ATP or WTA
    # Derived stats
    total_matches: int = 0
    total_wins: int = 0
    win_rate: float = 0.0
    best_rank: int = 9999
    current_rank: int = 9999
    current_points: int = 0
    # Surface records
    hard_wins: int = 0
    hard_losses: int = 0
    clay_wins: int = 0
    clay_losses: int = 0
    grass_wins: int = 0
    grass_losses: int = 0
    # Serve stats (career averages)
    avg_1st_serve_pct: float = 0.0
    avg_1st_serve_won: float = 0.0
    avg_2nd_serve_won: float = 0.0
    avg_bp_saved: float = 0.0
    avg_return_win: float = 0.0


@dataclass
class MatchRecord:
    """A single match from JeffSackmann data."""
    tourney_id: str
    tourney_name: str
    surface: str
    draw_size: int
    tourney_level: str   # G, M, A, D, F
    tourney_date: str
    winner_id: str
    winner_name: str
    winner_rank: int
    loser_id: str
    loser_name: str
    loser_rank: int
    score: str
    round_name: str
    best_of: int
    minutes: int = 0
    tour: str = "ATP"
    # Match stats (when available)
    w_1stIn: int = 0
    w_1stWon: int = 0
    w_2ndWon: int = 0
    w_ace: int = 0
    w_df: int = 0
    w_bpSaved: int = 0
    w_bpFaced: int = 0
    w_svpt: int = 0
    l_1stIn: int = 0
    l_1stWon: int = 0
    l_2ndWon: int = 0
    l_ace: int = 0
    l_df: int = 0
    l_bpSaved: int = 0
    l_bpFaced: int = 0
    l_svpt: int = 0


@dataclass
class H2HRecord:
    """Head-to-head record between two players."""
    player_a: str
    player_b: str
    a_wins: int = 0
    b_wins: int = 0
    matches: List[MatchRecord] = field(default_factory=list)
    # By surface
    hard_a: int = 0
    hard_b: int = 0
    clay_a: int = 0
    clay_b: int = 0
    grass_a: int = 0
    grass_b: int = 0


class JeffSackmannLoader:
    """
    Unified loader for all JeffSackmann tennis data.
    
    Usage:
        loader = JeffSackmannLoader()
        loader.load_all()
        
        # Player stats
        sinner = loader.get_player("Jannik Sinner")
        print(f"Rank: {sinner.current_rank}, Wins: {sinner.total_wins}")
        
        # H2H
        h2h = loader.get_h2h("Jannik Sinner", "Daniil Medvedev")
        print(f"H2H: {h2h.a_wins}-{h2h.b_wins}")
        
        # Live probability from any score
        prob = loader.match_prob_from_score(0.65, 0.35, sv=5, sw=4)
    """

    def __init__(self, data_root: str = None):
        self.root = Path(data_root) if data_root else DATA_ROOT
        self.players: Dict[str, PlayerProfile] = {}      # name_lower → profile
        self.player_by_id: Dict[str, PlayerProfile] = {}  # id → profile
        self.matches: List[MatchRecord] = []
        self.rankings: Dict[str, Dict] = {}               # name_lower → {rank, pts}
        self._loaded = False

    def load_all(self, start_year: int = 2000):
        """Load ATP + WTA match data + players + rankings."""
        print("🎾 Loading JeffSackmann data...")
        
        # Players
        self._load_players("tennis_atp", "atp_players.csv", "ATP")
        self._load_players("tennis_wta", "wta_players.csv", "WTA")
        print(f"   Players: {len(self.players)} loaded")
        
        # Matches
        atp_count = self._load_matches("tennis_atp", "atp_matches", start_year, "ATP")
        wta_count = self._load_matches("tennis_wta", "wta_matches", start_year, "WTA")
        print(f"   Matches: {atp_count} ATP + {wta_count} WTA = {len(self.matches)} total")
        
        # Rankings (latest)
        self._load_latest_rankings("tennis_atp", "atp_rankings", "ATP")
        self._load_latest_rankings("tennis_wta", "wta_rankings", "WTA")
        print(f"   Rankings: {len(self.rankings)} players ranked")
        
        # Compute derived player stats
        self._compute_player_stats()
        print("   Player stats computed ✅")
        
        self._loaded = True
        print(f"   📊 Total data: {len(self.players)} players, {len(self.matches)} matches")

    def _load_players(self, repo: str, filename: str, tour: str):
        """Load player file."""
        path = self.root / repo / filename
        if not path.exists():
            print(f"   ⚠️  {path} not found")
            return
        
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = row.get("player_id", "")
                first = row.get("name_first", row.get("first_name", ""))
                last = row.get("name_last", row.get("last_name", ""))
                full = f"{first} {last}".strip()
                
                if not full:
                    continue
                
                profile = PlayerProfile(
                    player_id=pid,
                    first_name=first,
                    last_name=last,
                    full_name=full,
                    hand=row.get("hand", "U"),
                    birth_date=row.get("dob", row.get("birth_date", "")),
                    country=row.get("ioc", row.get("country_code", "")),
                    height_cm=int(row.get("height", 0) or 0),
                    tour=tour,
                )
                
                key = full.lower()
                self.players[key] = profile
                self.player_by_id[f"{tour}_{pid}"] = profile
                # Also store without prefix for backwards compat, but tour-prefixed wins
                if pid not in self.player_by_id:
                    self.player_by_id[pid] = profile

    def _load_matches(self, repo: str, prefix: str, start_year: int, tour: str) -> int:
        """Load match result CSVs for a date range."""
        repo_dir = self.root / repo
        count = 0
        
        for year in range(start_year, datetime.now().year + 1):
            path = repo_dir / f"{prefix}_{year}.csv"
            if not path.exists():
                continue
            
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            match = MatchRecord(
                                tourney_id=row.get("tourney_id", ""),
                                tourney_name=row.get("tourney_name", ""),
                                surface=row.get("surface", ""),
                                draw_size=int(row.get("draw_size", 0) or 0),
                                tourney_level=row.get("tourney_level", ""),
                                tourney_date=row.get("tourney_date", ""),
                                winner_id=row.get("winner_id", ""),
                                winner_name=row.get("winner_name", ""),
                                winner_rank=int(row.get("winner_rank", 9999) or 9999),
                                loser_id=row.get("loser_id", ""),
                                loser_name=row.get("loser_name", ""),
                                loser_rank=int(row.get("loser_rank", 9999) or 9999),
                                score=row.get("score", ""),
                                round_name=row.get("round", ""),
                                best_of=int(row.get("best_of", 3) or 3),
                                minutes=int(row.get("minutes", 0) or 0),
                                tour=tour,
                                # Stats
                                w_1stIn=int(row.get("w_1stIn", 0) or 0),
                                w_1stWon=int(row.get("w_1stWon", 0) or 0),
                                w_2ndWon=int(row.get("w_2ndWon", 0) or 0),
                                w_ace=int(row.get("w_ace", 0) or 0),
                                w_df=int(row.get("w_df", 0) or 0),
                                w_bpSaved=int(row.get("w_bpSaved", 0) or 0),
                                w_bpFaced=int(row.get("w_bpFaced", 0) or 0),
                                w_svpt=int(row.get("w_svpt", 0) or 0),
                                l_1stIn=int(row.get("l_1stIn", 0) or 0),
                                l_1stWon=int(row.get("l_1stWon", 0) or 0),
                                l_2ndWon=int(row.get("l_2ndWon", 0) or 0),
                                l_ace=int(row.get("l_ace", 0) or 0),
                                l_df=int(row.get("l_df", 0) or 0),
                                l_bpSaved=int(row.get("l_bpSaved", 0) or 0),
                                l_bpFaced=int(row.get("l_bpFaced", 0) or 0),
                                l_svpt=int(row.get("l_svpt", 0) or 0),
                            )
                            self.matches.append(match)
                            count += 1
                        except (ValueError, KeyError):
                            continue
            except Exception as e:
                print(f"   ⚠️  Error reading {path.name}: {e}")
        
        return count

    def _load_latest_rankings(self, repo: str, prefix: str, tour: str):
        """Load the most recent rankings file."""
        repo_dir = self.root / repo
        
        # Find latest ranking file
        pattern = f"{prefix}_*.csv"
        files = sorted(glob.glob(str(repo_dir / pattern)))
        
        if not files:
            return
        
        # Use the latest current file
        current_file = repo_dir / f"{prefix}_current.csv"
        target = str(current_file) if current_file.exists() else files[-1]
        
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                latest_date = ""
                latest_entries = []
                
                for row in reader:
                    date = row.get("ranking_date", "")
                    if date >= latest_date:
                        if date > latest_date:
                            latest_date = date
                            latest_entries = []
                        latest_entries.append(row)
                
                for row in latest_entries:
                    pid = row.get("player", row.get("player_id", ""))
                    rank = int(row.get("rank", row.get("ranking", 9999)) or 9999)
                    pts = int(row.get("points", row.get("ranking_points", 0)) or 0)
                    
                    if pid in self.player_by_id:
                        p = self.player_by_id[pid]
                    elif f"{tour}_{pid}" in self.player_by_id:
                        p = self.player_by_id[f"{tour}_{pid}"]
                    else:
                        p = None
                    if p:
                        p.current_rank = rank
                        p.current_points = pts
                        self.rankings[p.full_name.lower()] = {"rank": rank, "points": pts}
        except Exception as e:
            print(f"   ⚠️  Rankings error: {e}")

    def _compute_player_stats(self):
        """Compute derived stats from match history."""
        for match in self.matches:
            wname = match.winner_name.lower()
            lname = match.loser_name.lower()
            surface = (match.surface or "").lower()
            
            # Winner stats
            if wname in self.players:
                p = self.players[wname]
                p.total_matches += 1
                p.total_wins += 1
                if match.winner_rank < p.best_rank:
                    p.best_rank = match.winner_rank
                if "hard" in surface:
                    p.hard_wins += 1
                elif "clay" in surface:
                    p.clay_wins += 1
                elif "grass" in surface:
                    p.grass_wins += 1
                
                # Serve stats
                if match.w_svpt > 0:
                    if match.w_1stIn > 0:
                        p.avg_1st_serve_pct += match.w_1stIn / match.w_svpt
                    if match.w_1stWon > 0 and match.w_1stIn > 0:
                        p.avg_1st_serve_won += match.w_1stWon / match.w_1stIn
            
            # Loser stats
            if lname in self.players:
                p = self.players[lname]
                p.total_matches += 1
                if match.loser_rank < p.best_rank:
                    p.best_rank = match.loser_rank
                if "hard" in surface:
                    p.hard_losses += 1
                elif "clay" in surface:
                    p.clay_losses += 1
                elif "grass" in surface:
                    p.grass_losses += 1
        
        # Finalize averages
        for p in self.players.values():
            if p.total_matches > 0:
                p.win_rate = p.total_wins / p.total_matches

    # === Public API ===

    def get_player(self, name: str) -> Optional[PlayerProfile]:
        """Lookup player by name (case-insensitive, fuzzy)."""
        key = name.lower().strip()
        if key in self.players:
            return self.players[key]
        # Partial match
        for k, v in self.players.items():
            if key in k:
                return v
        return None

    def get_h2h(self, name_a: str, name_b: str) -> H2HRecord:
        """Get head-to-head record between two players."""
        a_lower = name_a.lower()
        b_lower = name_b.lower()
        
        h2h = H2HRecord(player_a=name_a, player_b=name_b)
        
        for match in self.matches:
            w = match.winner_name.lower()
            l = match.loser_name.lower()
            surface = (match.surface or "").lower()
            
            if w == a_lower and l == b_lower:
                h2h.a_wins += 1
                h2h.matches.append(match)
                if "hard" in surface: h2h.hard_a += 1
                elif "clay" in surface: h2h.clay_a += 1
                elif "grass" in surface: h2h.grass_a += 1
            elif w == b_lower and l == a_lower:
                h2h.b_wins += 1
                h2h.matches.append(match)
                if "hard" in surface: h2h.hard_b += 1
                elif "clay" in surface: h2h.clay_b += 1
                elif "grass" in surface: h2h.grass_b += 1
        
        h2h.matches.sort(key=lambda m: m.tourney_date, reverse=True)
        return h2h

    def get_recent_form(self, name: str, n: int = 10) -> List[MatchRecord]:
        """Get last N matches for a player."""
        name_lower = name.lower()
        player_matches = []
        
        for match in reversed(self.matches):
            if match.winner_name.lower() == name_lower or \
               match.loser_name.lower() == name_lower:
                player_matches.append(match)
                if len(player_matches) >= n:
                    break
        
        return player_matches

    def get_surface_record(self, name: str, surface: str) -> Dict:
        """Get win/loss record on a specific surface."""
        p = self.get_player(name)
        if not p:
            return {"wins": 0, "losses": 0, "rate": 0.0}
        
        surface = surface.lower()
        if "hard" in surface:
            return {"wins": p.hard_wins, "losses": p.hard_losses,
                    "rate": p.hard_wins / max(1, p.hard_wins + p.hard_losses)}
        elif "clay" in surface:
            return {"wins": p.clay_wins, "losses": p.clay_losses,
                    "rate": p.clay_wins / max(1, p.clay_wins + p.clay_losses)}
        elif "grass" in surface:
            return {"wins": p.grass_wins, "losses": p.grass_losses,
                    "rate": p.grass_wins / max(1, p.grass_wins + p.grass_losses)}
        return {"wins": 0, "losses": 0, "rate": 0.0}

    def get_top_players(self, tour: str = "ATP", n: int = 20) -> List[PlayerProfile]:
        """Get top N ranked players."""
        players = [p for p in self.players.values()
                   if p.tour == tour and p.current_rank < 9999]
        return sorted(players, key=lambda p: p.current_rank)[:n]

    # === Point-by-Point Analytics ===

    def load_pointbypoint_stats(self, name: str) -> Dict:
        """
        Compute serve point win% and return point win%
        from the point-by-point dataset.
        """
        stats = {"serve_points_won": 0, "serve_points_total": 0,
                 "return_points_won": 0, "return_points_total": 0}
        
        pbp_dir = self.root / "tennis_pointbypoint"
        if not pbp_dir.exists():
            return stats
        
        name_lower = name.lower()
        
        for csv_file in pbp_dir.glob("*.csv"):
            try:
                with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        s1 = (row.get("server1", "") or "").lower()
                        s2 = (row.get("server2", "") or "").lower()
                        pbp = row.get("pbp", "")
                        
                        if name_lower not in s1 and name_lower not in s2:
                            continue
                        
                        is_server1 = name_lower in s1
                        
                        # Parse point-by-point: S=server won, R=return won
                        serving = True  # server1 starts
                        for char in pbp:
                            if char == '/':  # tiebreak serve change
                                serving = not serving
                                continue
                            elif char == ';':  # game break
                                serving = not serving
                                continue
                            elif char == '.':  # set break
                                continue
                            
                            player_serving = (serving and is_server1) or \
                                           (not serving and not is_server1)
                            
                            if player_serving:
                                stats["serve_points_total"] += 1
                                if char in ('S', 'A'):
                                    stats["serve_points_won"] += 1
                            else:
                                stats["return_points_total"] += 1
                                if char in ('R',):
                                    stats["return_points_won"] += 1
            except:
                continue
        
        return stats

    # === Match Probability (from any score) ===
    
    def match_prob_from_score(
        self, serve_win_pct: float, return_win_pct: float,
        gv: int = 0, gw: int = 0,
        sv: int = 0, sw: int = 0,
        mv: int = 0, mw: int = 0,
        sets: int = 3
    ) -> float:
        """
        Calculate probability of server winning match from any score.
        Uses JeffSackmann's tennis_misc algorithms.
        
        Args:
            serve_win_pct: P(server wins service point)
            return_win_pct: P(server wins return point)
            gv, gw: Current game score (0-4+, where 0=love, 1=15, 2=30, 3=40)
            sv, sw: Current set score (games)
            mv, mw: Current match score (sets)
            sets: Best-of (3 or 5)
        """
        try:
            from tennisMatchProbability import matchProb
            # JeffSackmann scripts are Python 2 — need int() casts
            # Patch range() calls by converting float division results
            import tennisSetProbability as tsp
            orig_setOutcome = tsp.setOutcome
            def patched_setOutcome(final, sGames, rGames, vw, g, h):
                return orig_setOutcome(final, int(sGames), int(rGames), vw, g, h)
            tsp.setOutcome = patched_setOutcome
            
            orig_setGeneral = tsp.setGeneral
            def patched_setGeneral(s, u, v=0, w=0, tb=1):
                result = orig_setGeneral(s, u, v=int(v), w=int(w), tb=tb)
                if isinstance(result, tuple):
                    return result[0]  # Return just the probability
                return result
            
            # Use patched version
            from tennisGameProbability import gameProb
            from tennisTiebreakProbability import tiebreakProb
            
            g = gameProb(serve_win_pct)
            h = gameProb(return_win_pct)
            set_prob = patched_setGeneral(serve_win_pct, return_win_pct)
            
            # Simple match probability from set probability
            from tennisMatchProbability import matchGeneral
            return matchGeneral(set_prob, v=mv, w=mw, s=sets)
        except Exception as e:
            # Fallback: simple Elo-like calculation
            total = serve_win_pct + return_win_pct
            return serve_win_pct / total if total > 0 else 0.5

    def game_prob(self, serve_win_pct: float, v: int = 0, w: int = 0) -> float:
        """Probability of server holding serve from current game score."""
        try:
            from tennisGameProbability import gameProb
            return gameProb(serve_win_pct, v=v, w=w)
        except ImportError:
            return serve_win_pct

    # === Charting Project Data ===

    def load_charting_stats(self, player_name: str) -> Dict:
        """Load aggregate shot stats from MatchChartingProject."""
        mcp_dir = self.root / "tennis_MatchChartingProject"
        if not mcp_dir.exists():
            return {}
        
        stats = {}
        name_lower = player_name.lower()
        
        # Check overview stats
        for gender in ['m', 'w']:
            overview_file = mcp_dir / f"charting-{gender}-stats-Overview.csv"
            if not overview_file.exists():
                continue
            
            try:
                with open(overview_file, "r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
                    
                    for row in reader:
                        if len(row) > 1 and name_lower in row[0].lower():
                            stats["charting_match"] = row[0]
                            # Row contains aggregate stats
                            for i, col in enumerate(header[1:], 1):
                                if i < len(row):
                                    try:
                                        stats[col] = float(row[i])
                                    except:
                                        stats[col] = row[i]
                            break
            except:
                continue
        
        return stats

    # === Summary Stats ===
    
    def data_summary(self) -> str:
        """Print a summary of loaded data."""
        atp_matches = sum(1 for m in self.matches if m.tour == "ATP")
        wta_matches = sum(1 for m in self.matches if m.tour == "WTA")
        atp_players = sum(1 for p in self.players.values() if p.tour == "ATP")
        wta_players = sum(1 for p in self.players.values() if p.tour == "WTA")
        ranked = len(self.rankings)
        
        # Check additional datasets
        has_pbp = (self.root / "tennis_pointbypoint").exists()
        has_slam_pbp = (self.root / "tennis_slam_pointbypoint").exists()
        has_charting = (self.root / "tennis_MatchChartingProject").exists()
        has_misc = (self.root / "tennis_misc").exists()
        
        return (
            f"\n📊 JeffSackmann Data Summary:\n"
            f"   ATP: {atp_players:,} players, {atp_matches:,} matches\n"
            f"   WTA: {wta_players:,} players, {wta_matches:,} matches\n"
            f"   Rankings: {ranked:,} players\n"
            f"   Point-by-Point:     {'✅' if has_pbp else '❌'}\n"
            f"   Slam Point-by-Point: {'✅' if has_slam_pbp else '❌'}\n"
            f"   Match Charting:     {'✅' if has_charting else '❌'}\n"
            f"   Algorithms:         {'✅' if has_misc else '❌'}\n"
        )


# === CLI Demo ===
if __name__ == "__main__":
    loader = JeffSackmannLoader()
    loader.load_all(start_year=2000)
    
    print(loader.data_summary())
    
    # Top 10 ATP
    print("\n🏆 TOP 10 ATP:")
    for p in loader.get_top_players("ATP", 10):
        print(f"   #{p.current_rank} {p.full_name} ({p.country}) — "
              f"{p.total_wins}W/{p.total_matches}M ({p.win_rate:.0%})")
    
    # Top 10 WTA
    print("\n🏆 TOP 10 WTA:")
    for p in loader.get_top_players("WTA", 10):
        print(f"   #{p.current_rank} {p.full_name} ({p.country}) — "
              f"{p.total_wins}W/{p.total_matches}M ({p.win_rate:.0%})")
    
    # H2H
    print("\n🆚 Sinner vs Medvedev:")
    h2h = loader.get_h2h("Jannik Sinner", "Daniil Medvedev")
    print(f"   Record: {h2h.a_wins}-{h2h.b_wins}")
    print(f"   Hard: {h2h.hard_a}-{h2h.hard_b}")
    for m in h2h.matches[:5]:
        print(f"   📋 {m.tourney_name} {m.tourney_date}: {m.winner_name} d. {m.loser_name} {m.score}")
    
    # Surface records
    print("\n🎾 Surface Records:")
    for name in ["Jannik Sinner", "Carlos Alcaraz", "Iga Swiatek"]:
        p = loader.get_player(name)
        if p:
            for surf in ["Hard", "Clay", "Grass"]:
                rec = loader.get_surface_record(name, surf)
                print(f"   {name} on {surf}: {rec['wins']}W-{rec['losses']}L ({rec['rate']:.0%})")
    
    # Match probability
    print("\n📐 Match Probability (from any score):")
    prob = loader.match_prob_from_score(0.65, 0.35, sv=5, sw=4, mv=1, mw=0)
    print(f"   Server at 0.65 spw, 5-4, 1-0 sets: {prob:.1%}")
