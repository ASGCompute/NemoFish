"""
Tennis Data Fetcher — 2025-2026 Match Data with Betting Odds
=============================================================
Downloads and converts match data from tennis-data.co.uk to
JeffSackmann-compatible CSV format for use with our Elo engine.

Source: www.tennis-data.co.uk (free, includes B365/Pinnacle/Max odds)
"""

import os
import subprocess
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional


DATA_DIR = Path(__file__).parent.parent / "data" / "tennis" / "tennis_data_uk"

# tennis-data.co.uk column mapping → JeffSackmann format
SURFACE_MAP = {"Hard": "Hard", "Clay": "Clay", "Grass": "Grass", "Carpet": "Carpet"}
LEVEL_MAP = {
    "Grand Slam": "G",
    "Masters 1000": "M",
    "Masters": "M",
    "ATP500": "A",
    "ATP250": "B",
    "International": "B",
    "International Gold": "A",
    "Tour Finals": "F",
}
ROUND_MAP = {
    "1st Round": "R128",
    "2nd Round": "R64",
    "3rd Round": "R32",
    "4th Round": "R16",
    "Quarterfinals": "QF",
    "Semifinals": "SF",
    "The Final": "F",
    "Round Robin": "RR",
}


def download_data(year: int) -> Path:
    """Download tennis-data.co.uk xlsx for a given year."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / f"tennis_data_{year}.xlsx"

    if output_path.exists():
        print(f"  ✓ {year} data already cached")
        return output_path

    url = f"http://www.tennis-data.co.uk/{year}/{year}.xlsx"
    print(f"  ⬇ Downloading {year} data from tennis-data.co.uk...")
    try:
        subprocess.run(
            ["curl", "-L", "-k", "-o", str(output_path), url],
            capture_output=True,
            timeout=30,
        )
        if output_path.exists() and output_path.stat().st_size > 1000:
            print(f"  ✓ Downloaded {output_path.stat().st_size:,} bytes")
            return output_path
        else:
            print(f"  ✗ Download failed or file too small")
            return None
    except Exception as e:
        print(f"  ✗ Error downloading: {e}")
        return None


# Global name resolver — loaded once, used for all conversions
_name_resolver = None

def _get_resolver():
    """Build name resolver from Elo DB (lazy-loaded, cached)."""
    global _name_resolver
    if _name_resolver is not None:
        return _name_resolver
    
    try:
        import sys
        terminal_dir = str(Path(__file__).parent.parent)
        if terminal_dir not in sys.path:
            sys.path.insert(0, terminal_dir)
        
        from feeds.name_resolver import TennisNameResolver
        from models.tennis_elo import TennisEloEngine
        
        data_dir = str(Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp")
        engine = TennisEloEngine(data_dir)
        engine.load_and_process(start_year=2000, end_year=2024)
        
        resolver = TennisNameResolver()
        for name in engine.ratings:
            resolver.add_player(name)
        
        _name_resolver = resolver
        print(f"  🔗 Name resolver loaded: {resolver.player_count} players")
        return resolver
    except Exception as e:
        print(f"  ⚠ Name resolver unavailable: {e}")
        import traceback
        traceback.print_exc()
        return None


def expand_name(abbreviated: str, resolver=None) -> str:
    """
    Convert abbreviated name (e.g., 'Sinner J.') to full format ('Jannik Sinner').
    Uses TennisNameResolver to bridge tennis-data.co.uk 'Lastname F.' format
    to JeffSackmann 'Firstname Lastname' format.
    """
    if not abbreviated or pd.isna(abbreviated):
        return str(abbreviated)
    name = str(abbreviated).strip()
    if resolver:
        return resolver.resolve(name)
    return name


def convert_to_sackmann_format(df: pd.DataFrame, year: int, resolver=None) -> pd.DataFrame:
    """
    Convert tennis-data.co.uk format to JeffSackmann-compatible format
    so our Elo engine can process it natively.
    Uses name resolver to convert 'Alcaraz C.' → 'Carlos Alcaraz'.
    """
    rows = []
    resolved_count = 0
    total_names = 0
    
    for _, row in df.iterrows():
        try:
            date = pd.to_datetime(row.get("Date"))
            tourney_date = int(date.strftime("%Y%m%d"))
        except:
            continue

        surface = SURFACE_MAP.get(row.get("Surface", "Hard"), "Hard")
        series = str(row.get("Series", "ATP250"))
        level = LEVEL_MAP.get(series, "B")
        round_name = ROUND_MAP.get(row.get("Round", ""), row.get("Round", ""))

        winner_raw = row.get("Winner", "")
        loser_raw = row.get("Loser", "")
        winner = expand_name(winner_raw, resolver)
        loser = expand_name(loser_raw, resolver)
        
        # Track resolution stats
        total_names += 2
        if winner != str(winner_raw).strip():
            resolved_count += 1
        if loser != str(loser_raw).strip():
            resolved_count += 1

        if not winner or winner == "nan" or not loser or loser == "nan":
            continue

        sackmann_row = {
            "tourney_id": f"{year}-{row.get('ATP', 0)}",
            "tourney_name": row.get("Tournament", row.get("Location", "")),
            "surface": surface,
            "tourney_level": level,
            "tourney_date": tourney_date,
            "winner_name": winner,
            "loser_name": loser,
            "winner_rank": row.get("WRank"),
            "loser_rank": row.get("LRank"),
            "winner_rank_points": row.get("WPts"),
            "loser_rank_points": row.get("LPts"),
            "round": round_name,
            "best_of": row.get("Best of", 3),
            "score": "",  # We don't need score for Elo
            # BETTING ODDS (key new data!)
            "odds_winner_b365": row.get("B365W"),
            "odds_loser_b365": row.get("B365L"),
            "odds_winner_ps": row.get("PSW"),  # Pinnacle
            "odds_loser_ps": row.get("PSL"),
            "odds_winner_max": row.get("MaxW"),
            "odds_loser_max": row.get("MaxL"),
            "odds_winner_avg": row.get("AvgW"),
            "odds_loser_avg": row.get("AvgL"),
        }
        rows.append(sackmann_row)

    if total_names > 0:
        print(f"  🔗 Names resolved: {resolved_count}/{total_names} ({resolved_count/total_names*100:.0f}%)")
    
    return pd.DataFrame(rows)


def load_year(year: int) -> pd.DataFrame:
    """Load and convert a single year of tennis-data.co.uk data."""
    xlsx_path = DATA_DIR / f"tennis_data_{year}.xlsx"

    # Try cached XLSX first
    if not xlsx_path.exists():
        xlsx_path = download_data(year)
        if not xlsx_path:
            return pd.DataFrame()

    try:
        df = pd.read_excel(xlsx_path, engine="openpyxl")
        resolver = _get_resolver()
        result = convert_to_sackmann_format(df, year, resolver)
        print(f"  📊 {year}: {len(result)} matches loaded (with odds)")
        return result
    except Exception as e:
        print(f"  ✗ Error processing {year}: {e}")
        return pd.DataFrame()


def load_all_recent(years=None) -> pd.DataFrame:
    """Load all recent years with odds data."""
    if years is None:
        years = [2025, 2026]

    all_data = []
    for year in years:
        df = load_year(year)
        if not df.empty:
            all_data.append(df)

    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        print(f"\n✅ Total: {len(combined)} matches with betting odds")
        return combined
    return pd.DataFrame()


def save_as_csv(years=None):
    """Save converted data as CSV in our data directory."""
    if years is None:
        years = [2025, 2026]

    output_dir = Path(__file__).parent.parent / "data" / "tennis" / "tennis_atp"

    for year in years:
        df = load_year(year)
        if df.empty:
            continue

        # Save main file (Elo compatible)
        output_path = output_dir / f"atp_matches_{year}.csv"
        cols_for_elo = [
            "tourney_id", "tourney_name", "surface", "tourney_level",
            "tourney_date", "winner_name", "loser_name", "winner_rank",
            "loser_rank", "round", "best_of", "score",
        ]
        df[cols_for_elo].to_csv(output_path, index=False)
        print(f"  ✅ Saved {output_path} ({len(df)} matches)")

        # Save odds file (for backtesting P&L)
        odds_path = output_dir / f"atp_odds_{year}.csv"
        df.to_csv(odds_path, index=False)
        print(f"  ✅ Saved {odds_path} (with betting odds)")


# --- CLI ---
if __name__ == "__main__":
    print("🎾 Tennis Data Fetcher — 2025-2026 with Betting Odds")
    print("=" * 55)

    # Download from tennis-data.co.uk if needed
    for year in [2025, 2026]:
        cached = DATA_DIR / f"tennis_data_{year}.xlsx"
        if not cached.exists():
            download_data(year)
        else:
            # Copy from /tmp if downloaded earlier
            tmp_path = Path(f"/tmp/tennis_{year}.xlsx")
            if tmp_path.exists() and not cached.exists():
                import shutil
                cached.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(tmp_path, cached)

    save_as_csv([2025, 2026])
    print("\n🎯 Data ready for Elo training + P&L backtesting!")
