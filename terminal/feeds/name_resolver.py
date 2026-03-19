"""
Tennis Player Name Resolver
============================
Bridges abbreviated names from api-tennis.com ("C. Dolehide")
to full names used in Elo/JeffSackmann databases ("Catherine Dolehide").

Fail-closed policy:
  - If resolution is ambiguous (multiple candidates after tour filter),
    returns AMBIGUOUS confidence → match must be skipped.
  - If no match found at all, returns UNRESOLVED confidence.

Strategy:
  1. Known aliases (hardcoded corrections)
  2. Exact match (fastest)
  3. Last-name match + first initial check + tour/gender filtering
  4. Fuzzy match (Levenshtein) on surname — only if unique result

Works with both Elo engine player names and JeffSackmann player DB.
"""

from collections import namedtuple

from typing import Dict, Optional, Set
from difflib import SequenceMatcher
import re

# Confidence levels for resolution results
ResolveResult = namedtuple('ResolveResult', ['name', 'confidence'])


class TennisNameResolver:
    """
    Resolves abbreviated player names to their full canonical form.
    
    Usage:
        resolver = TennisNameResolver()
        resolver.load_from_elo(elo_engine)
        
        full = resolver.resolve("C. Dolehide")                    # → "Catherine Dolehide"
        full = resolver.resolve("M. Stakusic", tour="WTA")        # → prefers female player
    """

    # Known aliases: abbreviation patterns that cause wrong matches.
    # Maps lowercased abbrev → correct full name.
    _KNOWN_ALIASES = {
        "storm hunter": "Storm Hunter",
        "s. hunter": "Storm Hunter",
    }

    # Gender classification for tour-aware disambiguation.
    # Built from Sackmann data or manually seeded.
    # tour_key: "atp" = male, "wta" = female
    _FEMALE_NAMES = {
        "storm hunter", "mia stakusic", "ella seidel", "susan bandecchi",
        "linda fruhvirtova", "robin sramkova", "martina trevisan",
        "kaja juvan", "catherine dolehide", "donna vekic",
        "bianca andreescu", "coco gauff", "iga swiatek",
        "aryna sabalenka", "elena rybakina", "maria timofeeva",
        "jil teichmann", "venus williams", "ajla tomljanovic",
        "kamilla rakhimova", "oksana selekhmeteva",
        "leolia jeanjean", "madison brengle", "ashlyn krueger",
        "caty mcnally", "katie volynets", "priscilla hon",
        "victoria jimenez kasintseva", "reese brantmeier",
        "yue yuan", "varvara lepchenko",
    }

    def __init__(self):
        # surname_lower → set of full names
        self._by_surname: Dict[str, Set[str]] = {}
        # full_name_lower → canonical name (preserves casing)
        self._canonical: Dict[str, str] = {}
        # Cache resolved lookups
        self._cache: Dict[str, str] = {}
        # Gender hints: full_name_lower → "M" | "F" | None
        self._gender: Dict[str, str] = {}

    def add_player(self, full_name: str, gender: str = None):
        """Register a player name with optional gender hint ('M' or 'F')."""
        if not full_name or len(full_name) < 2:
            return
        self._canonical[full_name.lower()] = full_name
        parts = full_name.strip().split()
        if parts:
            surname = parts[-1].lower()
            if surname not in self._by_surname:
                self._by_surname[surname] = set()
            self._by_surname[surname].add(full_name)
        # Store gender hint
        if gender:
            self._gender[full_name.lower()] = gender.upper()
        elif full_name.lower() in self._FEMALE_NAMES:
            self._gender[full_name.lower()] = "F"

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

    def resolve(self, abbrev_name: str, tour: str = None) -> ResolveResult:
        """
        Resolve an abbreviated name to its full canonical form.
        
        Args:
            abbrev_name: e.g. "C. Dolehide", "Alcaraz C.", "Coco Gauff"
            tour: optional "ATP" or "WTA" for gender-aware disambiguation
        
        Returns ResolveResult(name, confidence):
          - EXACT/ALIAS/UNIQUE → safe to use
          - AMBIGUOUS/UNRESOLVED → match should be skipped (fail-closed)
        """
        if not abbrev_name:
            return ResolveResult(abbrev_name, 'UNRESOLVED')

        # Check known aliases first
        alias_key = abbrev_name.lower().strip()
        if alias_key in self._KNOWN_ALIASES:
            return ResolveResult(self._KNOWN_ALIASES[alias_key], 'ALIAS')

        # Check cache (include tour in key for gender-dependent results)
        cache_key = f"{alias_key}|{tour or ''}" 
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 1. Exact match
        if alias_key in self._canonical:
            result = ResolveResult(self._canonical[alias_key], 'EXACT')
            self._cache[cache_key] = result
            return result

        # Parse the abbreviated name
        clean = abbrev_name.strip()
        parts = clean.split()

        if len(parts) < 2:
            result = ResolveResult(clean, 'UNRESOLVED')
            self._cache[cache_key] = result
            return result

        # Detect format: "Alcaraz C." (reversed) vs "C. Alcaraz" (normal)
        last_part = parts[-1].rstrip('.')
        first_part = parts[0].rstrip('.')
        
        if len(last_part) <= 2 and last_part[0].isupper():
            # Reversed format: "Alcaraz C." → surname is parts[0:-1], initial is last
            return self._resolve_reversed(clean, parts, cache_key, tour)

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
                
                # Apply tour/gender filter when ambiguous
                initial_matches = self._filter_by_tour(initial_matches, tour)
                
                if len(initial_matches) == 1:
                    result = ResolveResult(initial_matches[0], 'UNIQUE')
                    self._cache[cache_key] = result
                    return result
                elif len(initial_matches) > 1:
                    # FAIL-CLOSED: ambiguous — multiple candidates survive
                    result = ResolveResult(clean, 'AMBIGUOUS')
                    self._cache[cache_key] = result
                    return result

            # If no initial match but only one candidate for surname
            filtered = self._filter_by_tour(list(candidates), tour)
            if len(filtered) == 1:
                result = ResolveResult(filtered[0], 'UNIQUE')
                self._cache[cache_key] = result
                return result
            elif len(filtered) > 1:
                result = ResolveResult(clean, 'AMBIGUOUS')
                self._cache[cache_key] = result
                return result

        # 3. Fuzzy match across all names (expensive, only used as fallback)
        best_match = None
        best_ratio = 0.0
        second_ratio = 0.0
        for canonical_lower, canonical in self._canonical.items():
            ratio = SequenceMatcher(None, alias_key, canonical_lower).ratio()
            if ratio > best_ratio and ratio > 0.6:
                second_ratio = best_ratio
                best_ratio = ratio
                best_match = canonical
            elif ratio > second_ratio:
                second_ratio = ratio

        # Only accept fuzzy match if clearly dominant (>0.1 gap to second)
        if best_match and (best_ratio - second_ratio) > 0.1:
            result = ResolveResult(best_match, 'UNIQUE')
            self._cache[cache_key] = result
            return result
        elif best_match:
            # Too close to call — AMBIGUOUS
            result = ResolveResult(clean, 'AMBIGUOUS')
            self._cache[cache_key] = result
            return result

        # FAIL-CLOSED: nothing found
        result = ResolveResult(clean, 'UNRESOLVED')
        self._cache[cache_key] = result
        return result

    def _resolve_reversed(self, clean: str, parts: list, cache_key: str, tour: str = None) -> ResolveResult:
        """
        Resolve reversed format: "Alcaraz C." or "De Minaur A."
        """
        initial = parts[-1].rstrip('.')[0].upper()
        surname_parts = parts[:-1]
        
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
            
            # Apply tour/gender filter
            initial_matches = self._filter_by_tour(initial_matches, tour)
            
            if len(initial_matches) == 1:
                result = ResolveResult(initial_matches[0], 'UNIQUE')
                self._cache[cache_key] = result
                return result
            elif len(initial_matches) > 1:
                # FAIL-CLOSED: ambiguous
                result = ResolveResult(clean, 'AMBIGUOUS')
                self._cache[cache_key] = result
                return result
            
            # No initial match but only one candidate
            filtered = self._filter_by_tour(list(candidates), tour)
            if len(filtered) == 1:
                result = ResolveResult(filtered[0], 'UNIQUE')
                self._cache[cache_key] = result
                return result
            elif len(filtered) > 1:
                result = ResolveResult(clean, 'AMBIGUOUS')
                self._cache[cache_key] = result
                return result
        
        # Fallback: UNRESOLVED
        result = ResolveResult(clean, 'UNRESOLVED')
        self._cache[cache_key] = result
        return result

    def resolve_bulk(self, names: list, tour: str = None) -> dict:
        """Resolve a list of names. Returns dict of original → ResolveResult."""
        return {name: self.resolve(name, tour=tour) for name in names}

    def get_match_stats(self, names: list, tour: str = None) -> dict:
        """Get stats on how many names were resolved vs unresolved."""
        resolved = 0
        unresolved = 0
        ambiguous = 0
        for name in names:
            result = self.resolve(name, tour=tour)
            if result.confidence in ('EXACT', 'ALIAS', 'UNIQUE'):
                resolved += 1
            elif result.confidence == 'AMBIGUOUS':
                ambiguous += 1
            else:
                unresolved += 1
        return {"resolved": resolved, "unresolved": unresolved, "ambiguous": ambiguous, "total": len(names)}

    @staticmethod
    def _extract_initial(part: str) -> Optional[str]:
        """Extract first initial from 'C.' or 'C' or 'Carlos'."""
        clean = part.strip().rstrip('.')
        if clean:
            return clean[0]
        return None

    def _filter_by_tour(self, candidates: list, tour: str = None) -> list:
        """Filter candidates by tour/gender when ambiguous.
        
        ATP → prefer male players, WTA → prefer female players.
        Only filters when there are multiple candidates and tour is specified.
        """
        if not tour or len(candidates) <= 1:
            return candidates
        
        expected_gender = "M" if "atp" in tour.lower() else "F"
        
        filtered = []
        for name in candidates:
            gender = self._gender.get(name.lower())
            if gender is None:
                # Unknown gender — keep (don't filter out)
                filtered.append(name)
            elif gender == expected_gender:
                filtered.append(name)
        
        # If filtering removed everything, return original candidates
        return filtered if filtered else candidates

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
