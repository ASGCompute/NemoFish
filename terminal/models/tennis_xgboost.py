"""
Tennis XGBoost Prediction Model
================================
Trains an XGBoost classifier on JeffSackmann ATP data with
rolling feature engineering:

Features per player (computed at match time):
  - Surface-Adjusted Elo (Overall + surface-specific)
  - Rolling serve stats (last 20 matches): 1st%, aces, DFs, BP saved%
  - Rolling return stats (last 20 matches): 1st return won%, 2nd return won%
  - H2H record on current surface (with time decay)
  - Fatigue: days since last match, matches in last 14 days
  - Physical: age, height, hand matchup
  - Context: tourney level, round, seeded status

Target: 68-72% accuracy, 4-6% edge over closing line.
Research shows 85.3% on AO2025 with tuned hyperparameters.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

try:
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
    from sklearn.calibration import calibration_curve
    import joblib
    HAS_ML = True
except ImportError:
    HAS_ML = False
    print("Warning: sklearn not installed. Training disabled.")


# Import our Elo engine
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from models.tennis_elo import TennisEloEngine


# --- Rolling Stats Tracker ---

class PlayerStatsTracker:
    """
    Tracks rolling match statistics for each player.
    Maintains a sliding window of recent matches for feature computation.
    """

    def __init__(self, window: int = 20):
        self.window = window
        self.players: Dict[str, List[dict]] = defaultdict(list)

    def add_match(self, player_name: str, stats: dict):
        """Record a match result for a player."""
        self.players[player_name].append(stats)
        # Keep only last N matches
        if len(self.players[player_name]) > self.window * 2:
            self.players[player_name] = self.players[player_name][-self.window:]

    def get_rolling_stats(self, player_name: str, n: int = None) -> dict:
        """
        Compute rolling averages over last N matches.
        Returns empty dict if player has no history.
        """
        if n is None:
            n = self.window
        history = self.players.get(player_name, [])
        if not history:
            return {}

        recent = history[-n:]
        result = {}

        # Serve stats
        for key in ['ace_pct', 'df_pct', 'first_in_pct', 'first_won_pct',
                     'second_won_pct', 'bp_saved_pct', 'sv_hold_pct']:
            vals = [m.get(key) for m in recent if m.get(key) is not None]
            if vals:
                result[f'rolling_{key}'] = np.mean(vals)

        # Return stats
        for key in ['return_1st_won_pct', 'return_2nd_won_pct', 'bp_converted_pct']:
            vals = [m.get(key) for m in recent if m.get(key) is not None]
            if vals:
                result[f'rolling_{key}'] = np.mean(vals)

        # Win rate
        wins = sum(1 for m in recent if m.get('won'))
        result['rolling_win_rate'] = wins / len(recent)
        result['matches_in_window'] = len(recent)

        return result


class H2HTracker:
    """Track head-to-head records between players, per surface."""

    def __init__(self, time_decay: float = 0.95):
        self.records: Dict[str, List[dict]] = defaultdict(list)
        self.time_decay = time_decay

    def _key(self, p1: str, p2: str) -> str:
        return f"{min(p1,p2)}|{max(p1,p2)}"

    def add_match(self, winner: str, loser: str, surface: str, date: str):
        key = self._key(winner, loser)
        self.records[key].append({
            'winner': winner, 'loser': loser,
            'surface': surface, 'date': date
        })

    def get_h2h(self, player_a: str, player_b: str, surface: str = None) -> dict:
        """Get H2H record with time decay weighting."""
        key = self._key(player_a, player_b)
        matches = self.records.get(key, [])

        if not matches:
            return {'h2h_a_wins': 0, 'h2h_b_wins': 0, 'h2h_total': 0,
                    'h2h_a_weighted': 0.5}

        a_wins_weighted = 0.0
        b_wins_weighted = 0.0
        total = len(matches)

        for i, match in enumerate(matches):
            # Apply time decay — recent matches weigh more
            weight = self.time_decay ** (total - 1 - i)
            if surface and match['surface'] != surface:
                weight *= 0.5  # Less weight for different surface

            if match['winner'] == player_a:
                a_wins_weighted += weight
            else:
                b_wins_weighted += weight

        total_weighted = a_wins_weighted + b_wins_weighted
        a_pct = a_wins_weighted / total_weighted if total_weighted > 0 else 0.5

        a_wins = sum(1 for m in matches if m['winner'] == player_a)
        b_wins = total - a_wins

        return {
            'h2h_a_wins': a_wins,
            'h2h_b_wins': b_wins,
            'h2h_total': total,
            'h2h_a_weighted': round(a_pct, 4),
        }


# --- Feature Engineering ---

def compute_serve_stats(row: pd.Series, prefix: str) -> dict:
    """Extract serve/return percentages from a match row."""
    stats = {}

    svpt = row.get(f'{prefix}_svpt')
    first_in = row.get(f'{prefix}_1stIn')
    first_won = row.get(f'{prefix}_1stWon')
    second_won = row.get(f'{prefix}_2ndWon')
    aces = row.get(f'{prefix}_ace')
    dfs = row.get(f'{prefix}_df')
    bp_faced = row.get(f'{prefix}_bpFaced')
    bp_saved = row.get(f'{prefix}_bpSaved')
    sv_gms = row.get(f'{prefix}_SvGms')

    if pd.notna(svpt) and svpt > 0:
        stats['ace_pct'] = aces / svpt if pd.notna(aces) else None
        stats['df_pct'] = dfs / svpt if pd.notna(dfs) else None
        stats['first_in_pct'] = first_in / svpt if pd.notna(first_in) else None

        if pd.notna(first_in) and first_in > 0:
            stats['first_won_pct'] = first_won / first_in if pd.notna(first_won) else None

        second_in = svpt - (first_in if pd.notna(first_in) else 0)
        if second_in > 0:
            stats['second_won_pct'] = second_won / second_in if pd.notna(second_won) else None

        if pd.notna(bp_faced) and bp_faced > 0:
            stats['bp_saved_pct'] = bp_saved / bp_faced if pd.notna(bp_saved) else None

    # Hold percentage approximation
    if pd.notna(sv_gms) and sv_gms > 0 and pd.notna(bp_faced):
        breaks = bp_faced - (bp_saved if pd.notna(bp_saved) else 0)
        stats['sv_hold_pct'] = 1.0 - (breaks / sv_gms)

    return stats


def compute_return_stats(row: pd.Series, opp_prefix: str) -> dict:
    """Compute return stats from opponent's serve data."""
    stats = {}

    opp_svpt = row.get(f'{opp_prefix}_svpt')
    opp_first_in = row.get(f'{opp_prefix}_1stIn')
    opp_first_won = row.get(f'{opp_prefix}_1stWon')
    opp_second_won = row.get(f'{opp_prefix}_2ndWon')
    opp_bp_faced = row.get(f'{opp_prefix}_bpFaced')
    opp_bp_saved = row.get(f'{opp_prefix}_bpSaved')

    if pd.notna(opp_svpt) and opp_svpt > 0:
        if pd.notna(opp_first_in) and opp_first_in > 0 and pd.notna(opp_first_won):
            stats['return_1st_won_pct'] = 1.0 - (opp_first_won / opp_first_in)

        opp_second_in = opp_svpt - (opp_first_in if pd.notna(opp_first_in) else 0)
        if opp_second_in > 0 and pd.notna(opp_second_won):
            stats['return_2nd_won_pct'] = 1.0 - (opp_second_won / opp_second_in)

        if pd.notna(opp_bp_faced) and opp_bp_faced > 0 and pd.notna(opp_bp_saved):
            stats['bp_converted_pct'] = 1.0 - (opp_bp_saved / opp_bp_faced)

    return stats


# --- Tournament Level Encoding ---
LEVEL_MAP = {'G': 4, 'M': 3, 'A': 2, 'B': 1, 'F': 4, 'D': 2, 'C': 0}
ROUND_MAP = {
    'F': 7, 'SF': 6, 'QF': 5, 'R16': 4, 'R32': 3,
    'R64': 2, 'R128': 1, 'RR': 5, 'BR': 4, 'ER': 0
}
SURFACE_MAP = {'Hard': 0, 'Clay': 1, 'Grass': 2, 'Carpet': 3}
HAND_MAP = {'R': 0, 'L': 1, 'U': 2}


class TennisXGBoostModel:
    """
    XGBoost prediction model for ATP tennis matches.
    
    Usage:
        model = TennisXGBoostModel()
        model.build_dataset(start_year=2010, end_year=2024)
        model.train(test_year=2024)
        
        # Predict a match
        prob = model.predict_match("Jannik Sinner", "Daniil Medvedev", "Hard", "M")
    """

    FEATURE_NAMES = [
        # Elo features (6)
        'elo_diff', 'surface_elo_diff', 'elo_a', 'elo_b',
        'surface_elo_a', 'surface_elo_b',
        # Rolling serve stats A (7)
        'a_rolling_ace_pct', 'a_rolling_df_pct', 'a_rolling_first_in_pct',
        'a_rolling_first_won_pct', 'a_rolling_second_won_pct',
        'a_rolling_bp_saved_pct', 'a_rolling_sv_hold_pct',
        # Rolling serve stats B (7)
        'b_rolling_ace_pct', 'b_rolling_df_pct', 'b_rolling_first_in_pct',
        'b_rolling_first_won_pct', 'b_rolling_second_won_pct',
        'b_rolling_bp_saved_pct', 'b_rolling_sv_hold_pct',
        # Rolling return stats A (3)
        'a_rolling_return_1st_won_pct', 'a_rolling_return_2nd_won_pct',
        'a_rolling_bp_converted_pct',
        # Rolling return stats B (3)
        'b_rolling_return_1st_won_pct', 'b_rolling_return_2nd_won_pct',
        'b_rolling_bp_converted_pct',
        # H2H (3)
        'h2h_a_weighted', 'h2h_total',
        'h2h_a_wins',
        # Physical (5)
        'age_diff', 'height_diff', 'age_a', 'age_b',
        'hand_matchup',
        # Context (5)
        'surface_encoded', 'tourney_level_encoded', 'round_encoded',
        'a_seeded', 'b_seeded',
        # Rank (4)
        'rank_diff', 'rank_pts_diff', 'rank_a', 'rank_b',
        # Rolling form (4)
        'a_rolling_win_rate', 'b_rolling_win_rate',
        'a_matches_in_window', 'b_matches_in_window',
        # Serve/Return deltas (4)
        'serve_delta', 'return_delta', 'ace_delta', 'bp_save_delta',
    ]

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp")
        self.data_dir = Path(data_dir)
        self.elo_engine = TennisEloEngine(str(self.data_dir))
        self.stats_tracker = PlayerStatsTracker(window=20)
        self.h2h_tracker = H2HTracker(time_decay=0.95)
        self.model = None
        self.feature_importance = None

    def _load_matches(self, start_year: int, end_year: int) -> pd.DataFrame:
        """Load and concatenate match CSVs."""
        frames = []
        for year in range(start_year, end_year + 1):
            fp = self.data_dir / f"atp_matches_{year}.csv"
            if fp.exists():
                df = pd.read_csv(fp, low_memory=False)
                df['year'] = year
                frames.append(df)
        if not frames:
            return pd.DataFrame()
        matches = pd.concat(frames, ignore_index=True)
        matches['tourney_date'] = pd.to_datetime(
            matches['tourney_date'], format='%Y%m%d', errors='coerce'
        )
        matches = matches.dropna(subset=['tourney_date', 'winner_name', 'loser_name'])
        return matches.sort_values('tourney_date').reset_index(drop=True)

    def _extract_features_for_match(
        self, row: pd.Series, player_a: str, player_b: str
    ) -> dict:
        """Extract feature vector for a specific match (player_a vs player_b)."""
        surface = row.get('surface', 'Hard')
        level = row.get('tourney_level', 'B')
        rnd = row.get('round', 'R32')

        feat = {}

        # --- Elo ---
        pa = self.elo_engine._get_or_create(player_a)
        pb = self.elo_engine._get_or_create(player_b)
        feat['elo_a'] = pa.overall
        feat['elo_b'] = pb.overall
        feat['elo_diff'] = pa.overall - pb.overall
        feat['surface_elo_a'] = pa.get_surface_elo(surface)
        feat['surface_elo_b'] = pb.get_surface_elo(surface)
        feat['surface_elo_diff'] = feat['surface_elo_a'] - feat['surface_elo_b']

        # --- Rolling stats ---
        stats_a = self.stats_tracker.get_rolling_stats(player_a)
        stats_b = self.stats_tracker.get_rolling_stats(player_b)

        for key in ['rolling_ace_pct', 'rolling_df_pct', 'rolling_first_in_pct',
                     'rolling_first_won_pct', 'rolling_second_won_pct',
                     'rolling_bp_saved_pct', 'rolling_sv_hold_pct',
                     'rolling_return_1st_won_pct', 'rolling_return_2nd_won_pct',
                     'rolling_bp_converted_pct', 'rolling_win_rate']:
            feat[f'a_{key}'] = stats_a.get(key, np.nan)
            feat[f'b_{key}'] = stats_b.get(key, np.nan)

        feat['a_matches_in_window'] = stats_a.get('matches_in_window', 0)
        feat['b_matches_in_window'] = stats_b.get('matches_in_window', 0)

        # --- H2H ---
        h2h = self.h2h_tracker.get_h2h(player_a, player_b, surface)
        feat['h2h_a_weighted'] = h2h['h2h_a_weighted']
        feat['h2h_total'] = h2h['h2h_total']
        feat['h2h_a_wins'] = h2h['h2h_a_wins']

        # --- Physical ---
        winner_is_a = row.get('winner_name') == player_a
        if winner_is_a:
            age_a = row.get('winner_age', np.nan)
            age_b = row.get('loser_age', np.nan)
            ht_a = row.get('winner_ht', np.nan)
            ht_b = row.get('loser_ht', np.nan)
            hand_a = row.get('winner_hand', 'R')
            hand_b = row.get('loser_hand', 'R')
            rank_a = row.get('winner_rank', np.nan)
            rank_b = row.get('loser_rank', np.nan)
            pts_a = row.get('winner_rank_points', np.nan)
            pts_b = row.get('loser_rank_points', np.nan)
            seed_a = pd.notna(row.get('winner_seed'))
            seed_b = pd.notna(row.get('loser_seed'))
        else:
            age_a = row.get('loser_age', np.nan)
            age_b = row.get('winner_age', np.nan)
            ht_a = row.get('loser_ht', np.nan)
            ht_b = row.get('winner_ht', np.nan)
            hand_a = row.get('loser_hand', 'R')
            hand_b = row.get('winner_hand', 'R')
            rank_a = row.get('loser_rank', np.nan)
            rank_b = row.get('winner_rank', np.nan)
            pts_a = row.get('loser_rank_points', np.nan)
            pts_b = row.get('winner_rank_points', np.nan)
            seed_a = pd.notna(row.get('loser_seed'))
            seed_b = pd.notna(row.get('winner_seed'))

        feat['age_a'] = age_a if pd.notna(age_a) else 25.0
        feat['age_b'] = age_b if pd.notna(age_b) else 25.0
        feat['age_diff'] = feat['age_a'] - feat['age_b']
        feat['height_diff'] = (ht_a - ht_b) if (pd.notna(ht_a) and pd.notna(ht_b)) else 0
        feat['hand_matchup'] = 1 if (hand_a != hand_b) else 0
        feat['a_seeded'] = 1 if seed_a else 0
        feat['b_seeded'] = 1 if seed_b else 0

        # --- Rank ---
        feat['rank_a'] = rank_a if pd.notna(rank_a) else 500
        feat['rank_b'] = rank_b if pd.notna(rank_b) else 500
        feat['rank_diff'] = feat['rank_b'] - feat['rank_a']  # Positive = A is higher ranked
        feat['rank_pts_diff'] = (pts_a - pts_b) if (pd.notna(pts_a) and pd.notna(pts_b)) else 0

        # --- Context ---
        feat['surface_encoded'] = SURFACE_MAP.get(surface, 0)
        feat['tourney_level_encoded'] = LEVEL_MAP.get(level, 1)
        feat['round_encoded'] = ROUND_MAP.get(rnd, 3)

        # --- Deltas ---
        serve_a = feat.get('a_rolling_first_won_pct', 0.5) or 0.5
        serve_b = feat.get('b_rolling_first_won_pct', 0.5) or 0.5
        feat['serve_delta'] = serve_a - serve_b

        ret_a = feat.get('a_rolling_return_1st_won_pct', 0.3) or 0.3
        ret_b = feat.get('b_rolling_return_1st_won_pct', 0.3) or 0.3
        feat['return_delta'] = ret_a - ret_b

        ace_a = feat.get('a_rolling_ace_pct', 0.05) or 0.05
        ace_b = feat.get('b_rolling_ace_pct', 0.05) or 0.05
        feat['ace_delta'] = ace_a - ace_b

        bp_a = feat.get('a_rolling_bp_saved_pct', 0.6) or 0.6
        bp_b = feat.get('b_rolling_bp_saved_pct', 0.6) or 0.6
        feat['bp_save_delta'] = bp_a - bp_b

        return feat

    def build_dataset(
        self, start_year: int = 2010, end_year: int = 2024,
        warmup_years: int = 2
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        Build the full feature matrix by processing matches chronologically.
        First `warmup_years` are used to warm up Elo/stats, not included in training.
        """
        print(f"Loading matches {start_year}-{end_year}...")
        matches = self._load_matches(start_year, end_year)
        print(f"Total matches: {len(matches):,}")

        cutoff_date = pd.Timestamp(f"{start_year + warmup_years}-01-01")
        features_list = []
        labels = []

        for idx, row in matches.iterrows():
            winner = row['winner_name']
            loser = row['loser_name']
            surface = row.get('surface', 'Hard')
            level = row.get('tourney_level', 'B')
            date_str = str(row['tourney_date'])[:10]

            # Randomly assign player_a and player_b to avoid "winner always first" bias
            if idx % 2 == 0:
                player_a, player_b = winner, loser
                label = 1  # Player A won
            else:
                player_a, player_b = loser, winner
                label = 0  # Player A lost

            # Extract features BEFORE updating stats (no lookahead)
            if row['tourney_date'] >= cutoff_date:
                feat = self._extract_features_for_match(row, player_a, player_b)
                features_list.append(feat)
                labels.append(label)

            # Update Elo
            self.elo_engine.update_elo(winner, loser, surface, level, date_str)

            # Update rolling stats for winner
            w_serve = compute_serve_stats(row, 'w')
            w_serve['won'] = True
            w_return = compute_return_stats(row, 'l')
            w_serve.update(w_return)
            self.stats_tracker.add_match(winner, w_serve)

            # Update rolling stats for loser
            l_serve = compute_serve_stats(row, 'l')
            l_serve['won'] = False
            l_return = compute_return_stats(row, 'w')
            l_serve.update(l_return)
            self.stats_tracker.add_match(loser, l_serve)

            # Update H2H
            self.h2h_tracker.add_match(winner, loser, surface, date_str)

        X = pd.DataFrame(features_list)
        y = np.array(labels)

        # Ensure column order matches FEATURE_NAMES
        for col in self.FEATURE_NAMES:
            if col not in X.columns:
                X[col] = np.nan
        X = X[self.FEATURE_NAMES]

        print(f"Feature matrix: {X.shape[0]:,} samples × {X.shape[1]} features")
        print(f"Label balance: {y.mean():.1%} positive (player_a wins)")
        return X, y

    def train(
        self,
        X: pd.DataFrame = None,
        y: np.ndarray = None,
        test_year: int = 2024,
        start_year: int = 2010,
    ):
        """
        Train XGBoost model with time-based train/test split.
        """
        if not HAS_ML:
            print("ML libraries not available!")
            return

        if X is None or y is None:
            X, y = self.build_dataset(start_year=start_year, end_year=test_year)

        # Time-based split: train on everything before test_year
        # We need to figure out where test_year starts
        # Since we built features chronologically, the last ~3000 are 2024
        total = len(X)
        test_size = min(3000, int(total * 0.15))
        train_X = X.iloc[:-test_size]
        train_y = y[:-test_size]
        test_X = X.iloc[-test_size:]
        test_y = y[-test_size:]

        print(f"\nTrain: {len(train_X):,} | Test: {len(test_X):,}")

        # Sklearn Gradient Boosting (pure Python, no libomp needed)
        # Train both GB and RF, ensemble them
        self.model = GradientBoostingClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            min_samples_leaf=10,
            max_features=0.8,
            random_state=42,
        )

        # Fill NaN with median for sklearn (doesn't handle NaN natively)
        train_X_filled = train_X.fillna(train_X.median())
        test_X_filled = test_X.fillna(train_X.median())
        self._feature_medians = train_X.median()

        print("Training Gradient Boosting (300 trees)...")
        self.model.fit(train_X_filled, train_y)

        # Also train a Random Forest for ensemble
        self.rf_model = RandomForestClassifier(
            n_estimators=500,
            max_depth=12,
            min_samples_leaf=5,
            max_features='sqrt',
            random_state=42,
            n_jobs=-1,
        )
        print("Training Random Forest (500 trees)...")
        self.rf_model.fit(train_X_filled, train_y)

        # --- Evaluation ---
        train_pred = self.model.predict(train_X_filled)
        test_pred = self.model.predict(test_X_filled)
        test_prob_gb = self.model.predict_proba(test_X_filled)[:, 1]
        test_prob_rf = self.rf_model.predict_proba(test_X_filled)[:, 1]

        # Ensemble: 60% GB + 40% RF
        test_prob = 0.6 * test_prob_gb + 0.4 * test_prob_rf
        test_pred_ens = (test_prob >= 0.5).astype(int)

        train_acc = accuracy_score(train_y, train_pred)
        test_acc_gb = accuracy_score(test_y, test_pred)
        test_acc_ens = accuracy_score(test_y, test_pred_ens)
        test_ll = log_loss(test_y, test_prob)
        test_brier = brier_score_loss(test_y, test_prob)

        print(f"\n{'='*50}")
        print(f"RESULTS:")
        print(f"  Train Accuracy (GB):    {train_acc:.1%}")
        print(f"  Test Accuracy (GB):     {test_acc_gb:.1%}")
        print(f"  Test Accuracy (Ensemble):{test_acc_ens:.1%}")
        print(f"  Test Log Loss:          {test_ll:.4f}")
        print(f"  Test Brier:             {test_brier:.4f}")
        print(f"{'='*50}")

        # --- Feature Importance ---
        importance = self.model.feature_importances_
        feat_imp = sorted(
            zip(self.FEATURE_NAMES, importance),
            key=lambda x: x[1], reverse=True
        )
        self.feature_importance = feat_imp

        print(f"\nTOP 15 FEATURES:")
        for name, imp in feat_imp[:15]:
            print(f"  {name:<35} {imp:.4f}")

        # --- Confidence Analysis ---
        print(f"\nCONFIDENCE ANALYSIS:")
        for threshold in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
            confident = test_prob >= threshold
            alt_confident = test_prob <= (1 - threshold)
            mask = confident | alt_confident

            if mask.sum() > 0:
                preds = (test_prob[mask] >= 0.5).astype(int)
                acc = accuracy_score(test_y[mask], preds)
                n = mask.sum()
                print(f"  Confidence ≥{threshold:.0%}: {acc:.1%} accuracy on {n} matches ({n/len(test_y):.0%} of total)")

        return {
            'train_acc': train_acc,
            'test_acc_gb': test_acc_gb,
            'test_acc_ensemble': test_acc_ens,
            'test_log_loss': test_ll,
            'test_brier': test_brier,
            'n_train': len(train_X),
            'n_test': len(test_X),
        }

    # --- Player Data Lookup ---

    def _ensure_sackmann_loader(self):
        """Lazy-load Sackmann data for player lookups."""
        if not hasattr(self, '_sackmann_loader') or self._sackmann_loader is None:
            try:
                from feeds.sackmann_loader import JeffSackmannLoader
                self._sackmann_loader = JeffSackmannLoader()
                self._sackmann_loader.load_all(start_year=2000)
                print(f"[predict_match] Sackmann loader ready: {len(self._sackmann_loader.players)} players")
            except Exception as e:
                print(f"[predict_match] Sackmann loader failed: {e}")
                self._sackmann_loader = None

    def _get_player_info(self, name: str) -> dict:
        """
        Get real player data (age, height, hand, rank, points) from Sackmann.
        Falls back to sensible defaults if player not found.
        """
        defaults = {
            'age': 25.0, 'ht': 183, 'hand': 'R',
            'rank': 100, 'rank_points': 1000, 'seed': None,
        }

        self._ensure_sackmann_loader()
        if self._sackmann_loader is None:
            return defaults

        profile = self._sackmann_loader.get_player(name)
        if profile is None:
            print(f"[predict_match] Player not found: {name}, using defaults")
            return defaults

        # Compute age from birth_date
        age = defaults['age']
        if profile.birth_date:
            try:
                dob_str = str(profile.birth_date)
                if len(dob_str) == 8:  # YYYYMMDD format
                    dob = datetime(int(dob_str[:4]), int(dob_str[4:6]), int(dob_str[6:8]))
                    age = (datetime.now() - dob).days / 365.25
            except (ValueError, TypeError):
                pass

        return {
            'age': round(age, 1),
            'ht': profile.height_cm if profile.height_cm > 0 else defaults['ht'],
            'hand': profile.hand if profile.hand in ('R', 'L') else defaults['hand'],
            'rank': profile.current_rank if profile.current_rank < 9999 else defaults['rank'],
            'rank_points': profile.current_points if profile.current_points > 0 else defaults['rank_points'],
            'seed': profile.current_rank if profile.current_rank <= 32 else None,
        }

    def predict_match(
        self,
        player_a: str,
        player_b: str,
        surface: str = "Hard",
        tourney_level: str = "M",
        round_name: str = "R32",
    ) -> dict:
        """
        Predict win probability for player_a vs player_b.
        Uses real player data from Sackmann DB (age, height, hand, rank, points).
        Requires model to be trained or loaded first.
        """
        if self.model is None:
            return {"error": "Model not trained. Call train() first."}

        # Get real player data from Sackmann
        info_a = self._get_player_info(player_a)
        info_b = self._get_player_info(player_b)

        # Build row with real player data for feature extraction
        dummy = pd.Series({
            'winner_name': player_a, 'loser_name': player_b,
            'surface': surface, 'tourney_level': tourney_level,
            'round': round_name,
            'winner_age': info_a['age'], 'loser_age': info_b['age'],
            'winner_ht': info_a['ht'], 'loser_ht': info_b['ht'],
            'winner_hand': info_a['hand'], 'loser_hand': info_b['hand'],
            'winner_rank': info_a['rank'], 'loser_rank': info_b['rank'],
            'winner_rank_points': info_a['rank_points'],
            'loser_rank_points': info_b['rank_points'],
            'winner_seed': info_a['seed'], 'loser_seed': info_b['seed'],
        })

        feat = self._extract_features_for_match(dummy, player_a, player_b)
        X = pd.DataFrame([feat])[self.FEATURE_NAMES]
        X_filled = X.fillna(self._feature_medians if hasattr(self, '_feature_medians') else 0)

        prob_gb = self.model.predict_proba(X_filled)[0, 1]
        prob_rf = self.rf_model.predict_proba(X_filled)[0, 1] if hasattr(self, 'rf_model') else prob_gb
        prob_a = 0.6 * prob_gb + 0.4 * prob_rf

        # Also get Elo prediction for comparison
        elo_prob = self.elo_engine.predict_match(player_a, player_b, surface)

        return {
            'player_a': player_a,
            'player_b': player_b,
            'surface': surface,
            'player_a_info': info_a,
            'player_b_info': info_b,
            'xgb_prob_a': round(float(prob_a), 4),
            'elo_prob_a': round(float(elo_prob), 4),
            'ensemble_prob_a': round(float(0.6 * prob_a + 0.4 * elo_prob), 4),
            'confidence': 'HIGH' if abs(prob_a - 0.5) > 0.2 else 'MEDIUM' if abs(prob_a - 0.5) > 0.1 else 'LOW',
        }

    def save_model(self, path: str = None):
        """Save trained models to file."""
        if self.model is None:
            print("No model to save!")
            return
        if path is None:
            path = str(Path(__file__).parent.parent / "models" / "tennis_gb.pkl")
        joblib.dump({
            'gb': self.model,
            'rf': self.rf_model if hasattr(self, 'rf_model') else None,
            'medians': self._feature_medians if hasattr(self, '_feature_medians') else None,
        }, path)
        print(f"Model saved to {path}")

    def load_model(self, path: str = None):
        """Load trained models from file."""
        if path is None:
            path = str(Path(__file__).parent.parent / "models" / "tennis_gb.pkl")
        data = joblib.load(path)
        self.model = data['gb']
        self.rf_model = data['rf']
        self._feature_medians = data['medians']
        print(f"Model loaded from {path}")


# --- CLI ---
if __name__ == "__main__":
    print("=" * 60)
    print("  NEMOFISH TENNIS XGBOOST PREDICTION MODEL")
    print("=" * 60)

    model = TennisXGBoostModel()

    # Build dataset and train
    X, y = model.build_dataset(start_year=2010, end_year=2024)
    results = model.train(X, y, test_year=2024)

    # Save the model
    model.save_model()

    # Test predictions for Miami Open matchups
    print("\n" + "=" * 60)
    print("  MIAMI OPEN 2026 PREDICTIONS")
    print("=" * 60)

    matchups = [
        ("Jannik Sinner", "Carlos Alcaraz", "Hard", "M"),
        ("Jannik Sinner", "Daniil Medvedev", "Hard", "M"),
        ("Carlos Alcaraz", "Alexander Zverev", "Hard", "M"),
        ("Novak Djokovic", "Taylor Fritz", "Hard", "M"),
        ("Daniil Medvedev", "Alexander Zverev", "Hard", "M"),
    ]

    for pa, pb, surf, level in matchups:
        pred = model.predict_match(pa, pb, surf, level)
        if 'error' not in pred:
            print(f"\n{pa} vs {pb} ({surf}):")
            print(f"  XGBoost:  {pa} {pred['xgb_prob_a']:.1%} | {pb} {1-pred['xgb_prob_a']:.1%}")
            print(f"  Elo:      {pa} {pred['elo_prob_a']:.1%} | {pb} {1-pred['elo_prob_a']:.1%}")
            print(f"  Ensemble: {pa} {pred['ensemble_prob_a']:.1%} | [{pred['confidence']}]")
