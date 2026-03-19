"""
Tennis Agent Swarm — Multi-Agent Ensemble Prediction
=====================================================
5 specialized agent roles that independently analyze matches,
then vote through weighted consensus to produce final prediction.

Architecture:
  - StatisticalAgent: Elo + serve/return stats + H2H
  - NewsScoutAgent: Injury/form/weather signals 
  - PsychologyAgent: Fatigue, pressure, motivation analysis
  - MarketMakerAgent: Odds movement, CLV, sharp money
  - ContrarianAgent: Upset detection, public fading

Each agent scores independently (0-1 probability).
SelfConsistencyAgent aggregates via weighted majority vote.
Minimum 8% consensus edge required for execution.

This module works WITHOUT external LLM API keys by using
rule-based expert systems. DeepSeek-R1 integration is Phase 3.5.
"""

import sys
import json
import math
import random
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.tennis_elo import TennisEloEngine
from models.kelly import KellyCriterion

# JeffSackmann deep data integration (1.4 GB: 143K matches, 132K players)
try:
    from feeds.sackmann_loader import JeffSackmannLoader
    SACKMANN_AVAILABLE = True
except ImportError:
    SACKMANN_AVAILABLE = False
    JeffSackmannLoader = None


# === Data Structures ===

@dataclass
class MatchContext:
    """All available information about an upcoming match."""
    player_a: str
    player_b: str
    surface: str
    tourney_name: str
    tourney_level: str  # G, M, A, B
    round_name: str     # F, SF, QF, R16, R32, etc.
    date: str
    # Ranks
    rank_a: int = 50
    rank_b: int = 50
    rank_pts_a: int = 0
    rank_pts_b: int = 0
    # Seeds
    seed_a: Optional[int] = None
    seed_b: Optional[int] = None
    # Odds (if available)
    odds_a: Optional[float] = None
    odds_b: Optional[float] = None
    # Extra context
    altitude_m: int = 0  # Madrid 640m, Denver 1609m
    indoor: bool = False
    best_of: int = 3
    # News/injuries
    injury_a: Optional[str] = None
    injury_b: Optional[str] = None
    days_since_last_match_a: int = 4
    days_since_last_match_b: int = 4
    matches_last_14d_a: int = 3
    matches_last_14d_b: int = 3
    # Recent form (last 10 matches)
    recent_wins_a: int = 7
    recent_wins_b: int = 7


@dataclass
class AgentVote:
    """A single agent's prediction for a match."""
    agent_name: str
    agent_role: str
    prob_a: float       # Probability player_a wins (0-1)
    confidence: float   # Agent's confidence in its own prediction (0-1)
    reasoning: str      # Brief explanation
    factors: Dict       # Key factors considered


@dataclass
class SwarmConsensus:
    """Final swarm consensus prediction."""
    player_a: str
    player_b: str
    surface: str
    prob_a: float
    prob_b: float
    confidence: str     # LOW / MEDIUM / HIGH / ELITE
    edge_vs_market: Optional[float]
    recommended_action: str  # BET_A / BET_B / SKIP
    kelly_bet_size: float
    agent_votes: List[AgentVote]
    reasoning_summary: str
    data_quality_score: float  # 0-1, how much data we have


# === Agent Implementations ===

class StatisticalAgent:
    """
    Pure statistics agent: Elo + JeffSackmann deep data.
    Uses H2H records, surface win rates, serve/return stats from 143K matches.
    This is the backbone — highest weight in consensus.
    Weight: 0.35
    """
    ROLE = "Statistical Analyst"
    WEIGHT = 0.35

    def __init__(self, elo_engine: TennisEloEngine, sackmann: 'JeffSackmannLoader' = None):
        self.elo = elo_engine
        self.sackmann = sackmann

    def analyze(self, ctx: MatchContext) -> AgentVote:
        # --- Elo probability ---
        elo_prob = self.elo.predict_match(ctx.player_a, ctx.player_b, ctx.surface)

        # --- Rank-based adjustment ---
        rank_factor = 0.0
        if ctx.rank_a > 0 and ctx.rank_b > 0:
            rank_ratio = ctx.rank_b / (ctx.rank_a + ctx.rank_b)
            rank_factor = (rank_ratio - 0.5) * 0.1  # ±5% max from rank

        # --- Surface specialization bonus ---
        pa = self.elo.get_player(ctx.player_a)
        pb = self.elo.get_player(ctx.player_b)

        surface_gap = 0.0
        if pa and pb:
            sa = pa.get_surface_elo(ctx.surface)
            sb = pb.get_surface_elo(ctx.surface)
            oa = pa.overall
            ob = pb.overall
            a_surface_bonus = (sa - oa) / 200.0
            b_surface_bonus = (sb - ob) / 200.0
            surface_gap = (a_surface_bonus - b_surface_bonus) * 0.05

        prob_a = np.clip(elo_prob + rank_factor + surface_gap, 0.05, 0.95)

        # === SACKMANN DEEP DATA INTEGRATION ===
        h2h_factor = 0.0
        surface_wr_factor = 0.0
        serve_return_factor = 0.0
        sackmann_reasoning = ""

        if self.sackmann:
            try:
                # --- H2H from 143K matches ---
                h2h = self.sackmann.get_h2h(ctx.player_a, ctx.player_b)
                total_h2h = h2h.a_wins + h2h.b_wins
                if total_h2h >= 3:
                    h2h_wr = h2h.a_wins / total_h2h
                    h2h_factor = (h2h_wr - 0.5) * 0.12  # ±6% max from H2H
                    sackmann_reasoning += f"H2H: {h2h.a_wins}-{h2h.b_wins}. "

                    # Surface-specific H2H
                    surface_key = ctx.surface.lower()
                    if surface_key in h2h.surface_records:
                        sw, sl = h2h.surface_records[surface_key]
                        if sw + sl >= 2:
                            surface_h2h_wr = sw / (sw + sl)
                            h2h_factor += (surface_h2h_wr - 0.5) * 0.06
                            sackmann_reasoning += f"H2H on {ctx.surface}: {sw}-{sl}. "

                # --- Surface Win Rate from full career ---
                sr_a = self.sackmann.get_surface_record(ctx.player_a, ctx.surface)
                sr_b = self.sackmann.get_surface_record(ctx.player_b, ctx.surface)
                if sr_a and sr_b:
                    wr_a = sr_a['wins'] / max(1, sr_a['wins'] + sr_a['losses'])
                    wr_b = sr_b['wins'] / max(1, sr_b['wins'] + sr_b['losses'])
                    if sr_a['wins'] + sr_a['losses'] >= 20 and sr_b['wins'] + sr_b['losses'] >= 20:
                        surface_wr_factor = (wr_a - wr_b) * 0.08
                        sackmann_reasoning += f"{ctx.surface} WR: {wr_a:.0%} vs {wr_b:.0%}. "

                # --- Serve/Return Stats ---
                profile_a = self.sackmann.get_player(ctx.player_a)
                profile_b = self.sackmann.get_player(ctx.player_b)
                if profile_a and profile_b:
                    spw_a = profile_a.get('avg_1st_serve_won', 0)
                    spw_b = profile_b.get('avg_1st_serve_won', 0)
                    rpw_a = profile_a.get('avg_return_won', 0)
                    rpw_b = profile_b.get('avg_return_won', 0)
                    if spw_a > 0 and spw_b > 0 and rpw_a > 0 and rpw_b > 0:
                        # A's serve vs B's return, and vice versa
                        a_serve_edge = (spw_a - rpw_b) / 100.0  # Normalize percentages
                        b_serve_edge = (spw_b - rpw_a) / 100.0
                        serve_return_factor = (a_serve_edge - b_serve_edge) * 0.05
                        sackmann_reasoning += f"S/R: {spw_a:.0f}% vs {rpw_b:.0f}% ret. "

            except Exception:
                pass  # Gracefully degrade if Sackmann data is incomplete

        # Combine all factors
        prob_a = np.clip(
            elo_prob + rank_factor + surface_gap + h2h_factor + surface_wr_factor + serve_return_factor,
            0.05, 0.95
        )

        # Confidence based on data availability (boosted by Sackmann)
        confidence = 0.7
        if pa and pb:
            if pa.matches_played > 100 and pb.matches_played > 100:
                confidence = 0.85
            elif pa.matches_played > 50 and pb.matches_played > 50:
                confidence = 0.8
        if self.sackmann and h2h_factor != 0:
            confidence = min(0.95, confidence + 0.05)  # H2H data boosts confidence

        factors = {
            'elo_prob': round(elo_prob, 4),
            'rank_adjustment': round(rank_factor, 4),
            'surface_gap': round(surface_gap, 4),
            'h2h_factor': round(h2h_factor, 4),
            'surface_wr_factor': round(surface_wr_factor, 4),
            'serve_return_factor': round(serve_return_factor, 4),
            'a_overall_elo': pa.overall if pa else 1500,
            'b_overall_elo': pb.overall if pb else 1500,
            'a_surface_elo': pa.get_surface_elo(ctx.surface) if pa else 1500,
            'b_surface_elo': pb.get_surface_elo(ctx.surface) if pb else 1500,
            'sackmann_enriched': bool(self.sackmann),
        }

        reasoning = (f"Elo: {ctx.player_a} {elo_prob:.1%}. "
                     f"Surface gap: {surface_gap:+.1%}. "
                     f"Rank: {rank_factor:+.1%}. "
                     f"{sackmann_reasoning}")

        return AgentVote(
            agent_name="StatBot-Alpha",
            agent_role=self.ROLE,
            prob_a=round(prob_a, 4),
            confidence=confidence,
            reasoning=reasoning,
            factors=factors,
        )


class PsychologyAgent:
    """
    Analyzes fatigue, pressure, motivation.
    Key signals: days rest, recent match load, tournament importance, round pressure.
    Weight: 0.20
    """
    ROLE = "Behavioral Psychologist"
    WEIGHT = 0.20

    def analyze(self, ctx: MatchContext) -> AgentVote:
        base_prob = 0.5  # Start neutral, adjust based on psych factors
        factors = {}

        # --- Fatigue Index ---
        fatigue_a = self._fatigue_score(ctx.days_since_last_match_a, ctx.matches_last_14d_a)
        fatigue_b = self._fatigue_score(ctx.days_since_last_match_b, ctx.matches_last_14d_b)
        fatigue_delta = (fatigue_b - fatigue_a) * 0.08  # ±8% max
        factors['fatigue_a'] = round(fatigue_a, 3)
        factors['fatigue_b'] = round(fatigue_b, 3)

        # --- Motivation/Momentum ---
        form_a = ctx.recent_wins_a / 10.0
        form_b = ctx.recent_wins_b / 10.0
        form_delta = (form_a - form_b) * 0.06  # ±6% max
        factors['form_a'] = form_a
        factors['form_b'] = form_b

        # --- Tournament Pressure ---
        pressure_factor = 0.0
        level_pressure = {'G': 0.04, 'M': 0.03, 'A': 0.02, 'B': 0.01, 'F': 0.04}
        round_pressure = {'F': 0.05, 'SF': 0.03, 'QF': 0.02, 'R16': 0.01}

        # Higher-ranked players handle pressure better
        if ctx.rank_a < ctx.rank_b:
            pressure_factor = level_pressure.get(ctx.tourney_level, 0.01) * 0.5
            rp = round_pressure.get(ctx.round_name, 0)
            pressure_factor += rp * 0.3
        elif ctx.rank_b < ctx.rank_a:
            pressure_factor = -(level_pressure.get(ctx.tourney_level, 0.01) * 0.5)

        factors['pressure_factor'] = round(pressure_factor, 4)

        # --- Seed Advantage (expectation/comfort) ---
        seed_bonus = 0.0
        if ctx.seed_a and not ctx.seed_b:
            seed_bonus = 0.02
        elif ctx.seed_b and not ctx.seed_a:
            seed_bonus = -0.02
        factors['seed_bonus'] = seed_bonus

        # --- Best of 5 favors higher ranked ---
        bo5_factor = 0.0
        if ctx.best_of == 5 and ctx.rank_a < ctx.rank_b:
            bo5_factor = 0.03  # Better player more likely to win in longer format
        elif ctx.best_of == 5 and ctx.rank_b < ctx.rank_a:
            bo5_factor = -0.03
        factors['bo5_factor'] = bo5_factor

        prob_a = np.clip(
            base_prob + fatigue_delta + form_delta + pressure_factor + seed_bonus + bo5_factor,
            0.15, 0.85
        )

        confidence = 0.6  # Psych factors are softer signals

        reasoning = (f"Fatigue: A={fatigue_a:.0%} B={fatigue_b:.0%} (delta {fatigue_delta:+.1%}). "
                     f"Form: A={form_a:.0%} B={form_b:.0%}. "
                     f"Pressure bias: {pressure_factor:+.1%}.")

        return AgentVote(
            agent_name="PsychBot-Beta",
            agent_role=self.ROLE,
            prob_a=round(prob_a, 4),
            confidence=confidence,
            reasoning=reasoning,
            factors=factors,
        )

    @staticmethod
    def _fatigue_score(days_rest: int, matches_14d: int) -> float:
        """0 = fresh, 1 = exhausted."""
        rest_fatigue = max(0, 1.0 - days_rest / 5.0)  # 0 days = 1.0, 5+ = 0.0
        load_fatigue = min(1.0, matches_14d / 8.0)     # 8+ matches in 14 days = max
        return (rest_fatigue * 0.4 + load_fatigue * 0.6)


class MarketMakerAgent:
    """
    Analyzes market odds to find value.
    Detects when our model disagrees with the market.
    Weight: 0.20
    """
    ROLE = "Market Maker"
    WEIGHT = 0.20

    def analyze(self, ctx: MatchContext) -> AgentVote:
        factors = {}

        # If we have odds, use them to anchor
        if ctx.odds_a and ctx.odds_b:
            market_prob_a = 1.0 / ctx.odds_a
            market_prob_b = 1.0 / ctx.odds_b

            # Remove overround
            total = market_prob_a + market_prob_b
            market_prob_a /= total
            market_prob_b /= total

            factors['market_prob_a'] = round(market_prob_a, 4)
            factors['market_odds_a'] = ctx.odds_a
            factors['market_odds_b'] = ctx.odds_b
            factors['overround'] = round(total - 1.0, 4)

            # Market is smart — use as baseline but allow deviation
            prob_a = market_prob_a
            confidence = 0.8  # Market odds are strong signal
        else:
            # No odds — use rank-based proxy
            if ctx.rank_a > 0 and ctx.rank_b > 0:
                total = ctx.rank_a + ctx.rank_b
                prob_a = ctx.rank_b / total
            else:
                prob_a = 0.5
            confidence = 0.4  # Low confidence without real odds

            factors['market_prob_a'] = None
            factors['rank_based'] = True

        # --- Grand Slam / Masters value adjustment ---
        # Markets tend to be sharper in big tournaments
        if ctx.tourney_level in ('G', 'M', 'F'):
            factors['market_efficiency'] = 'HIGH'
            # Small contrarian signal: slightly fade the big favorite
            if prob_a > 0.75:
                prob_a -= 0.02  # Markets slightly overprice big GS favorites
                factors['big_fav_fade'] = True
        else:
            factors['market_efficiency'] = 'MEDIUM'

        prob_a = np.clip(prob_a, 0.05, 0.95)

        reasoning = (f"Market implies {ctx.player_a} {prob_a:.1%}. "
                     f"Efficiency: {factors.get('market_efficiency', 'N/A')}.")

        return AgentVote(
            agent_name="MarketBot-Gamma",
            agent_role=self.ROLE,
            prob_a=round(prob_a, 4),
            confidence=confidence,
            reasoning=reasoning,
            factors=factors,
        )


class ContrarianAgent:
    """
    Looks for upset potential — fades public favorites.
    Now enhanced with JeffSackmann H2H upset detection.
    Weight: 0.10
    """
    ROLE = "Contrarian Analyst"
    WEIGHT = 0.10

    def __init__(self, sackmann: 'JeffSackmannLoader' = None):
        self.sackmann = sackmann

    def analyze(self, ctx: MatchContext) -> AgentVote:
        factors = {}
        prob_a = 0.5

        factors['handedness'] = 'unknown'

        # --- Surface upset patterns ---
        surface_upset_boost = {'Clay': 0.05, 'Grass': 0.03, 'Hard': 0.0}
        upset_boost = surface_upset_boost.get(ctx.surface, 0)

        if ctx.rank_a > ctx.rank_b:
            prob_a += upset_boost
            factors['upset_boost_to'] = ctx.player_a
        elif ctx.rank_b > ctx.rank_a:
            prob_a -= upset_boost
            factors['upset_boost_to'] = ctx.player_b

        # --- Early round upset bias ---
        early_rounds = {'R128': 0.04, 'R64': 0.03, 'R32': 0.02, 'R16': 0.01}
        round_upset = early_rounds.get(ctx.round_name, 0)

        if ctx.rank_a > ctx.rank_b:
            prob_a += round_upset
        else:
            prob_a -= round_upset
        factors['round_upset_factor'] = round_upset

        # --- Fatigue-based upset ---
        if ctx.matches_last_14d_a > 6 and ctx.rank_a < ctx.rank_b:
            prob_a -= 0.03
            factors['tired_favorite'] = ctx.player_a
        if ctx.matches_last_14d_b > 6 and ctx.rank_b < ctx.rank_a:
            prob_a += 0.03
            factors['tired_favorite'] = ctx.player_b

        # === SACKMANN: H2H Upset Detection ===
        h2h_upset_factor = 0.0
        if self.sackmann:
            try:
                h2h = self.sackmann.get_h2h(ctx.player_a, ctx.player_b)
                total = h2h.a_wins + h2h.b_wins
                if total >= 3:
                    # If the lower-ranked player dominates H2H → upset value
                    if ctx.rank_a > ctx.rank_b and h2h.a_wins > h2h.b_wins:
                        # Underdog A actually wins H2H → contrarian signal!
                        h2h_upset_factor = 0.06 * (h2h.a_wins / total)
                        factors['h2h_upset_signal'] = f"{ctx.player_a} leads H2H {h2h.a_wins}-{h2h.b_wins} as underdog"
                    elif ctx.rank_b > ctx.rank_a and h2h.b_wins > h2h.a_wins:
                        h2h_upset_factor = -0.06 * (h2h.b_wins / total)
                        factors['h2h_upset_signal'] = f"{ctx.player_b} leads H2H {h2h.b_wins}-{h2h.a_wins} as underdog"

                # Recent form from Sackmann (last 10 matches)
                form_a = self.sackmann.get_recent_form(ctx.player_a, n=10)
                form_b = self.sackmann.get_recent_form(ctx.player_b, n=10)
                if form_a and form_b:
                    recent_wr_a = sum(1 for m in form_a if m.winner_name and ctx.player_a.lower() in m.winner_name.lower()) / max(1, len(form_a))
                    recent_wr_b = sum(1 for m in form_b if m.winner_name and ctx.player_b.lower() in m.winner_name.lower()) / max(1, len(form_b))
                    # If underdog has better recent form → upset value
                    if ctx.rank_a > ctx.rank_b and recent_wr_a > recent_wr_b:
                        h2h_upset_factor += 0.03
                        factors['form_upset'] = f"{ctx.player_a} form {recent_wr_a:.0%} > {recent_wr_b:.0%}"
                    elif ctx.rank_b > ctx.rank_a and recent_wr_b > recent_wr_a:
                        h2h_upset_factor -= 0.03
                        factors['form_upset'] = f"{ctx.player_b} form {recent_wr_b:.0%} > {recent_wr_a:.0%}"
            except Exception:
                pass

        prob_a += h2h_upset_factor
        factors['h2h_upset_factor'] = round(h2h_upset_factor, 4)

        prob_a = np.clip(prob_a, 0.15, 0.85)
        confidence = 0.5 if not h2h_upset_factor else 0.65  # Higher confidence when H2H data backs it

        reasoning = (f"Contrarian: upset boost {upset_boost:.1%} on {ctx.surface}. "
                     f"Round: {round_upset:.1%}. "
                     f"H2H upset: {h2h_upset_factor:+.1%}.")

        return AgentVote(
            agent_name="ContrarianBot-Delta",
            agent_role=self.ROLE,
            prob_a=round(prob_a, 4),
            confidence=confidence,
            reasoning=reasoning,
            factors=factors,
        )


class NewsScoutAgent:
    """
    Processes injury, weather, and breaking news signals.
    Without live API, uses provided context (injury flags, conditions).
    Weight: 0.15
    """
    ROLE = "News Scout"
    WEIGHT = 0.15

    def analyze(self, ctx: MatchContext) -> AgentVote:
        factors = {}
        adjustment = 0.0

        # --- Injury signals ---
        if ctx.injury_a:
            severity = self._injury_severity(ctx.injury_a)
            adjustment -= severity * 0.15  # Up to -15% for severe injury
            factors['injury_a'] = ctx.injury_a
            factors['injury_a_severity'] = severity

        if ctx.injury_b:
            severity = self._injury_severity(ctx.injury_b)
            adjustment += severity * 0.15
            factors['injury_b'] = ctx.injury_b
            factors['injury_b_severity'] = severity

        # --- Altitude adjustment ---
        if ctx.altitude_m > 500:
            # High altitude: bigger server advantage, ball travels faster
            factors['altitude'] = ctx.altitude_m
            factors['altitude_effect'] = 'serve_boost'

        # --- Indoor/Outdoor ---
        if ctx.indoor:
            # Indoor: faster conditions, serve advantage
            factors['conditions'] = 'indoor_fast'
        else:
            factors['conditions'] = 'outdoor'

        # Base probability neutral + adjustments
        prob_a = np.clip(0.5 + adjustment, 0.1, 0.9)

        confidence = 0.5
        if ctx.injury_a or ctx.injury_b:
            confidence = 0.7  # Injury info is high-value signal

        reasoning = (f"News: injury adjustment {adjustment:+.1%}. "
                     f"Conditions: {factors.get('conditions', 'standard')}.")

        return AgentVote(
            agent_name="NewsBot-Epsilon",
            agent_role=self.ROLE,
            prob_a=round(prob_a, 4),
            confidence=confidence,
            reasoning=reasoning,
            factors=factors,
        )

    @staticmethod
    def _injury_severity(injury_desc: str) -> float:
        """Estimate injury severity from text. 0-1 scale."""
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


# === MiroFish LLM Agent ===

class MiroFishAgent:
    """
    MiroFish — LLM-powered qualitative analysis agent.
    
    Uses DeepSeek v3.2 (or configured LLM) for:
    1. News/sentiment signals that stats don't capture
    2. Motivation / "tanking" detection (top player on small tourney)
    3. Reasoning validation when statistical agents disagree
    4. Edge case evaluation (returning from injury, surface switch)
    
    Weight: 0.10 (qualitative complement to pure statistics)
    Falls back to neutral 0.50 if LLM is unavailable.
    """
    ROLE = "MiroFish LLM"
    WEIGHT = 0.10

    def __init__(self):
        self.client = None
        self.model = None
        self._init_client()

    def _init_client(self):
        """Initialize LLM client from environment."""
        try:
            import os
            from dotenv import load_dotenv
            from pathlib import Path
            load_dotenv(Path(__file__).parent.parent / ".env")
            
            api_key = os.getenv("LLM_API_KEY")
            base_url = os.getenv("LLM_BASE_URL")
            self.model = os.getenv("LLM_MODEL_NAME", "deepseek-ai/deepseek-v3.2")
            
            if api_key and base_url:
                try:
                    from openai import OpenAI
                    self.client = OpenAI(api_key=api_key, base_url=base_url)
                except ImportError:
                    self.client = None
        except Exception:
            self.client = None

    def analyze(self, ctx: MatchContext) -> AgentVote:
        """
        Ask MiroFish LLM to analyze qualitative factors.
        Falls back to neutral vote if LLM unavailable.
        """
        if not self.client:
            return self._neutral_vote(ctx, "LLM unavailable")

        try:
            prompt = self._build_prompt(ctx)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are MiroFish, a tennis betting analysis AI. "
                        "Analyze qualitative factors that pure statistics miss: "
                        "motivation, injuries, schedule fatigue, surface transitions, "
                        "pressure situations, and form trajectories. "
                        "Respond ONLY with valid JSON: "
                        "{\"prob_a\": 0.XX, \"confidence\": 0.X, \"reasoning\": \"...\"}"
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.3,
            )

            text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            
            data = json.loads(text)
            prob_a = max(0.1, min(0.9, float(data.get("prob_a", 0.5))))
            confidence = max(0.1, min(1.0, float(data.get("confidence", 0.5))))
            reasoning = data.get("reasoning", "LLM analysis")

            return AgentVote(
                agent_name="MiroFish-LLM",
                agent_role=self.ROLE,
                prob_a=prob_a,
                confidence=confidence,
                reasoning=f"🐡 {reasoning[:200]}",
                factors={"source": "mirofish_llm", "model": self.model or "unknown"},
            )

        except Exception as e:
            return self._neutral_vote(ctx, f"LLM error: {str(e)[:80]}")

    def _build_prompt(self, ctx: MatchContext) -> str:
        """Build analysis prompt with match context."""
        parts = [
            f"Match: {ctx.player_a} vs {ctx.player_b}",
            f"Surface: {ctx.surface} | Tournament: {ctx.tourney_name} ({ctx.tourney_level})",
            f"Round: {ctx.round_name} | Date: {ctx.date}",
            f"Rankings: #{ctx.rank_a} vs #{ctx.rank_b}",
        ]

        if ctx.odds_a and ctx.odds_b:
            parts.append(f"Market odds: {ctx.odds_a:.2f} vs {ctx.odds_b:.2f}")

        if ctx.age_a and ctx.age_b:
            parts.append(f"Ages: {ctx.age_a:.1f} vs {ctx.age_b:.1f}")

        if ctx.days_since_last_match_a is not None:
            parts.append(
                f"Rest: A={ctx.days_since_last_match_a}d "
                f"({ctx.matches_last_14d_a} matches/14d), "
                f"B={ctx.days_since_last_match_b}d "
                f"({ctx.matches_last_14d_b} matches/14d)"
            )

        parts.append(
            "\nAnalyze qualitative factors: motivation level, injuries, "
            "schedule fatigue, surface affinity, mental state, and any "
            "edge the market might miss. Give prob_a (0.1-0.9) and confidence (0.1-1.0)."
        )

        return "\n".join(parts)

    def _neutral_vote(self, ctx: MatchContext, reason: str) -> AgentVote:
        """Return neutral vote when LLM is unavailable."""
        return AgentVote(
            agent_name="MiroFish-LLM",
            agent_role=self.ROLE,
            prob_a=0.5,
            confidence=0.3,  # Low confidence = minimal swarm impact
            reasoning=f"🐡 Neutral ({reason})",
            factors={"source": "mirofish_fallback"},
        )


# === Consensus Engine ===

class TennisSwarm:
    """
    Multi-agent swarm for tennis match prediction.
    
    Usage:
        swarm = TennisSwarm()
        
        match = MatchContext(
            player_a="Jannik Sinner",
            player_b="Daniil Medvedev",
            surface="Hard",
            tourney_name="Miami Open",
            tourney_level="M",
            round_name="SF",
            date="2026-03-28",
            rank_a=1, rank_b=5,
        )
        
        result = swarm.predict(match)
        print(f"{result.player_a}: {result.prob_a:.1%} | Action: {result.recommended_action}")
    """

    def __init__(self, elo_engine: TennisEloEngine = None, sackmann_loader: 'JeffSackmannLoader' = None):
        if elo_engine is None:
            data_dir = str(Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp")
            elo_engine = TennisEloEngine(data_dir)
            elo_engine.load_and_process(start_year=2000)

        self.elo = elo_engine
        self.kelly = KellyCriterion(bankroll=5000)

        # === Load JeffSackmann data (143K matches, 132K players) ===
        self.sackmann = sackmann_loader
        if self.sackmann is None and SACKMANN_AVAILABLE:
            try:
                self.sackmann = JeffSackmannLoader()
                self.sackmann.load_all(start_year=2015)  # Recent data for speed
                print(f"  🎾 Sackmann: {len(self.sackmann.matches)} matches, {len(self.sackmann.players)} players")
            except Exception as e:
                print(f"  ⚠️  Sackmann load failed: {e} (continuing with Elo only)")
                self.sackmann = None

        # Initialize agents WITH Sackmann injection + MiroFish LLM
        self.agents = [
            StatisticalAgent(elo_engine, sackmann=self.sackmann),
            PsychologyAgent(),
            MarketMakerAgent(),
            ContrarianAgent(sackmann=self.sackmann),
            NewsScoutAgent(),
            MiroFishAgent(),  # 🐡 LLM qualitative analysis
        ]

        # Weights rescaled to include MiroFish at 0.10
        # Original: Stat=0.35, Psych=0.20, Market=0.20, Contrarian=0.10, News=0.15
        # Rescaled by 0.9: each original weight * 0.9
        self.weights = {
            "Statistical Analyst": 0.32,
            "Behavioral Psychologist": 0.18,
            "Market Maker": 0.18,
            "Contrarian Analyst": 0.09,
            "News Scout": 0.13,
            "MiroFish LLM": 0.10,         # 🐡 qualitative edge
        }

    def predict(self, ctx: MatchContext) -> SwarmConsensus:
        """Run all agents and compute weighted consensus."""
        votes = []

        for agent in self.agents:
            vote = agent.analyze(ctx)
            votes.append(vote)

        # --- Weighted Consensus ---
        weighted_prob_a = 0.0
        total_weight = 0.0

        for vote in votes:
            w = self.weights.get(vote.agent_role, 0.1) * vote.confidence
            weighted_prob_a += vote.prob_a * w
            total_weight += w

        consensus_prob_a = weighted_prob_a / total_weight if total_weight > 0 else 0.5
        consensus_prob_b = 1.0 - consensus_prob_a

        # --- Data Quality Score ---
        data_quality = self._assess_data_quality(ctx)

        # --- Confidence Level ---
        spread = max(v.prob_a for v in votes) - min(v.prob_a for v in votes)
        if spread < 0.10 and data_quality > 0.7:
            confidence = "ELITE"
        elif spread < 0.15 and data_quality > 0.5:
            confidence = "HIGH"
        elif spread < 0.25:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        # --- Edge vs Market ---
        edge_vs_market = None
        if ctx.odds_a:
            market_prob = 1.0 / ctx.odds_a
            edge_vs_market = consensus_prob_a - market_prob

        # --- Kelly Sizing ---
        if ctx.odds_a and edge_vs_market and edge_vs_market > 0.03:
            kelly_result = self.kelly.size_bet(consensus_prob_a, ctx.odds_a)
            kelly_bet = kelly_result.bet_size
        elif ctx.odds_b and consensus_prob_b > consensus_prob_a:
            market_prob_b = 1.0 / ctx.odds_b
            edge_b = consensus_prob_b - market_prob_b
            if edge_b > 0.03:
                kelly_result = self.kelly.size_bet(consensus_prob_b, ctx.odds_b)
                kelly_bet = kelly_result.bet_size
            else:
                kelly_bet = 0
        else:
            kelly_bet = 0

        # --- Action ---
        if consensus_prob_a > 0.55 and edge_vs_market and edge_vs_market >= 0.03:
            action = "BET_A"
        elif consensus_prob_b > 0.55 and ctx.odds_b:
            market_prob_b = 1.0 / ctx.odds_b
            edge_b = consensus_prob_b - market_prob_b
            if edge_b >= 0.03:
                action = "BET_B"
            else:
                action = "SKIP"
        else:
            action = "SKIP"

        # --- Reasoning Summary ---
        summary_parts = []
        for v in sorted(votes, key=lambda x: self.weights.get(x.agent_role, 0), reverse=True):
            summary_parts.append(f"{v.agent_role}: {ctx.player_a} {v.prob_a:.0%} ({v.reasoning})")

        return SwarmConsensus(
            player_a=ctx.player_a,
            player_b=ctx.player_b,
            surface=ctx.surface,
            prob_a=round(consensus_prob_a, 4),
            prob_b=round(consensus_prob_b, 4),
            confidence=confidence,
            edge_vs_market=round(edge_vs_market, 4) if edge_vs_market else None,
            recommended_action=action,
            kelly_bet_size=round(kelly_bet, 2),
            agent_votes=votes,
            reasoning_summary="\n".join(summary_parts),
            data_quality_score=round(data_quality, 2),
        )

    def _assess_data_quality(self, ctx: MatchContext) -> float:
        """Score data quality 0-1. Are we confident in our data?"""
        score = 0.0

        # Elo data available
        pa = self.elo.get_player(ctx.player_a)
        pb = self.elo.get_player(ctx.player_b)

        if pa and pa.matches_played > 100:
            score += 0.20
        elif pa and pa.matches_played > 30:
            score += 0.10
        else:
            score += 0.03

        if pb and pb.matches_played > 100:
            score += 0.20
        elif pb and pb.matches_played > 30:
            score += 0.10
        else:
            score += 0.03

        # Odds available
        if ctx.odds_a and ctx.odds_b:
            score += 0.20

        # Recent form data
        if ctx.recent_wins_a > 0 and ctx.recent_wins_b > 0:
            score += 0.10

        # Rankings available
        if ctx.rank_a > 0 and ctx.rank_b > 0:
            score += 0.10

        # === Sackmann data bonus ===
        if self.sackmann:
            try:
                h2h = self.sackmann.get_h2h(ctx.player_a, ctx.player_b)
                if h2h.a_wins + h2h.b_wins >= 1:
                    score += 0.10  # H2H data available
                profile_a = self.sackmann.get_player(ctx.player_a)
                profile_b = self.sackmann.get_player(ctx.player_b)
                if profile_a and profile_b:
                    score += 0.10  # Full profiles available
            except Exception:
                pass

        return min(1.0, score)

    def apply_scenario_overlay(
        self,
        consensus: 'SwarmConsensus',
        signals: 'Any',
    ) -> 'SwarmConsensus':
        """
        Apply NemoFish scenario overlay to an existing SwarmConsensus.
        Returns a NEW SwarmConsensus with bounded adjustments.

        This is OPT-IN — not called from predict(). Called from scenario_runner.

        Args:
            consensus: Baseline SwarmConsensus from predict()
            signals: ScenarioSignals from scenario simulation

        Returns:
            New SwarmConsensus with adjusted probabilities, confidence, and action.
        """
        try:
            from intelligence.scenario_overlay import ScenarioOverlay

            overlay = ScenarioOverlay(max_prob_adjustment=0.03)
            result = overlay.apply(
                signals=signals,
                baseline_prob_a=consensus.prob_a,
                baseline_prob_b=consensus.prob_b,
                baseline_confidence=consensus.confidence,
                baseline_action=consensus.recommended_action,
                player_a=consensus.player_a,
                player_b=consensus.player_b,
            )

            # Build adjusted consensus
            adjusted = SwarmConsensus(
                player_a=consensus.player_a,
                player_b=consensus.player_b,
                surface=consensus.surface,
                prob_a=result.adjusted_prob_a,
                prob_b=result.adjusted_prob_b,
                confidence=result.adjusted_confidence,
                edge_vs_market=consensus.edge_vs_market,
                recommended_action=result.adjusted_action,
                kelly_bet_size=consensus.kelly_bet_size,
                agent_votes=consensus.agent_votes,
                reasoning_summary=consensus.reasoning_summary +
                    f"\n[NemoFish Overlay] {result.explanation}",
                data_quality_score=consensus.data_quality_score,
            )
            return adjusted

        except Exception as e:
            # Fail-closed: return original consensus unchanged
            return consensus

    def predict_and_display(self, ctx: MatchContext) -> SwarmConsensus:
        """Predict and pretty-print the results."""
        result = self.predict(ctx)

        print(f"\n{'='*65}")
        print(f"  🎾 SWARM PREDICTION: {ctx.player_a} vs {ctx.player_b}")
        print(f"  {ctx.tourney_name} | {ctx.surface} | {ctx.round_name}")
        print(f"{'='*65}")

        print(f"\n  AGENT VOTES:")
        for v in result.agent_votes:
            bar_a = "█" * int(v.prob_a * 20) + "░" * int((1-v.prob_a) * 20)
            print(f"    {v.agent_role:<25} {ctx.player_a} {v.prob_a:.0%} {bar_a} {1-v.prob_a:.0%} {ctx.player_b}")

        print(f"\n  ╔══════════════════════════════════════════════╗")
        print(f"  ║  CONSENSUS: {ctx.player_a} {result.prob_a:.1%} | {ctx.player_b} {result.prob_b:.1%}")
        print(f"  ║  Confidence: {result.confidence}")
        print(f"  ║  Data Quality: {result.data_quality_score:.0%}")
        if result.edge_vs_market:
            print(f"  ║  Edge vs Market: {result.edge_vs_market:+.1%}")
        print(f"  ║  Action: {result.recommended_action}")
        if result.kelly_bet_size > 0:
            print(f"  ║  Kelly Bet Size: ${result.kelly_bet_size:.2f}")
        print(f"  ╚══════════════════════════════════════════════╝")

        return result


# === CLI Demo ===
if __name__ == "__main__":
    print("=" * 65)
    print("  NEMOFISH TENNIS SWARM — Loading...")
    print("=" * 65)

    swarm = TennisSwarm()

    # Miami Open 2026 potential matchups
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
            player_a="Jannik Sinner", player_b="Carlos Alcaraz",
            surface="Hard", tourney_name="Miami Open 2026",
            tourney_level="M", round_name="F", date="2026-03-30",
            rank_a=1, rank_b=3, seed_a=1, seed_b=3,
            odds_a=1.55, odds_b=2.55,
            days_since_last_match_a=2, days_since_last_match_b=2,
            matches_last_14d_a=5, matches_last_14d_b=6,
            recent_wins_a=9, recent_wins_b=7,
            best_of=3,
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
    ]

    print("\n" + "🌴" * 20)
    print("  MIAMI OPEN 2026 — SWARM PREDICTIONS")
    print("🌴" * 20)

    for m in matches:
        swarm.predict_and_display(m)
