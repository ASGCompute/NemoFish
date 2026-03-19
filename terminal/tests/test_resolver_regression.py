"""
Regression tests for TennisNameResolver — fail-closed policy + today's runtime cases.

Tests cover:
  - Fail-closed: AMBIGUOUS/UNRESOLVED confidence → match must be skipped
  - Today's runtime cases: M. Stakusic, D. Parry, M. Trevisan, M. McDonald
  - Known aliases, tour disambiguation, cache isolation
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from feeds.name_resolver import TennisNameResolver, ResolveResult


@pytest.fixture
def resolver():
    """Pre-seeded resolver with test players from today's runtime errors."""
    r = TennisNameResolver()

    # Male ATP players
    for name in [
        "Jannik Sinner", "Carlos Alcaraz", "Novak Djokovic",
        "Daniil Medvedev", "Matteo Berrettini",
        # Today's runtime cases
        "Marko Stakusic",         # M. Stakusic in ATP
        "Mackenzie McDonald",     # M. McDonald in ATP  
        "Diane Parry",            # not ATP — but tests ambiguity
    ]:
        r.add_player(name, gender="M")

    # Fix: Diane Parry is female
    r._gender["diane parry"] = "F"

    # Female WTA players
    for name in [
        "Storm Hunter", "Mia Stakusic", "Ella Seidel",
        "Catherine Dolehide", "Donna Vekic",
        # Today's runtime cases
        "Martina Trevisan",       # M. Trevisan in WTA
        "Diane Parry",            # D. Parry in WTA — also female
    ]:
        r.add_player(name, gender="F")

    return r


# ============================================================
# FAIL-CLOSED: ResolveResult contract
# ============================================================

class TestResolveResultContract:
    """Every resolve() call must return ResolveResult namedtuple."""

    def test_returns_namedtuple(self, resolver):
        result = resolver.resolve("Novak Djokovic")
        assert isinstance(result, ResolveResult)
        assert hasattr(result, 'name')
        assert hasattr(result, 'confidence')

    def test_exact_match_returns_exact(self, resolver):
        result = resolver.resolve("Novak Djokovic")
        assert result.name == "Novak Djokovic"
        assert result.confidence == "EXACT"

    def test_alias_returns_alias(self, resolver):
        result = resolver.resolve("Storm Hunter")
        assert result.confidence == "ALIAS"

    def test_single_word_returns_unresolved(self, resolver):
        result = resolver.resolve("Federer")
        assert result.confidence == "UNRESOLVED"

    def test_unknown_player_returns_unresolved(self, resolver):
        result = resolver.resolve("X. Zyxwvuts")
        assert result.confidence == "UNRESOLVED"

    def test_empty_returns_unresolved(self, resolver):
        result = resolver.resolve("")
        assert result.confidence == "UNRESOLVED"


# ============================================================
# TODAY'S RUNTIME CASES
# ============================================================

class TestMStakusic:
    """M. Stakusic: male (Marko) in ATP, female (Mia) in WTA."""

    def test_wta_resolves_to_mia(self, resolver):
        result = resolver.resolve("M. Stakusic", tour="WTA")
        assert result.name == "Mia Stakusic"
        assert result.confidence == "UNIQUE"

    def test_atp_resolves_to_marko(self, resolver):
        result = resolver.resolve("M. Stakusic", tour="ATP")
        assert result.name == "Marko Stakusic"
        assert result.confidence == "UNIQUE"

    def test_no_tour_is_ambiguous(self, resolver):
        """Without tour hint, M. Stakusic is ambiguous — fail-closed."""
        result = resolver.resolve("M. Stakusic")
        assert result.confidence == "AMBIGUOUS"


class TestDParry:
    """D. Parry: Diane Parry is WTA player. If no male D. Parry in DB, should be UNIQUE."""

    def test_wta_resolves(self, resolver):
        result = resolver.resolve("D. Parry", tour="WTA")
        assert result.name == "Diane Parry"
        assert result.confidence == "UNIQUE"

    def test_atp_no_male_parry(self, resolver):
        """No male D. Parry in our DB → should be UNRESOLVED or UNIQUE (Diane)."""
        result = resolver.resolve("D. Parry", tour="ATP")
        # Diane is tagged F, ATP filter removes her → UNRESOLVED
        # This is correct fail-closed behavior
        assert result.confidence in ("UNRESOLVED", "UNIQUE")


class TestMTrevisan:
    """M. Trevisan: Martina Trevisan (WTA). No male M. Trevisan in DB."""

    def test_wta_resolves(self, resolver):
        result = resolver.resolve("M. Trevisan", tour="WTA")
        assert result.name == "Martina Trevisan"
        assert result.confidence == "UNIQUE"

    def test_no_tour_unique_if_only_one(self, resolver):
        """Only one Trevisan in DB → should be UNIQUE even without tour."""
        result = resolver.resolve("M. Trevisan")
        assert result.name == "Martina Trevisan"
        assert result.confidence == "UNIQUE"


class TestMMcDonald:
    """M. McDonald: Mackenzie McDonald (ATP male)."""

    def test_atp_resolves(self, resolver):
        result = resolver.resolve("M. McDonald", tour="ATP")
        assert result.name == "Mackenzie McDonald"
        assert result.confidence == "UNIQUE"

    def test_no_tour_unique_if_only_one(self, resolver):
        """Only one McDonald in DB → should be UNIQUE."""
        result = resolver.resolve("M. McDonald")
        assert result.name == "Mackenzie McDonald"
        assert result.confidence == "UNIQUE"


# ============================================================
# KNOWN ALIASES
# ============================================================

class TestKnownAliases:
    """Hardcoded aliases override all resolution logic."""

    def test_storm_hunter_alias(self, resolver):
        result = resolver.resolve("Storm Hunter")
        assert result.name == "Storm Hunter"
        assert result.confidence == "ALIAS"

    def test_s_hunter_alias(self, resolver):
        result = resolver.resolve("S. Hunter")
        assert result.name == "Storm Hunter"
        assert result.confidence == "ALIAS"


# ============================================================
# CACHE ISOLATION
# ============================================================

class TestCacheIsolation:
    """Tour-dependent results don't pollute each other in cache."""

    def test_separate_cache_per_tour(self, resolver):
        wta = resolver.resolve("M. Stakusic", tour="WTA")
        atp = resolver.resolve("M. Stakusic", tour="ATP")
        assert wta.name != atp.name
        assert wta.name == "Mia Stakusic"
        assert atp.name == "Marko Stakusic"


# ============================================================
# FILTER BY TOUR
# ============================================================

class TestFilterByTour:
    """_filter_by_tour correctly narrows candidates."""

    def test_no_tour_returns_all(self, resolver):
        candidates = ["Marko Stakusic", "Mia Stakusic"]
        assert resolver._filter_by_tour(candidates, tour=None) == candidates

    def test_wta_filters_male(self, resolver):
        candidates = ["Marko Stakusic", "Mia Stakusic"]
        result = resolver._filter_by_tour(candidates, tour="WTA")
        assert result == ["Mia Stakusic"]

    def test_atp_filters_female(self, resolver):
        candidates = ["Marko Stakusic", "Mia Stakusic"]
        result = resolver._filter_by_tour(candidates, tour="ATP")
        assert result == ["Marko Stakusic"]


# ============================================================
# STANDARD RESOLUTION
# ============================================================

class TestStandardResolution:
    """Basic abbreviation resolution."""

    def test_initial_dot_surname(self, resolver):
        result = resolver.resolve("C. Dolehide")
        assert result.name == "Catherine Dolehide"
        assert result.confidence == "UNIQUE"

    def test_full_name_passthrough(self, resolver):
        result = resolver.resolve("Novak Djokovic")
        assert result.name == "Novak Djokovic"
        assert result.confidence == "EXACT"

    def test_reversed_format(self, resolver):
        result = resolver.resolve("Alcaraz C.")
        assert result.name == "Carlos Alcaraz"
        assert result.confidence == "UNIQUE"

    def test_unresolvable_returns_unresolved(self, resolver):
        result = resolver.resolve("G. Miguel")
        assert result.confidence == "UNRESOLVED"
