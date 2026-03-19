"""
Match Dossier Builder — Assembles Intelligence Dossier from Feeds
==================================================================
Pulls data from existing feed infrastructure to build a complete
MatchDossier for scenario simulation.

Data sources used (all existing):
  - TennisEloEngine: Elo ratings, surface Elo
  - JeffSackmannLoader: H2H, serve/return stats, surface records, recent form
  - MatchContext fields: rankings, tournament context
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from intelligence.player_profile_schema import (
    PlayerIntelligence, PlayerIdentity, PlayStyle, MentalProfile,
    PhysicalProfile, SurfaceProfile, FormProfile, MarketProfile,
    NewsProfile, Unknowns, H2HSummary, TournamentContext, MatchDossier,
)


class MatchDossierBuilder:
    """
    Assembles a MatchDossier from existing NemoFish feeds.

    Usage:
        builder = MatchDossierBuilder(elo_engine=elo, sackmann=sackmann)
        dossier = builder.build(match_context)
    """

    def __init__(self, elo_engine=None, sackmann_loader=None):
        self.elo = elo_engine
        self.sackmann = sackmann_loader

    def build(self, ctx) -> MatchDossier:
        """
        Build a complete MatchDossier from a MatchContext.

        Args:
            ctx: agents.tennis_swarm.MatchContext

        Returns:
            MatchDossier with both player profiles filled in
        """
        player_a = self._build_player_intel(
            name=ctx.player_a,
            rank=ctx.rank_a,
            rank_pts=ctx.rank_pts_a,
            odds=ctx.odds_a,
            surface=ctx.surface,
            injury=getattr(ctx, 'injury_a', None),
            days_rest=ctx.days_since_last_match_a,
            matches_14d=ctx.matches_last_14d_a,
            recent_wins=ctx.recent_wins_a,
            seed=ctx.seed_a,
            is_favorite=(ctx.rank_a < ctx.rank_b),
        )

        player_b = self._build_player_intel(
            name=ctx.player_b,
            rank=ctx.rank_b,
            rank_pts=ctx.rank_pts_b,
            odds=ctx.odds_b,
            surface=ctx.surface,
            injury=getattr(ctx, 'injury_b', None),
            days_rest=ctx.days_since_last_match_b,
            matches_14d=ctx.matches_last_14d_b,
            recent_wins=ctx.recent_wins_b,
            seed=ctx.seed_b,
            is_favorite=(ctx.rank_b < ctx.rank_a),
        )

        h2h = self._build_h2h(ctx.player_a, ctx.player_b, ctx.surface)

        tournament = TournamentContext(
            tournament_name=ctx.tourney_name,
            tournament_level=ctx.tourney_level,
            surface=ctx.surface,
            round_name=ctx.round_name,
            best_of=ctx.best_of,
            indoor=ctx.indoor,
            altitude_m=ctx.altitude_m,
            date=ctx.date,
        )

        # Data quality assessment
        dq = self._assess_data_quality(player_a, player_b, h2h, ctx)

        return MatchDossier(
            player_a=player_a,
            player_b=player_b,
            h2h=h2h,
            tournament=tournament,
            generated_at=datetime.now().isoformat(),
            data_quality=dq,
        )

    def _build_player_intel(
        self,
        name: str,
        rank: int,
        rank_pts: int,
        odds: Optional[float],
        surface: str,
        injury: Optional[str],
        days_rest: int,
        matches_14d: int,
        recent_wins: int,
        seed: Optional[int],
        is_favorite: bool,
    ) -> PlayerIntelligence:
        """Build PlayerIntelligence from available data."""
        unknowns_list = []

        # === Identity ===
        elo_overall = 1500.0
        elo_surface = 1500.0
        if self.elo:
            player_elo = self.elo.get_player(name)
            if player_elo:
                elo_overall = player_elo.overall
                elo_surface = player_elo.get_surface_elo(surface)
            else:
                unknowns_list.append("elo_data_missing")

        identity = PlayerIdentity(
            name=name,
            ranking=rank,
            ranking_points=rank_pts,
            elo_overall=round(elo_overall, 1),
            elo_surface=round(elo_surface, 1),
        )

        # === Play Style (from Sackmann if available) ===
        play_style = PlayStyle()
        if self.sackmann:
            try:
                profile = self.sackmann.get_player(name)
                if profile:
                    spw = profile.get('avg_1st_serve_won', 0)
                    rpw = profile.get('avg_return_won', 0)
                    play_style.first_serve_won_pct = spw if spw > 0 else None
                    play_style.return_won_pct = rpw if rpw > 0 else None

                    # Classify serve type
                    if spw > 75:
                        play_style.serve_type = "big_server"
                    elif spw > 65:
                        play_style.serve_type = "solid"
                    elif spw > 0:
                        play_style.serve_type = "weak"

                    # Classify return game
                    if rpw > 42:
                        play_style.return_game = "elite"
                    elif rpw > 38:
                        play_style.return_game = "strong"
                    elif rpw > 32:
                        play_style.return_game = "average"
                    elif rpw > 0:
                        play_style.return_game = "weak"

                    # Break point stats
                    bp_conv = profile.get('avg_bp_converted', 0)
                    bp_save = profile.get('avg_bp_saved', 0)
                    if bp_conv > 0:
                        play_style.break_point_conversion = bp_conv
                    if bp_save > 0:
                        play_style.break_point_save = bp_save

                    # Ace/DF rates
                    ace = profile.get('avg_ace_rate', 0)
                    df = profile.get('avg_df_rate', 0)
                    if ace > 0:
                        play_style.ace_rate = ace
                    if df > 0:
                        play_style.df_rate = df
                else:
                    unknowns_list.append("sackmann_profile_missing")
            except Exception:
                unknowns_list.append("sackmann_error")
        else:
            unknowns_list.append("sackmann_unavailable")

        # === Physical Profile ===
        fatigue = self._compute_fatigue(days_rest, matches_14d)
        physical = PhysicalProfile(
            fatigue_score=round(fatigue, 3),
            days_since_last_match=days_rest,
            matches_last_14d=matches_14d,
            injury_flag=injury,
            injury_severity=self._injury_severity(injury),
            fitness_concern=(fatigue > 0.7 or self._injury_severity(injury) > 0.3),
        )

        # === Surface Profile ===
        surface_profile = SurfaceProfile(
            surface=surface,
            surface_elo_delta=round(elo_surface - elo_overall, 1),
        )
        if self.sackmann:
            try:
                sr = self.sackmann.get_surface_record(name, surface)
                if sr:
                    total = sr['wins'] + sr['losses']
                    if total > 0:
                        surface_profile.career_surface_win_rate = round(sr['wins'] / total, 3)
                        surface_profile.career_surface_matches = total
                        surface_profile.is_surface_specialist = (
                            surface_profile.career_surface_win_rate > 0.65 and total >= 30
                        )
                        if surface_profile.career_surface_win_rate > 0.60:
                            surface_profile.surface_comfort = "comfortable"
                        elif surface_profile.career_surface_win_rate < 0.45:
                            surface_profile.surface_comfort = "uncomfortable"
            except Exception:
                pass

        # === Form Profile ===
        recent_losses = 10 - recent_wins
        form = FormProfile(
            last_10_wins=recent_wins,
            last_10_losses=recent_losses,
        )
        if recent_wins >= 8:
            form.form_trajectory = "rising"
        elif recent_wins <= 3:
            form.form_trajectory = "declining"
        else:
            form.form_trajectory = "stable"

        # Sackmann recent form enrichment
        if self.sackmann:
            try:
                recent = self.sackmann.get_recent_form(name, n=5)
                if recent:
                    wins_5 = sum(
                        1 for m in recent
                        if m.winner_name and name.lower() in m.winner_name.lower()
                    )
                    form.last_5_wins = wins_5
                    form.last_5_losses = len(recent) - wins_5
            except Exception:
                pass

        # === Market Profile ===
        market = MarketProfile()
        if odds:
            market.odds_decimal = odds
            market.implied_probability = round(1.0 / odds, 4)
            market.is_favorite = is_favorite

        # === Mental Profile (derived from available data) ===
        mental = MentalProfile()
        # Higher-ranked with good form = better pressure handling
        if rank < 20 and recent_wins >= 7:
            mental.pressure_handling = 0.75
            mental.big_match_factor = 0.7
        elif rank < 50:
            mental.pressure_handling = 0.6
        # Surface specialist boost
        if surface_profile.is_surface_specialist:
            mental.pressure_handling = min(1.0, mental.pressure_handling + 0.1)

        # === News Profile ===
        news = NewsProfile()
        if injury:
            news.injury_news = injury

        # === Unknowns ===
        # Assess what data we're missing
        dq_score = 1.0
        if unknowns_list:
            dq_score -= 0.1 * len(unknowns_list)
        if not odds:
            unknowns_list.append("no_market_odds")
            dq_score -= 0.15
        if rank >= 200:
            unknowns_list.append("low_ranked_limited_data")
            dq_score -= 0.1

        unknowns = Unknowns(
            missing_data_fields=unknowns_list,
            data_quality_score=max(0.0, round(dq_score, 2)),
        )

        return PlayerIntelligence(
            identity=identity,
            play_style=play_style,
            mental_profile=mental,
            physical_profile=physical,
            surface_profile=surface_profile,
            form_profile=form,
            market_profile=market,
            news_profile=news,
            unknowns=unknowns,
        )

    def _build_h2h(self, player_a: str, player_b: str, surface: str) -> H2HSummary:
        """Build head-to-head summary from Sackmann data."""
        h2h = H2HSummary()

        if not self.sackmann:
            return h2h

        try:
            h2h_data = self.sackmann.get_h2h(player_a, player_b)
            h2h.a_wins = h2h_data.a_wins
            h2h.b_wins = h2h_data.b_wins
            h2h.total_matches = h2h_data.a_wins + h2h_data.b_wins

            # Surface-specific H2H
            surface_key = surface.lower()
            if surface_key in h2h_data.surface_records:
                sw, sl = h2h_data.surface_records[surface_key]
                h2h.a_wins_on_surface = sw
                h2h.b_wins_on_surface = sl
                h2h.surface_matches = sw + sl

            # Dominance factor
            if h2h.total_matches > 0:
                h2h.dominance_factor = round(
                    h2h.a_wins / h2h.total_matches, 3
                )
        except Exception:
            pass

        return h2h

    def _assess_data_quality(
        self, pa: PlayerIntelligence, pb: PlayerIntelligence,
        h2h: H2HSummary, ctx
    ) -> float:
        """Overall data quality score for the dossier."""
        score = 0.0

        # Elo data
        if pa.identity.elo_overall != 1500.0:
            score += 0.15
        if pb.identity.elo_overall != 1500.0:
            score += 0.15

        # Market odds
        if ctx.odds_a and ctx.odds_b:
            score += 0.2

        # Sackmann profiles
        if pa.play_style.serve_type != "unknown":
            score += 0.1
        if pb.play_style.serve_type != "unknown":
            score += 0.1

        # H2H
        if h2h.total_matches >= 3:
            score += 0.15
        elif h2h.total_matches >= 1:
            score += 0.05

        # Rankings
        if ctx.rank_a < 200 and ctx.rank_b < 200:
            score += 0.1

        # Form data
        score += 0.05  # Always have at least basic form

        return min(1.0, round(score, 2))

    @staticmethod
    def _compute_fatigue(days_rest: int, matches_14d: int) -> float:
        """Fatigue score: 0=fresh, 1=exhausted."""
        rest_fatigue = max(0, 1.0 - days_rest / 5.0)
        load_fatigue = min(1.0, matches_14d / 8.0)
        return rest_fatigue * 0.4 + load_fatigue * 0.6

    @staticmethod
    def _injury_severity(injury_desc: Optional[str]) -> float:
        """Estimate injury severity. 0-1 scale."""
        if not injury_desc:
            return 0.0
        desc = injury_desc.lower()
        if any(w in desc for w in ['withdrew', 'surgery', 'torn', 'fracture']):
            return 1.0
        if any(w in desc for w in ['illness', 'sick', 'abdominal', 'back pain']):
            return 0.6
        if any(w in desc for w in ['minor', 'blister', 'cramping', 'tight']):
            return 0.3
        return 0.4
