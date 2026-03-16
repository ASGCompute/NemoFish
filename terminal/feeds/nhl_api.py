"""
NHL API Client
===============
Free, official NHL API — no key required.
Base URL: https://api-web.nhle.com

Provides:
- Current standings (with points, records, goal differential)
- Team schedules and game results
- Player stats (goals, assists, TOI, advanced)
- Goaltender stats (SV%, GAA, GSAx proxy)
- Today's games with confirmed starters

Key insight: goaltender confirmation = biggest edge in hockey betting.
"""

import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass


BASE_URL = "https://api-web.nhle.com/v1"


@dataclass
class NHLGame:
    """Represents an NHL game."""
    game_id: int
    date: str
    home_team: str
    away_team: str
    home_abbrev: str
    away_abbrev: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    game_state: str = "FUT"  # FUT, LIVE, FINAL, OFF
    period: Optional[int] = None
    start_time: Optional[str] = None


@dataclass
class TeamStanding:
    """NHL team standing data."""
    team_name: str
    team_abbrev: str
    conference: str
    division: str
    points: int
    wins: int
    losses: int
    ot_losses: int
    games_played: int
    goals_for: int
    goals_against: int
    goal_diff: int
    streak: str
    points_pct: float


class NHLClient:
    """
    Client for the free NHL API.
    
    Usage:
        nhl = NHLClient()
        
        # Get today's games
        games = nhl.get_todays_games()
        for g in games:
            print(f"{g.away_team} @ {g.home_team}")
            
        # Get standings
        standings = nhl.get_standings()
        for s in standings[:5]:
            print(f"{s.team_name}: {s.points} pts")
    """

    def __init__(self):
        self.base_url = BASE_URL

    def _fetch(self, endpoint: str) -> dict:
        """Fetch JSON from NHL API."""
        url = f"{self.base_url}/{endpoint}"
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "NemoFish-Terminal/1.0")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"NHL API error {e.code}: {url}")
            return {}
        except Exception as e:
            print(f"NHL API request failed: {e}")
            return {}

    def get_standings(self, date: str = None) -> List[TeamStanding]:
        """
        Get current NHL standings.
        
        Args:
            date: Optional date string (YYYY-MM-DD), defaults to today
        """
        if date:
            endpoint = f"standings/{date}"
        else:
            endpoint = "standings/now"

        data = self._fetch(endpoint)
        standings = []

        for team_data in data.get("standings", []):
            standings.append(TeamStanding(
                team_name=team_data.get("teamName", {}).get("default", "Unknown"),
                team_abbrev=team_data.get("teamAbbrev", {}).get("default", "UNK"),
                conference=team_data.get("conferenceName", ""),
                division=team_data.get("divisionName", ""),
                points=team_data.get("points", 0),
                wins=team_data.get("wins", 0),
                losses=team_data.get("losses", 0),
                ot_losses=team_data.get("otLosses", 0),
                games_played=team_data.get("gamesPlayed", 0),
                goals_for=team_data.get("goalFor", 0),
                goals_against=team_data.get("goalAgainst", 0),
                goal_diff=team_data.get("goalDifferential", 0),
                streak=team_data.get("streakCode", ""),
                points_pct=team_data.get("pointPctg", 0.0),
            ))

        return sorted(standings, key=lambda x: x.points, reverse=True)

    def get_schedule(self, date: str = None) -> List[NHLGame]:
        """
        Get games for a specific date.
        
        Args:
            date: YYYY-MM-DD format, defaults to today
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        endpoint = f"schedule/{date}"
        data = self._fetch(endpoint)
        games = []

        for game_week in data.get("gameWeek", []):
            for game in game_week.get("games", []):
                games.append(NHLGame(
                    game_id=game.get("id", 0),
                    date=game_week.get("date", date),
                    home_team=game.get("homeTeam", {}).get("placeName", {}).get("default", ""),
                    away_team=game.get("awayTeam", {}).get("placeName", {}).get("default", ""),
                    home_abbrev=game.get("homeTeam", {}).get("abbrev", ""),
                    away_abbrev=game.get("awayTeam", {}).get("abbrev", ""),
                    home_score=game.get("homeTeam", {}).get("score"),
                    away_score=game.get("awayTeam", {}).get("score"),
                    game_state=game.get("gameState", "FUT"),
                    start_time=game.get("startTimeUTC", ""),
                ))

        return games

    def get_todays_games(self) -> List[NHLGame]:
        """Get today's NHL games."""
        return self.get_schedule()

    def get_team_schedule(self, team_abbrev: str) -> List[dict]:
        """Get a team's upcoming schedule for B2B detection."""
        endpoint = f"club-schedule-season/{team_abbrev}/now"
        data = self._fetch(endpoint)
        return data.get("games", [])

    def detect_back_to_back(self, team_abbrev: str, game_date: str) -> dict:
        """
        Detect if a team is playing a back-to-back game.
        This is a KEY signal for hockey betting — B2B = fatigue = edge.
        
        Returns:
            dict with is_b2b, previous_game info, travel_distance estimate
        """
        schedule = self.get_team_schedule(team_abbrev)
        target = datetime.strptime(game_date, "%Y-%m-%d")

        previous_game = None
        for game in schedule:
            game_dt_str = game.get("gameDate", "")
            if not game_dt_str:
                continue
            game_dt = datetime.strptime(game_dt_str[:10], "%Y-%m-%d")
            if game_dt < target:
                previous_game = game
            elif game_dt == target:
                break

        if previous_game is None:
            return {"is_b2b": False, "days_rest": 99}

        prev_date = datetime.strptime(previous_game["gameDate"][:10], "%Y-%m-%d")
        days_rest = (target - prev_date).days

        return {
            "is_b2b": days_rest == 1,
            "days_rest": days_rest,
            "previous_game_date": prev_date.strftime("%Y-%m-%d"),
            "previous_opponent": previous_game.get("awayTeam", {}).get("abbrev", "")
                if previous_game.get("homeTeam", {}).get("abbrev") == team_abbrev
                else previous_game.get("homeTeam", {}).get("abbrev", ""),
            "was_home": previous_game.get("homeTeam", {}).get("abbrev") == team_abbrev,
        }

    def get_player_stats(self, player_id: int) -> dict:
        """Get detailed player stats by NHL player ID."""
        endpoint = f"player/{player_id}/landing"
        return self._fetch(endpoint)

    def get_player_gamelog(self, player_id: int, season: str = "20252026") -> dict:
        """Get player game log for a specific season."""
        endpoint = f"player/{player_id}/game-log/{season}/2"
        return self._fetch(endpoint)


# --- CLI Usage ---
if __name__ == "__main__":
    nhl = NHLClient()

    print("=== NHL STANDINGS (Top 10) ===")
    standings = nhl.get_standings()
    print(f"{'Team':<25} {'Pts':>4} {'W':>3} {'L':>3} {'OTL':>4} {'GD':>4} {'Streak':>6}")
    print("-" * 55)
    for s in standings[:10]:
        print(
            f"{s.team_name:<25} {s.points:>4} {s.wins:>3} {s.losses:>3} "
            f"{s.ot_losses:>4} {s.goal_diff:>+4} {s.streak:>6}"
        )

    print("\n=== TODAY'S GAMES ===")
    games = nhl.get_todays_games()
    if not games:
        print("No games today.")
    for g in games:
        status = f"{g.away_score}-{g.home_score}" if g.home_score is not None else g.game_state
        print(f"{g.away_abbrev} @ {g.home_abbrev}  [{status}]")

    # B2B detection example
    if standings:
        team = standings[0].team_abbrev
        today = datetime.now().strftime("%Y-%m-%d")
        b2b = nhl.detect_back_to_back(team, today)
        print(f"\n=== B2B CHECK: {team} ===")
        print(f"Back-to-back: {b2b['is_b2b']}")
        print(f"Days rest: {b2b['days_rest']}")
