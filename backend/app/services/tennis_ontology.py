"""
Tennis Ontology — Pre-built Domain Ontology
=============================================
Hardcoded tennis-domain ontology for NemoFish graph building.
No LLM generation needed — the tennis domain is well-known.

Compatible with GraphBuilderService.set_ontology() format.
"""

from typing import Dict, Any


def get_tennis_ontology() -> Dict[str, Any]:
    """
    Returns a pre-built tennis ontology dict compatible
    with the existing GraphBuilderService.

    Entity types (10):
        Player, CoachTeam, Tournament, Surface, Match,
        Market, Injury, News, TravelFatigue, StyleTrait

    Edge types (8):
        PLAYS_ON, MATCHES_UP_WELL_AGAINST, STRUGGLES_AGAINST,
        COMING_OFF, REPORTED_BY, PRICED_BY_MARKET,
        AFFECTED_BY, CONNECTED_TO
    """
    return {
        "entity_types": [
            {
                "name": "Player",
                "description": "A professional tennis player competing in the match",
                "attributes": [
                    {"name": "full_name", "type": "text", "description": "Player full name"},
                    {"name": "ranking", "type": "text", "description": "Current ATP/WTA ranking"},
                    {"name": "elo_rating", "type": "text", "description": "Current Elo rating"},
                ],
                "examples": ["Jannik Sinner", "Carlos Alcaraz"],
            },
            {
                "name": "CoachTeam",
                "description": "Coaching staff and support team of a player",
                "attributes": [
                    {"name": "coach_name", "type": "text", "description": "Head coach name"},
                    {"name": "role", "type": "text", "description": "Role in the team"},
                ],
                "examples": ["Darren Cahill", "Juan Carlos Ferrero"],
            },
            {
                "name": "Tournament",
                "description": "A professional tennis tournament or event",
                "attributes": [
                    {"name": "tournament_name", "type": "text", "description": "Tournament name"},
                    {"name": "level", "type": "text", "description": "G/M/A/B/F level"},
                    {"name": "draw_size", "type": "text", "description": "Number of players in draw"},
                ],
                "examples": ["Miami Open", "Roland Garros"],
            },
            {
                "name": "Surface",
                "description": "Playing surface type affecting match dynamics",
                "attributes": [
                    {"name": "surface_type", "type": "text", "description": "Hard/Clay/Grass"},
                    {"name": "speed_rating", "type": "text", "description": "Surface speed classification"},
                ],
                "examples": ["Hard (outdoor)", "Clay", "Grass"],
            },
            {
                "name": "Match",
                "description": "A specific tennis match between two players",
                "attributes": [
                    {"name": "match_date", "type": "text", "description": "Date of the match"},
                    {"name": "round_name", "type": "text", "description": "Tournament round (F/SF/QF/R16)"},
                ],
                "examples": ["Sinner vs Alcaraz SF Miami Open"],
            },
            {
                "name": "Market",
                "description": "Betting market and odds for a match",
                "attributes": [
                    {"name": "odds_description", "type": "text", "description": "Market odds summary"},
                    {"name": "market_movement", "type": "text", "description": "Direction of odds movement"},
                ],
                "examples": ["Polymarket: Sinner 1.55 / Alcaraz 2.55"],
            },
            {
                "name": "Injury",
                "description": "Physical injury or health concern affecting a player",
                "attributes": [
                    {"name": "injury_type", "type": "text", "description": "Type of injury"},
                    {"name": "severity", "type": "text", "description": "Severity: minor/moderate/severe"},
                ],
                "examples": ["Right knee discomfort", "Back spasms"],
            },
            {
                "name": "News",
                "description": "News report or media signal about a player or match",
                "attributes": [
                    {"name": "headline", "type": "text", "description": "News headline"},
                    {"name": "sentiment", "type": "text", "description": "Positive/neutral/negative"},
                ],
                "examples": ["Player X spotted limping at practice"],
            },
            # Fallback types (required by ontology contract)
            {
                "name": "Person",
                "description": "Any individual person not fitting other specific types",
                "attributes": [
                    {"name": "full_name", "type": "text", "description": "Full name"},
                    {"name": "role", "type": "text", "description": "Role or occupation"},
                ],
                "examples": ["tournament director", "physiotherapist"],
            },
            {
                "name": "Organization",
                "description": "Any organization not fitting other specific types",
                "attributes": [
                    {"name": "org_name", "type": "text", "description": "Organization name"},
                    {"name": "org_type", "type": "text", "description": "Type of organization"},
                ],
                "examples": ["ATP Tour", "ITF"],
            },
        ],
        "edge_types": [
            {
                "name": "PLAYS_ON",
                "description": "Player competes on a surface or at a tournament",
                "source_targets": [
                    {"source": "Player", "target": "Surface"},
                    {"source": "Player", "target": "Tournament"},
                ],
                "attributes": [],
            },
            {
                "name": "MATCHES_UP_WELL_AGAINST",
                "description": "Player has favorable H2H or style matchup vs another",
                "source_targets": [
                    {"source": "Player", "target": "Player"},
                ],
                "attributes": [
                    {"name": "h2h_record", "type": "text", "description": "Head-to-head record"},
                ],
            },
            {
                "name": "STRUGGLES_AGAINST",
                "description": "Player has unfavorable matchup against another",
                "source_targets": [
                    {"source": "Player", "target": "Player"},
                ],
                "attributes": [
                    {"name": "weakness", "type": "text", "description": "Description of the struggle"},
                ],
            },
            {
                "name": "COMING_OFF",
                "description": "Player is recovering from injury or recent event",
                "source_targets": [
                    {"source": "Player", "target": "Injury"},
                    {"source": "Player", "target": "Match"},
                ],
                "attributes": [],
            },
            {
                "name": "REPORTED_BY",
                "description": "News or injury reported by a source",
                "source_targets": [
                    {"source": "Injury", "target": "News"},
                    {"source": "Player", "target": "News"},
                ],
                "attributes": [],
            },
            {
                "name": "PRICED_BY_MARKET",
                "description": "Match or player is priced by betting markets",
                "source_targets": [
                    {"source": "Match", "target": "Market"},
                    {"source": "Player", "target": "Market"},
                ],
                "attributes": [],
            },
            {
                "name": "AFFECTED_BY",
                "description": "Player performance affected by fatigue, injury, or conditions",
                "source_targets": [
                    {"source": "Player", "target": "Injury"},
                    {"source": "Player", "target": "Surface"},
                ],
                "attributes": [],
            },
            {
                "name": "CONNECTED_TO",
                "description": "General connection between entities",
                "source_targets": [
                    {"source": "Player", "target": "CoachTeam"},
                    {"source": "Player", "target": "Organization"},
                    {"source": "Tournament", "target": "Surface"},
                ],
                "attributes": [],
            },
        ],
        "analysis_summary": "Pre-built tennis domain ontology for NemoFish match scenario analysis",
    }


def build_match_graph_text(dossier_dict: Dict[str, Any]) -> str:
    """
    Convert a MatchDossier dict into a narrative text suitable
    for graph building via Zep API.

    This is the bridge between our structured dossier and the
    Zep graph builder which ingests text.
    """
    pa = dossier_dict.get("player_a", {})
    pb = dossier_dict.get("player_b", {})
    h2h = dossier_dict.get("h2h", {})
    tournament = dossier_dict.get("tournament", {})

    pa_id = pa.get("identity", {})
    pb_id = pb.get("identity", {})

    sections = []

    # Tournament context
    sections.append(
        f"Tournament: {tournament.get('tournament_name', 'Unknown')} "
        f"({tournament.get('tournament_level', '')}, "
        f"{tournament.get('surface', '')}, "
        f"Round: {tournament.get('round_name', '')}). "
        f"Date: {tournament.get('date', '')}."
    )

    # Player A profile
    sections.append(
        f"Player A: {pa_id.get('name', 'Unknown')}, "
        f"ranked #{pa_id.get('ranking', 'N/A')}, "
        f"Elo {pa_id.get('elo_overall', 1500):.0f} "
        f"(surface Elo {pa_id.get('elo_surface', 1500):.0f}). "
        f"Serve: {pa.get('play_style', {}).get('serve_type', 'unknown')}. "
        f"Return: {pa.get('play_style', {}).get('return_game', 'unknown')}. "
        f"Form: {pa.get('form_profile', {}).get('last_10_wins', 0)}-"
        f"{pa.get('form_profile', {}).get('last_10_losses', 0)} last 10 "
        f"({pa.get('form_profile', {}).get('form_trajectory', 'stable')}). "
        f"Fatigue: {pa.get('physical_profile', {}).get('fatigue_score', 0):.0%}."
    )

    injury_a = pa.get("physical_profile", {}).get("injury_flag")
    if injury_a:
        sections.append(f"Injury concern for {pa_id.get('name')}: {injury_a}.")

    # Player B profile
    sections.append(
        f"Player B: {pb_id.get('name', 'Unknown')}, "
        f"ranked #{pb_id.get('ranking', 'N/A')}, "
        f"Elo {pb_id.get('elo_overall', 1500):.0f} "
        f"(surface Elo {pb_id.get('elo_surface', 1500):.0f}). "
        f"Serve: {pb.get('play_style', {}).get('serve_type', 'unknown')}. "
        f"Return: {pb.get('play_style', {}).get('return_game', 'unknown')}. "
        f"Form: {pb.get('form_profile', {}).get('last_10_wins', 0)}-"
        f"{pb.get('form_profile', {}).get('last_10_losses', 0)} last 10 "
        f"({pb.get('form_profile', {}).get('form_trajectory', 'stable')}). "
        f"Fatigue: {pb.get('physical_profile', {}).get('fatigue_score', 0):.0%}."
    )

    injury_b = pb.get("physical_profile", {}).get("injury_flag")
    if injury_b:
        sections.append(f"Injury concern for {pb_id.get('name')}: {injury_b}.")

    # H2H
    if h2h.get("total_matches", 0) > 0:
        sections.append(
            f"Head-to-head: {pa_id.get('name')} leads {h2h.get('a_wins', 0)}-{h2h.get('b_wins', 0)}. "
            f"On {tournament.get('surface', '')}: "
            f"{h2h.get('a_wins_on_surface', 0)}-{h2h.get('b_wins_on_surface', 0)}."
        )

    # Market
    odds_a = pa.get("market_profile", {}).get("odds_decimal")
    odds_b = pb.get("market_profile", {}).get("odds_decimal")
    if odds_a and odds_b:
        sections.append(
            f"Market odds: {pa_id.get('name')} {odds_a:.2f} / "
            f"{pb_id.get('name')} {odds_b:.2f}."
        )

    return " ".join(sections)
