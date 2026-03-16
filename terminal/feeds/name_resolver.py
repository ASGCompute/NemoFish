"""
Tennis Player Name Resolver
============================
Bridges abbreviated names from api-tennis.com ("C. Dolehide")
to full names used in Elo/JeffSackmann databases ("Catherine Dolehide").

Strategy:
  1. Exact match (fastest)
  2. Last-name match + first initial check
  3. Fuzzy match (Levenshtein) on surname

Works with both Elo engine player names and JeffSackmann player DB.
"""

from typing import Dict, Optional, Tuple, Set
from difflib import SequenceMatcher
import re


class TennisNameResolver:
    """
    Resolves abbreviated player names to their full canonical form.
    
    Usage:
        resolver = TennisNameResolver()
        resolver.load_from_elo(elo_engine)      # Load known players from Elo DB
        resolver.load_from_sackmann(sackmann)    # Load from JeffSackmann (132K players)
        
        full = resolver.resolve("C. Dolehide")   # → "Catherine Dolehide"
        full = resolver.resolve("N. Djokovic")   # → "Novak Djokovic"
    """

    def __init__(self):
        # surname_lower → set of full names
        self._by_surname: Dict[str, Set[str]] = {}
        # full_name_lower → canonical name (preserves casing)
        self._canonical: Dict[str, str] = {}
        # Cache resolved lookups
        self._cache: Dict[str, str] = {}

    def add_player(self, full_name: str):
        """Register a player name."""
        if not full_name or len(full_name) < 2:
            return
        self._canonical[full_name.lower()] = full_name
        parts = full_name.strip().split()
        if parts:
            surname = parts[-1].lower()
            if surname not in self._by_surname:
                self._by_surname[surname] = set()
            self._by_surname[surname].add(full_name)

    def load_from_elo(self, elo_engine):
        """Load all player names from TennisEloEngine."""
        if hasattr(elo_engine, 'players'):
            for name in elo_engine.players:
                self.add_player(name)

    def load_from_sackmann(self, sackmann_loader):
        """Load all player names from JeffSackmannLoader."""
        if hasattr(sackmann_loader, 'players'):
            for name in sackmann_loader.players:
                self.add_player(name)

    def resolve(self, abbrev_name: str) -> str:
        """
        Resolve an abbreviated name to its full canonical form.
        
        Input examples:
            "C. Dolehide", "N. Djokovic", "J. Sinner", "Coco Gauff"
            "Alcaraz C.", "Sinner J.", "Djokovic N."  ← tennis-data.co.uk format
        
        Returns the best matching full name, or the input unchanged if no match.
        """
        if not abbrev_name:
            return abbrev_name

        # Check cache
        cache_key = abbrev_name.lower().strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 1. Exact match
        if cache_key in self._canonical:
            result = self._canonical[cache_key]
            self._cache[cache_key] = result
            return result

        # Parse the abbreviated name
        clean = abbrev_name.strip()
        parts = clean.split()

        if len(parts) < 2:
            self._cache[cache_key] = clean
            return clean

        # Detect format: "Alcaraz C." (reversed, tennis-data.co.uk) vs "C. Alcaraz" (normal)
        last_part = parts[-1].rstrip('.')
        first_part = parts[0].rstrip('.')
        
        if len(last_part) <= 2 and last_part[0].isupper():
            # Reversed format: "Alcaraz C." → surname is parts[0:-1], initial is last
            return self._resolve_reversed(clean, parts, cache_key)

        # Normal format: "C. Dolehide" → first_part="C.", surname="Dolehide"
        surname = parts[-1].lower()
        first_parts = parts[:-1]

        # 2. Surname match + initial check
        candidates = self._by_surname.get(surname, set())
        
        if not candidates:
            # Try without accents / with substitutions
            for stored_surname, names in self._by_surname.items():
                if self._surname_fuzzy_match(surname, stored_surname):
                    candidates = candidates.union(names)

        if candidates:
            # Try to match by first initial(s)
            first_initial = self._extract_initial(first_parts[0])
            
            if first_initial:
                initial_matches = []
                for full in candidates:
                    full_parts = full.split()
                    if full_parts:
                        cand_initial = full_parts[0][0].upper()
                        if cand_initial == first_initial.upper():
                            initial_matches.append(full)
                
                if len(initial_matches) == 1:
                    result = initial_matches[0]
                    self._cache[cache_key] = result
                    return result
                elif len(initial_matches) > 1:
                    # Multiple matches with same initial — use string similarity
                    best = max(initial_matches, 
                             key=lambda x: SequenceMatcher(None, clean.lower(), x.lower()).ratio())
                    self._cache[cache_key] = best
                    return best

            # If no initial match but only one candidate for surname
            if len(candidates) == 1:
                result = next(iter(candidates))
                self._cache[cache_key] = result
                return result

        # 3. Fuzzy match across all names (expensive, only used as fallback)
        best_match = None
        best_ratio = 0.0
        for canonical_lower, canonical in self._canonical.items():
            ratio = SequenceMatcher(None, cache_key, canonical_lower).ratio()
            if ratio > best_ratio and ratio > 0.6:
                best_ratio = ratio
                best_match = canonical

        if best_match:
            self._cache[cache_key] = best_match
            return best_match

        # Give up — return original
        self._cache[cache_key] = clean
        return clean

    def _resolve_reversed(self, clean: str, parts: list, cache_key: str) -> str:
        """
        Resolve reversed format: "Alcaraz C." or "De Minaur A." or "Auger-Aliassime F."
        
        Last part is the initial (e.g. "C."), everything before is the surname.
        """
        initial = parts[-1].rstrip('.')[0].upper()
        surname_parts = parts[:-1]
        
        # Try different surname constructions (handles multi-word surnames)
        # "De Minaur A." → surname="de minaur" or just "minaur"
        # "Van De Zandschulp B." → surname="zandschulp" 
        # "Auger-Aliassime F." → surname="auger-aliassime"
        
        candidates = set()
        
        # Strategy 1: Last word of surname parts  
        last_surname = surname_parts[-1].lower()
        if last_surname in self._by_surname:
            candidates.update(self._by_surname[last_surname])
        
        # Strategy 2: Full surname joined
        full_surname = " ".join(surname_parts).lower()
        for stored_surname, names in self._by_surname.items():
            if stored_surname == last_surname:
                continue
            # Check if any stored candidate has the full surname in their name
            for name in names:
                name_lower = name.lower()
                if full_surname in name_lower:
                    candidates.add(name)
        
        # Strategy 3: Fuzzy match on surname
        if not candidates:
            for stored_surname, names in self._by_surname.items():
                if self._surname_fuzzy_match(last_surname, stored_surname):
                    candidates.update(names)
        
        # Strategy 4: Hyphenated surnames
        if not candidates and '-' in last_surname:
            # "Auger-Aliassime" → try both parts
            for part in last_surname.split('-'):
                if part in self._by_surname:
                    candidates.update(self._by_surname[part])
        
        if candidates:
            # Filter by first initial  
            initial_matches = []
            for full_name in candidates:
                full_parts = full_name.split()
                if full_parts and full_parts[0][0].upper() == initial:
                    initial_matches.append(full_name)
            
            if len(initial_matches) == 1:
                result = initial_matches[0]
                self._cache[cache_key] = result
                return result
            elif len(initial_matches) > 1:
                # Score by surname similarity
                best = max(initial_matches,
                          key=lambda x: SequenceMatcher(
                              None, full_surname, x.lower()).ratio())
                self._cache[cache_key] = best
                return best
            
            # No initial match but only one candidate
            if len(candidates) == 1:
                result = next(iter(candidates))
                self._cache[cache_key] = result
                return result
        
        # Fallback: return original
        self._cache[cache_key] = clean
        return clean

    def resolve_bulk(self, names: list) -> dict:
        """Resolve a list of names. Returns dict of original → resolved."""
        return {name: self.resolve(name) for name in names}

    def get_match_stats(self, names: list) -> dict:
        """Get stats on how many names were resolved vs unresolved."""
        resolved = 0
        unresolved = 0
        for name in names:
            result = self.resolve(name)
            if result != name:
                resolved += 1
            else:
                unresolved += 1
        return {"resolved": resolved, "unresolved": unresolved, "total": len(names)}

    @staticmethod
    def _extract_initial(part: str) -> Optional[str]:
        """Extract first initial from 'C.' or 'C' or 'Carlos'."""
        clean = part.strip().rstrip('.')
        if clean:
            return clean[0]
        return None

    @staticmethod
    def _surname_fuzzy_match(a: str, b: str) -> bool:
        """Check if two surnames are likely the same (accent/spelling variants)."""
        if a == b:
            return True
        # Remove accents and compare
        a_clean = re.sub(r'[^a-z]', '', a.lower())
        b_clean = re.sub(r'[^a-z]', '', b.lower())
        if a_clean == b_clean:
            return True
        # Close enough
        if SequenceMatcher(None, a_clean, b_clean).ratio() > 0.85:
            return True
        return False

    @property
    def player_count(self) -> int:
        return len(self._canonical)


# === CLI Test ===
if __name__ == "__main__":
    resolver = TennisNameResolver()

    # Add known players
    test_players = [
        "Jannik Sinner", "Carlos Alcaraz", "Alexander Zverev",
        "Novak Djokovic", "Daniil Medvedev", "Taylor Fritz",
        "Andrey Rublev", "Casper Ruud", "Hubert Hurkacz",
        "Catherine Dolehide", "Donna Vekic", "Bianca Andreescu",
        "Coco Gauff", "Iga Swiatek", "Aryna Sabalenka",
        "Elena Rybakina", "Maria Timofeeva", "Jil Teichmann",
        "Linda Fruhvirtova", "Robin Sramkova", "Kaja Juvan",
        "Matteo Bellucci", "Nicolas Jarry", "Cristian Garin",
    ]
    for p in test_players:
        resolver.add_player(p)

    # Test resolution
    test_abbrevs = [
        "C. Dolehide", "N. Djokovic", "J. Sinner", "C. Alcaraz",
        "D. Vekic", "B. Andreescu", "I. Swiatek", "M. Timofeeva",
        "L. Fruhvirtova", "R. Sramkova", "K. Juvan",
        "M. Bellucci", "N. Jarry", "C. Garin",
        "Novak Djokovic",  # Already full name
        "Unknown Player",   # No match
    ]

    print("🎾 Name Resolution Test")
    print("-" * 50)
    for abbrev in test_abbrevs:
        full = resolver.resolve(abbrev)
        match = "✅" if full != abbrev else "❓"
        print(f"  {match} {abbrev:25} → {full}")
    print(f"\n  Players in DB: {resolver.player_count}")
