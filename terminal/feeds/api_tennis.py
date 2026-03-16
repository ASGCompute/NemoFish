"""
API-Tennis.com Integration
============================
Premium tennis data API with real-time scores, odds, H2H, and fixtures.

API Docs: https://api-tennis.com/documentation
Base URL: https://api.api-tennis.com/tennis/

Endpoints:
  - get_livescore   — Live match scores + point-by-point
  - get_fixtures    — Upcoming & past match fixtures
  - get_odds        — Pre-match odds from multiple bookmakers
  - get_live_odds   — Real-time in-play odds
  - get_H2H         — Head-to-head and recent form
  - get_players     — Player profiles
  - get_events      — Event types
  - get_tournaments — Tournament info
  - get_standings   — Rankings / standings
"""

import json
import os
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

# Load .env from project root
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

API_TENNIS_BASE = "https://api.api-tennis.com/tennis/"


@dataclass
class ApiTennisMatch:
    """Parsed match from api-tennis.com."""
    event_key: str
    date: str
    time: str
    player_a: str
    player_a_key: str
    player_b: str
    player_b_key: str
    final_result: str
    game_result: str
    serve: str              # "First Player" / "Second Player" / None
    winner: Optional[str]   # "First Player" / "Second Player" / None
    status: str             # "Set 1", "Set 2", "Finished", ""
    event_type: str         # "Atp Singles", "Wta Singles", etc
    tournament: str
    tournament_key: str
    round_name: str
    season: str
    is_live: bool
    scores: List[Dict]      # [{score_first, score_second, score_set}]
    player_a_logo: str
    player_b_logo: str


@dataclass
class ApiTennisOdds:
    """Odds from api-tennis.com (multi-bookmaker)."""
    event_key: str
    player_a: str
    player_b: str
    home_odds: Dict[str, float]    # bookmaker -> odds
    away_odds: Dict[str, float]
    best_home: float               # Best available odds
    best_away: float
    avg_home: float                # Average odds
    avg_away: float


@dataclass
class ApiTennisH2H:
    """Head-to-head data."""
    player_a: str
    player_b: str
    h2h_matches: List[Dict]
    player_a_recent: List[Dict]
    player_b_recent: List[Dict]
    h2h_record: str  # e.g. "3-2"


class ApiTennisClient:
    """
    Client for api-tennis.com API.
    
    Usage:
        client = ApiTennisClient()  # Uses default key
        live = client.get_livescore()
        odds = client.get_odds(match_key=159923)
        h2h = client.get_h2h(player_a_key=23, player_b_key=28)
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("API_TENNIS_KEY", "")
        self.base_url = API_TENNIS_BASE
        self._request_count = 0

    def _call(self, method: str, params: Dict = None) -> dict:
        """Make API call to api-tennis.com."""
        p = {"method": method, "APIkey": self.api_key}
        if params:
            p.update(params)

        query = "&".join(f"{k}={v}" for k, v in p.items() if v is not None)
        url = f"{self.base_url}?{query}"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                self._request_count += 1
                data = json.loads(resp.read().decode())
                if data.get("success") == 1:
                    return data
                else:
                    print(f"⚠️  API-Tennis error: {data.get('error', 'unknown')}")
                    return data
        except urllib.error.HTTPError as e:
            print(f"⚠️  API-Tennis HTTP {e.code}: {method}")
            return {}
        except Exception as e:
            print(f"⚠️  API-Tennis request failed: {e}")
            return {}

    # === Live Scores ===
    def get_livescore(self) -> List[ApiTennisMatch]:
        """Get all currently live tennis matches."""
        data = self._call("get_livescore")
        return self._parse_matches(data.get("result", []))

    # === Fixtures ===
    def get_fixtures(self, date_start: str = None, date_stop: str = None,
                     tournament_key: str = None) -> List[ApiTennisMatch]:
        """
        Get fixtures for a date range.
        
        Args:
            date_start: YYYY-MM-DD (defaults to today)
            date_stop: YYYY-MM-DD (defaults to today)
            tournament_key: Filter by tournament
        """
        if not date_start:
            date_start = datetime.now().strftime("%Y-%m-%d")
        if not date_stop:
            date_stop = date_start

        params = {"date_start": date_start, "date_stop": date_stop}
        if tournament_key:
            params["tournament_key"] = tournament_key

        data = self._call("get_fixtures", params)
        return self._parse_matches(data.get("result", []))

    # === Odds (pre-match) ===
    def get_odds(self, match_key: str) -> Optional[ApiTennisOdds]:
        """
        Get pre-match odds from multiple bookmakers.
        Returns odds from bwin, bet365, Betsson, 1xbet, etc.
        """
        data = self._call("get_odds", {"match_key": str(match_key)})
        result = data.get("result", {})

        if not result:
            return None

        # Result is keyed by event_key
        for event_key, odds_data in result.items():
            ha = odds_data.get("Home/Away", {})
            home = ha.get("Home", {})
            away = ha.get("Away", {})

            home_odds = {k: float(v) for k, v in home.items()}
            away_odds = {k: float(v) for k, v in away.items()}

            home_vals = list(home_odds.values()) or [0]
            away_vals = list(away_odds.values()) or [0]

            return ApiTennisOdds(
                event_key=str(event_key),
                player_a="Player 1",
                player_b="Player 2",
                home_odds=home_odds,
                away_odds=away_odds,
                best_home=max(home_vals),
                best_away=max(away_vals),
                avg_home=sum(home_vals) / len(home_vals) if home_vals else 0,
                avg_away=sum(away_vals) / len(away_vals) if away_vals else 0,
            )

        return None

    # === Live Odds ===
    def get_live_odds(self) -> Dict[str, Any]:
        """Get real-time odds for all live matches."""
        data = self._call("get_live_odds")
        return data.get("result", {})

    # === Head to Head ===
    def get_h2h(self, player_a_key: str, player_b_key: str) -> Optional[ApiTennisH2H]:
        """Get head-to-head history and recent form."""
        data = self._call("get_H2H", {
            "first_player_key": str(player_a_key),
            "second_player_key": str(player_b_key),
        })
        result = data.get("result", {})

        h2h_matches = result.get("H2H", [])
        p1_results = result.get("firstPlayerResults", [])
        p2_results = result.get("secondPlayerResults", [])

        # Calculate H2H record
        p1_wins = sum(1 for m in h2h_matches
                      if m.get("event_winner") == "First Player")
        p2_wins = len(h2h_matches) - p1_wins

        return ApiTennisH2H(
            player_a="Player 1",
            player_b="Player 2",
            h2h_matches=h2h_matches[:10],
            player_a_recent=p1_results[:5],
            player_b_recent=p2_results[:5],
            h2h_record=f"{p1_wins}-{p2_wins}",
        )

    # === Players ===
    def get_player(self, player_key: str) -> Dict:
        """Get player profile."""
        data = self._call("get_players", {"player_key": str(player_key)})
        results = data.get("result", [])
        return results[0] if results else {}

    # === Tournaments ===
    def get_tournaments(self) -> List[Dict]:
        """Get all tournaments."""
        data = self._call("get_tournaments")
        return data.get("result", [])

    # === Standings / Rankings ===
    def get_standings(self) -> List[Dict]:
        """Get current standings/rankings."""
        data = self._call("get_standings")
        return data.get("result", [])

    # === Internal: parse matches ===
    def _parse_matches(self, items: Any) -> List[ApiTennisMatch]:
        """Parse raw API response into ApiTennisMatch objects."""
        if not isinstance(items, list):
            return []

        matches = []
        for m in items:
            try:
                matches.append(ApiTennisMatch(
                    event_key=str(m.get("event_key", "")),
                    date=m.get("event_date", ""),
                    time=m.get("event_time", ""),
                    player_a=m.get("event_first_player", ""),
                    player_a_key=str(m.get("first_player_key", "")),
                    player_b=m.get("event_second_player", ""),
                    player_b_key=str(m.get("second_player_key", "")),
                    final_result=m.get("event_final_result", ""),
                    game_result=m.get("event_game_result", ""),
                    serve=m.get("event_serve", "") or "",
                    winner=m.get("event_winner"),
                    status=m.get("event_status", ""),
                    event_type=m.get("event_type_type", ""),
                    tournament=m.get("tournament_name", ""),
                    tournament_key=str(m.get("tournament_key", "")),
                    round_name=m.get("tournament_round", ""),
                    season=m.get("tournament_season", ""),
                    is_live=str(m.get("event_live", "0")) != "0",
                    scores=m.get("scores", []),
                    player_a_logo=m.get("event_first_player_logo") or "",
                    player_b_logo=m.get("event_second_player_logo") or "",
                ))
            except Exception as e:
                print(f"⚠️  Parse error: {e}")
                continue

        return matches

    # === Convenience: today's fixtures with odds ===
    def get_today_with_odds(self) -> List[Dict]:
        """
        Get today's fixtures enriched with pre-match odds.
        This is the primary method for the swarm's MarketBot agent.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        fixtures = self.get_fixtures(date_start=today, date_stop=today)

        enriched = []
        for match in fixtures:
            entry = asdict(match)

            # Only fetch odds for ATP/WTA singles (save API calls)
            if any(t in match.event_type.lower() for t in ["atp singles", "wta singles"]):
                odds = self.get_odds(match.event_key)
                if odds:
                    entry["odds"] = asdict(odds)

            enriched.append(entry)

        return enriched


# === CLI Demo ===
if __name__ == "__main__":
    client = ApiTennisClient()

    print("=" * 60)
    print("  🎾 API-TENNIS.COM — Live Integration Test")
    print("=" * 60)

    # 1. Live scores
    print("\n  🔴 LIVE SCORES")
    print("  " + "-" * 50)
    live = client.get_livescore()
    if live:
        for m in live[:10]:
            score = m.final_result if m.final_result != "-" else m.game_result
            serve = "🎾" if m.serve == "First Player" else "  "
            print(f"  {serve} {m.player_a} vs {m.player_b}")
            print(f"     {m.tournament} | {m.status} | {score}")
            if m.scores:
                sets = " ".join(f"{s.get('score_first', '')}-{s.get('score_second', '')}"
                               for s in m.scores)
                print(f"     Sets: {sets}")
        print(f"\n  Total live: {len(live)} matches")
    else:
        print("  No live matches currently")

    # 2. Today's fixtures
    print("\n  📅 TODAY'S FIXTURES")
    print("  " + "-" * 50)
    today = datetime.now().strftime("%Y-%m-%d")
    fixtures = client.get_fixtures(date_start=today, date_stop=today)
    atp_wta = [f for f in fixtures
               if any(t in f.event_type.lower() for t in ["atp singles", "wta singles"])]
    print(f"  Total fixtures: {len(fixtures)} | ATP/WTA Singles: {len(atp_wta)}")
    for f in atp_wta[:5]:
        print(f"  📋 {f.player_a} vs {f.player_b}")
        print(f"     {f.tournament} {f.round_name} | {f.time}")

    print(f"\n  📊 Total API requests used: {client._request_count}")
