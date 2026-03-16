"""
Sportradar Tennis API Client
===============================
Premium data source for tennis with live summaries, rankings, 
competitor profiles, and live probabilities.

API Docs: https://developer.sportradar.com/tennis/reference/overview
Base URL: https://api.sportradar.com/tennis/production/v3/

Key Endpoints:
  - /live/summaries         — Live match summaries with scores
  - /rankings               — ATP/WTA rankings
  - /competitors/{id}/profile — Player profiles
  - /live/probabilities     — Real-time win probabilities
  - /competitions           — All tennis competitions
  - /seasons                — Tournament seasons
  - /sport_events/{id}/summary     — Single match summary
  - /sport_events/{id}/timeline    — Point-by-point timeline
  - /sport_events/updated          — Recently updated events
  - /sport_events/created          — Recently created events
"""

import json
import os
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# Load .env from project root
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SPORTRADAR_BASE = "https://api.sportradar.com/tennis/production/v3"


@dataclass
class SRMatch:
    """Parsed live match from Sportradar."""
    event_id: str
    start_time: str
    status: str              # "live", "closed", "not_started"
    player_a: str
    player_a_id: str
    player_a_seed: Optional[int]
    player_b: str
    player_b_id: str
    player_b_seed: Optional[int]
    competition: str
    season: str
    home_score: Optional[int]
    away_score: Optional[int]
    period_scores: List[Dict]  # [{home_score, away_score, type, number}]
    winner_id: Optional[str]
    raw: Dict


@dataclass
class SRRanking:
    """Player ranking entry."""
    rank: int
    points: int
    player_name: str
    player_id: str
    nationality: str
    movement: int           # Positive = up, negative = down


@dataclass
class SRCompetitorProfile:
    """Competitor profile with stats."""
    player_id: str
    name: str
    nationality: str
    birthday: str
    height: Optional[int]   # cm
    weight: Optional[int]   # kg
    handedness: str
    pro_year: Optional[int]
    ranking: Optional[int]
    doubles_ranking: Optional[int]
    prize_money: Optional[float]
    raw: Dict


@dataclass
class SRProbability:
    """Live probability for a match."""
    event_id: str
    player_a: str
    player_b: str
    prob_a: float
    prob_b: float
    market_name: str
    raw: Dict


class SportradarTennisClient:
    """
    Client for Sportradar Tennis API v3.
    
    Usage:
        client = SportradarTennisClient()
        live = client.get_live_summaries()
        rankings = client.get_rankings()
        profile = client.get_competitor_profile("sr:competitor:12345")
        probabilities = client.get_live_probabilities()
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("SPORTRADAR_API_KEY", "")
        self.base_url = SPORTRADAR_BASE
        self._request_count = 0

    def _call(self, endpoint: str, params: Dict = None) -> dict:
        """Make API call to Sportradar."""
        url = f"{self.base_url}/{endpoint}.json?api_key={self.api_key}"
        if params:
            extra = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url += f"&{extra}"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                self._request_count += 1
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print(f"⚠️  Sportradar 403 Forbidden — check API key/plan for: {endpoint}")
            elif e.code == 429:
                print(f"⚠️  Sportradar rate limit hit: {endpoint}")
            else:
                print(f"⚠️  Sportradar HTTP {e.code}: {endpoint}")
            return {}
        except Exception as e:
            print(f"⚠️  Sportradar request failed: {e}")
            return {}

    # === Live Summaries ===
    def get_live_summaries(self) -> List[SRMatch]:
        """
        Get all currently live tennis matches with scores and stats.
        Endpoint: /live/summaries
        """
        data = self._call("en/live/summaries")
        summaries = data.get("summaries", [])
        return self._parse_summaries(summaries)

    # === Rankings ===
    def get_rankings(self) -> Dict[str, List[SRRanking]]:
        """
        Get current ATP and WTA rankings.
        Returns dict like: {"atp": [...], "wta": [...]}
        """
        data = self._call("en/rankings")
        rankings_data = data.get("rankings", [])

        result = {}
        for ranking_group in rankings_data:
            group_name = ranking_group.get("name", "").lower()
            entries = ranking_group.get("competitor_rankings", [])
            
            parsed = []
            for entry in entries[:100]:  # Top 100
                competitor = entry.get("competitor", {})
                parsed.append(SRRanking(
                    rank=entry.get("rank", 0),
                    points=entry.get("points", 0),
                    player_name=competitor.get("name", ""),
                    player_id=competitor.get("id", ""),
                    nationality=competitor.get("nationality", ""),
                    movement=entry.get("movement", 0),
                ))
            
            if "atp" in group_name or "men" in group_name:
                result["atp"] = parsed
            elif "wta" in group_name or "women" in group_name:
                result["wta"] = parsed
            else:
                key = group_name.replace(" ", "_")[:20]
                result[key] = parsed

        return result

    # === Competitor Profile ===
    def get_competitor_profile(self, competitor_id: str) -> Optional[SRCompetitorProfile]:
        """
        Get detailed player profile.
        competitor_id: Sportradar ID, e.g. "sr:competitor:12345"
        """
        # Clean the ID format
        clean_id = competitor_id.replace(":", "%3A")
        data = self._call(f"en/competitors/{clean_id}/profile")

        if not data:
            return None

        competitor = data.get("competitor", {})
        info = data.get("info", {})

        return SRCompetitorProfile(
            player_id=competitor.get("id", ""),
            name=competitor.get("name", ""),
            nationality=competitor.get("nationality", ""),
            birthday=info.get("date_of_birth", ""),
            height=info.get("height"),
            weight=info.get("weight"),
            handedness=info.get("handedness", ""),
            pro_year=info.get("pro_year"),
            ranking=data.get("rankings", [{}])[0].get("rank") if data.get("rankings") else None,
            doubles_ranking=None,
            prize_money=info.get("prize_money"),
            raw=data,
        )

    # === Competitor Recent Results ===
    def get_competitor_summaries(self, competitor_id: str) -> List[SRMatch]:
        """Get recent match summaries for a competitor."""
        clean_id = competitor_id.replace(":", "%3A")
        data = self._call(f"en/competitors/{clean_id}/summaries")
        summaries = data.get("summaries", [])
        return self._parse_summaries(summaries)

    # === Live Probabilities ===
    def get_live_probabilities(self) -> List[SRProbability]:
        """
        Get real-time win probabilities for live matches.
        Endpoint: /live/probabilities
        """
        data = self._call("en/live/probabilities")
        events = data.get("sport_events", data.get("sport_event_probabilities", []))

        probabilities = []
        for event in events:
            se = event.get("sport_event", {})
            competitors = se.get("competitors", [])
            markets = event.get("markets", [])

            if len(competitors) < 2:
                continue

            p_a = competitors[0].get("name", "")
            p_b = competitors[1].get("name", "")

            for market in markets:
                outcomes = market.get("outcomes", [])
                prob_a = 0.5
                prob_b = 0.5

                for outcome in outcomes:
                    if outcome.get("competitor_id") == competitors[0].get("id"):
                        prob_a = outcome.get("probability", 0.5)
                    elif outcome.get("competitor_id") == competitors[1].get("id"):
                        prob_b = outcome.get("probability", 0.5)

                probabilities.append(SRProbability(
                    event_id=se.get("id", ""),
                    player_a=p_a,
                    player_b=p_b,
                    prob_a=prob_a,
                    prob_b=prob_b,
                    market_name=market.get("name", ""),
                    raw=event,
                ))

        return probabilities

    # === Competitions ===
    def get_competitions(self) -> List[Dict]:
        """Get all tennis competitions."""
        data = self._call("en/competitions")
        return data.get("competitions", [])

    # === Seasons ===
    def get_seasons(self) -> List[Dict]:
        """Get all current seasons."""
        data = self._call("en/seasons")
        return data.get("seasons", [])

    # === Sport Event Summary ===
    def get_sport_event_summary(self, event_id: str) -> Dict:
        """Get detailed summary for a single match."""
        clean_id = event_id.replace(":", "%3A")
        return self._call(f"en/sport_events/{clean_id}/summary")

    # === Sport Event Timeline ===
    def get_sport_event_timeline(self, event_id: str) -> Dict:
        """Get point-by-point timeline for a match."""
        clean_id = event_id.replace(":", "%3A")
        return self._call(f"en/sport_events/{clean_id}/timeline")

    # === Updated Events ===
    def get_updated_events(self) -> List[Dict]:
        """Get recently updated sport events."""
        data = self._call("en/sport_events/updated")
        return data.get("sport_events", [])

    # === Internal: parse summaries ===
    def _parse_summaries(self, summaries: list) -> List[SRMatch]:
        """Parse raw API summaries into SRMatch objects."""
        matches = []
        for s in summaries:
            try:
                se = s.get("sport_event", {})
                ses = s.get("sport_event_status", {})
                competitors = se.get("competitors", [])
                sport_event_context = se.get("sport_event_context", {})

                if len(competitors) < 2:
                    continue

                comp_a = competitors[0]
                comp_b = competitors[1]

                # Parse period scores
                period_scores = ses.get("period_scores", [])

                status_str = ses.get("status", "not_started")
                if status_str == "live":
                    status = "live"
                elif status_str == "closed" or status_str == "ended":
                    status = "closed"
                else:
                    status = "not_started"

                matches.append(SRMatch(
                    event_id=se.get("id", ""),
                    start_time=se.get("start_time", ""),
                    status=status,
                    player_a=comp_a.get("name", ""),
                    player_a_id=comp_a.get("id", ""),
                    player_a_seed=comp_a.get("seed"),
                    player_b=comp_b.get("name", ""),
                    player_b_id=comp_b.get("id", ""),
                    player_b_seed=comp_b.get("seed"),
                    competition=sport_event_context.get("competition", {}).get("name", ""),
                    season=sport_event_context.get("season", {}).get("name", ""),
                    home_score=ses.get("home_score"),
                    away_score=ses.get("away_score"),
                    period_scores=[{
                        "home": ps.get("home_score"),
                        "away": ps.get("away_score"),
                        "type": ps.get("type"),
                        "number": ps.get("number"),
                    } for ps in period_scores],
                    winner_id=ses.get("winner_id"),
                    raw=s,
                ))
            except Exception as e:
                print(f"⚠️  SR parse error: {e}")
                continue

        return matches


# === CLI Demo ===
if __name__ == "__main__":
    client = SportradarTennisClient()

    print("=" * 60)
    print("  🏟️  SPORTRADAR TENNIS API — Integration Test")
    print("=" * 60)

    # 1. Live summaries
    print("\n  🔴 LIVE MATCHES")
    print("  " + "-" * 50)
    live = client.get_live_summaries()
    if live:
        for m in live[:10]:
            seed_a = f"[{m.player_a_seed}]" if m.player_a_seed else ""
            seed_b = f"[{m.player_b_seed}]" if m.player_b_seed else ""
            score = f"{m.home_score}-{m.away_score}" if m.home_score is not None else "—"
            print(f"  🎾 {seed_a}{m.player_a} vs {seed_b}{m.player_b}")
            print(f"     {m.competition} | {m.status} | {score}")
            if m.period_scores:
                sets = " ".join(f'{ps["home"]}-{ps["away"]}' for ps in m.period_scores)
                print(f"     Sets: {sets}")
        print(f"\n  Total live: {len(live)} matches")
    else:
        print("  No live matches or API rate limited")

    # 2. Rankings
    print("\n  🏆 ATP/WTA RANKINGS (Top 5)")
    print("  " + "-" * 50)
    rankings = client.get_rankings()
    for tour, entries in rankings.items():
        print(f"\n  [{tour.upper()}]")
        for r in entries[:5]:
            move = f"↑{r.movement}" if r.movement > 0 else (f"↓{abs(r.movement)}" if r.movement < 0 else "—")
            print(f"  #{r.rank} {r.player_name} ({r.nationality}) — {r.points}pts {move}")

    print(f"\n  📊 Total API calls: {client._request_count}")
