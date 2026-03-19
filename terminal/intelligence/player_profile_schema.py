"""
Player Intelligence Schema — Structured Player Profiles
=========================================================
Typed, JSON-serializable dataclasses for player intelligence.
NO free text blobs. Every field is structured and machine-readable.

Schema contract:
  PlayerIntelligence
  ├── identity        — name, tour, ranking, Elo
  ├── play_style      — serve, return, rally, net
  ├── mental_profile   — pressure, comebacks, big-match
  ├── physical_profile — fatigue, travel, rest, injury
  ├── surface_profile  — surface win rates, Elo delta
  ├── form_profile     — recent results, streaks
  ├── market_profile   — odds, movement, sharp money
  ├── news_profile     — injury news, sentiment, coaching
  └── unknowns         — unresolved flags
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json


@dataclass
class PlayerIdentity:
    """Core identity of a player."""
    name: str = ""
    tour: str = ""            # ATP / WTA
    ranking: int = 999
    ranking_points: int = 0
    elo_overall: float = 1500.0
    elo_surface: float = 1500.0
    age: Optional[float] = None
    country: str = ""
    handedness: str = ""      # R / L / unknown


@dataclass
class PlayStyle:
    """Playing style characteristics."""
    serve_type: str = "unknown"         # big_server / solid / weak
    first_serve_pct: Optional[float] = None
    first_serve_won_pct: Optional[float] = None
    second_serve_won_pct: Optional[float] = None
    return_game: str = "unknown"        # elite / strong / average / weak
    return_won_pct: Optional[float] = None
    rally_preference: str = "unknown"   # baseline / all_court / serve_volley
    net_approach: str = "unknown"       # aggressive / occasional / rare
    ace_rate: Optional[float] = None
    df_rate: Optional[float] = None
    break_point_conversion: Optional[float] = None
    break_point_save: Optional[float] = None


@dataclass
class MentalProfile:
    """Psychological and mental attributes."""
    pressure_handling: float = 0.5       # 0=cracks, 1=ice-cold
    comeback_ability: float = 0.5        # 0=fragile, 1=resilient
    big_match_factor: float = 0.5        # performance uplift in big matches
    tiebreak_record: Optional[float] = None  # win rate in tiebreaks
    deciding_set_record: Optional[float] = None  # win rate in deciding sets
    motivation_level: str = "normal"     # high / normal / low / unknown


@dataclass
class PhysicalProfile:
    """Physical condition and fatigue."""
    fatigue_score: float = 0.0           # 0=fresh, 1=exhausted
    days_since_last_match: int = 7
    matches_last_14d: int = 0
    matches_last_30d: int = 0
    travel_load: str = "normal"          # light / normal / heavy
    injury_flag: Optional[str] = None    # None = no known injury
    injury_severity: float = 0.0         # 0=none, 1=severe
    fitness_concern: bool = False


@dataclass
class SurfaceProfile:
    """Surface-specific performance."""
    surface: str = ""                    # Hard / Clay / Grass
    career_surface_win_rate: Optional[float] = None
    career_surface_matches: int = 0
    surface_elo_delta: float = 0.0       # surface Elo - overall Elo
    is_surface_specialist: bool = False
    surface_comfort: str = "neutral"     # comfortable / neutral / uncomfortable


@dataclass
class FormProfile:
    """Recent form and momentum."""
    last_5_wins: int = 0
    last_5_losses: int = 0
    last_10_wins: int = 0
    last_10_losses: int = 0
    current_streak: int = 0              # positive = win streak, negative = loss
    best_recent_result: str = ""         # e.g. "SF Miami Open"
    worst_recent_result: str = ""        # e.g. "R1 Challenger"
    form_trajectory: str = "stable"      # rising / stable / declining


@dataclass
class MarketProfile:
    """Market and odds information."""
    odds_decimal: Optional[float] = None
    implied_probability: Optional[float] = None
    odds_movement: str = "stable"        # shortening / stable / drifting
    is_favorite: Optional[bool] = None
    sharp_money_signal: str = "none"     # none / backing / fading
    market_confidence: str = "unknown"   # high / medium / low / unknown


@dataclass
class NewsProfile:
    """News, media, and external signals."""
    injury_news: Optional[str] = None
    coaching_change: bool = False
    media_sentiment: str = "neutral"     # positive / neutral / negative
    off_court_issues: bool = False
    recent_headlines: List[str] = field(default_factory=list)


@dataclass
class Unknowns:
    """Unresolved data flags."""
    missing_data_fields: List[str] = field(default_factory=list)
    low_confidence_flags: List[str] = field(default_factory=list)
    data_quality_score: float = 0.5      # 0=no data, 1=complete


@dataclass
class PlayerIntelligence:
    """
    Complete structured intelligence on a player for one match.
    This is the contract between data feeds and the scenario engine.
    """
    identity: PlayerIdentity = field(default_factory=PlayerIdentity)
    play_style: PlayStyle = field(default_factory=PlayStyle)
    mental_profile: MentalProfile = field(default_factory=MentalProfile)
    physical_profile: PhysicalProfile = field(default_factory=PhysicalProfile)
    surface_profile: SurfaceProfile = field(default_factory=SurfaceProfile)
    form_profile: FormProfile = field(default_factory=FormProfile)
    market_profile: MarketProfile = field(default_factory=MarketProfile)
    news_profile: NewsProfile = field(default_factory=NewsProfile)
    unknowns: Unknowns = field(default_factory=Unknowns)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlayerIntelligence':
        return cls(
            identity=PlayerIdentity(**data.get("identity", {})),
            play_style=PlayStyle(**data.get("play_style", {})),
            mental_profile=MentalProfile(**data.get("mental_profile", {})),
            physical_profile=PhysicalProfile(**data.get("physical_profile", {})),
            surface_profile=SurfaceProfile(**data.get("surface_profile", {})),
            form_profile=FormProfile(**data.get("form_profile", {})),
            market_profile=MarketProfile(**data.get("market_profile", {})),
            news_profile=NewsProfile(**data.get("news_profile", {})),
            unknowns=Unknowns(**data.get("unknowns", {})),
        )


@dataclass
class H2HSummary:
    """Head-to-head summary between two players."""
    total_matches: int = 0
    a_wins: int = 0
    b_wins: int = 0
    a_wins_on_surface: int = 0
    b_wins_on_surface: int = 0
    surface_matches: int = 0
    last_meeting: str = ""
    last_winner: str = ""
    dominance_factor: float = 0.5  # 0=B dominates, 0.5=even, 1=A dominates


@dataclass
class TournamentContext:
    """Tournament and match context."""
    tournament_name: str = ""
    tournament_level: str = ""     # G / M / A / B / F
    surface: str = ""
    round_name: str = ""
    best_of: int = 3
    indoor: bool = False
    altitude_m: int = 0
    date: str = ""
    draw_size: int = 0


@dataclass
class MatchDossier:
    """
    Complete intelligence dossier for a single match.
    This is the primary input to the Scenario Engine.
    """
    player_a: PlayerIntelligence = field(default_factory=PlayerIntelligence)
    player_b: PlayerIntelligence = field(default_factory=PlayerIntelligence)
    h2h: H2HSummary = field(default_factory=H2HSummary)
    tournament: TournamentContext = field(default_factory=TournamentContext)
    generated_at: str = ""
    data_quality: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MatchDossier':
        return cls(
            player_a=PlayerIntelligence.from_dict(data.get("player_a", {})),
            player_b=PlayerIntelligence.from_dict(data.get("player_b", {})),
            h2h=H2HSummary(**data.get("h2h", {})),
            tournament=TournamentContext(**data.get("tournament", {})),
            generated_at=data.get("generated_at", ""),
            data_quality=data.get("data_quality", 0.0),
        )
