"""Data structures and normalisation rules.

Everything here is pure: no network, no filesystem. That is what makes it testable.
"""

from dataclasses import dataclass, field

import re

from .categories import canonical_category


# --- Normalisation helpers -------------------------------------------------------

# "Paco Bagur, Freddy Córdoba e Iban José" -> ["Paco Bagur", "Freddy Córdoba", "Iban José"]
# Note the standalone y/e: "Agustín Díaz Yanes" must stay in one piece.
_MULTI_SEPARATOR = re.compile(r"\s+(?:y|e)\s+")
_WHITESPACE = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")

# Only what we have actually seen in the source. Anything unrecognised is kept as-is
# rather than guessed at.
COUNTRY_ALIASES = {
    "española": "España",
    "español": "España",
}


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace and return None for empty input."""
    if value is None:
        return None
    cleaned = _WHITESPACE.sub(" ", value).strip()
    return cleaned or None


def _split_multi(raw: str) -> list[str]:
    """Split a comma / slash / 'y' separated list into parts."""
    parts = []
    for chunk in raw.replace("/", ",").split(","):
        parts.extend(_MULTI_SEPARATOR.split(chunk))
    return [p.strip() for p in parts if p.strip()]


def _dedupe(items: list[str]) -> list[str]:
    """Remove duplicates, keeping the original order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def split_people(raw: str | None) -> list[str]:
    """Split a list of person names. Empty list when there is no value."""
    if not raw:
        return []
    return _dedupe(_split_multi(raw))


def parse_countries(raw: str | None) -> tuple[list[str], str | None]:
    """Return (normalised countries, original value).

    The original is always kept so the normalisation stays auditable.
    """
    if not raw:
        return [], None
    original = clean_text(raw)
    countries = [
        COUNTRY_ALIASES.get(c.lower(), c) for c in _split_multi(raw)
    ]
    return _dedupe(countries), original


def parse_duration(raw: str | None) -> int | None:
    """'105 minutos' -> 105. None when there is no value."""
    if not raw:
        return None
    match = _DIGITS.search(raw)
    return int(match.group()) if match else None


# --- Structures ------------------------------------------------------------------

# Where the data comes from. Kept here because it is a fact about the data, not
# about the transport, and http_client imports it instead of duplicating it.
SITE_URL = "https://www.premiosgoya.com"

# detail_status values. They answer "did we get this film's page?", which is a
# different question from "was the field empty on the page?".
DETAIL_OK = "ok"
DETAIL_NOT_FOUND = "not_found"
DETAIL_ERROR = "error"


@dataclass
class Nomination:
    """One row of a category: a movie competing for one award.

    category is the canonical name; category_raw is what the site said that year.
    Both are kept so the canonical mapping stays auditable (ADR-009).
    """

    edition: int
    ceremony_year: int
    category: str
    credited: list[str]
    won: bool
    note: str | None = None
    category_raw: str = ""

    def __post_init__(self) -> None:
        if not self.category_raw:
            self.category_raw = self.category

    def to_dict(self) -> dict:
        return {
            "edition": self.edition,
            "ceremony_year": self.ceremony_year,
            "category": self.category,
            "category_raw": self.category_raw,
            "credited": self.credited,
            "won": self.won,
            "note": self.note,
        }


@dataclass
class Credits:
    # producers_raw is a string on purpose: company names contain commas
    # ("Alba Sotorra, S.L."), so splitting them would invent data. See ADR-008.
    directors: list[str] = field(default_factory=list)
    screenwriters: list[str] = field(default_factory=list)
    cast: list[str] = field(default_factory=list)
    producers_raw: str | None = None

    def to_dict(self) -> dict:
        return {
            "directors": self.directors,
            "screenwriters": self.screenwriters,
            "cast": self.cast,
            "producers_raw": self.producers_raw,
        }


def make_nomination(
    edition: int,
    ceremony_year: int,
    category: str,
    credited: list[str],
    won: bool,
    note: str | None = None,
) -> Nomination:
    """Build a Nomination with the canonical category name filled in."""
    return Nomination(
        edition=edition,
        ceremony_year=ceremony_year,
        category=canonical_category(category),
        credited=credited,
        won=won,
        note=note,
        category_raw=category,
    )


@dataclass
class Movie:
    """A film, with everything the source tells us about it.

    title is optional because a film can be nominated on a page we never managed
    to fetch. Losing its nominations would be worse than having no title, so the
    record is kept and detail_status says what happened.
    """

    slug: str
    title: str | None = None
    title_original: str | None = None
    synopsis: str | None = None
    countries: list[str] = field(default_factory=list)
    countries_raw: str | None = None
    duration_minutes: int | None = None
    credits: Credits = field(default_factory=Credits)

    # Counters the Academy publishes on the page itself, used to cross-check our
    # own numbers. Only meaningful when detail_status is "ok".
    reported_nominations: int = 0
    reported_awards: int = 0
    # The categories that page claims were won. Lets the validator say *which*
    # award is disputed, not just that the totals differ.
    reported_award_categories: list[str] | None = None

    detail_status: str = DETAIL_OK
    missing_fields: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    nominations: list[Nomination] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"{SITE_URL}/pelicula/{self.slug}/"

    @property
    def editions(self) -> list[int]:
        seen: list[int] = []
        for nomination in self.nominations:
            if nomination.edition not in seen:
                seen.append(nomination.edition)
        return sorted(seen)

    @property
    def total_nominations(self) -> int:
        return len(self.nominations)

    @property
    def total_awards(self) -> int:
        return sum(1 for n in self.nominations if n.won)

    @property
    def distinct_categories(self) -> int:
        return len({n.category for n in self.nominations})

    def categories(self) -> set[str]:
        return {n.category for n in self.nominations}

    def to_dict(self) -> dict:
        """The shape written to data/movies.json. Key order is meaningful."""
        return {
            "slug": self.slug,
            "url": self.url,
            "title": self.title,
            "title_original": self.title_original,
            "synopsis": self.synopsis,
            "countries": self.countries,
            "countries_raw": self.countries_raw,
            "duration_minutes": self.duration_minutes,
            "credits": self.credits.to_dict(),
            "goya": {
                "editions": self.editions,
                "total_nominations": self.total_nominations,
                "total_awards": self.total_awards,
                "nominations": [n.to_dict() for n in self.nominations],
            },
            "data_quality": {
                "detail_status": self.detail_status,
                # None when we never got the page, so that a failed fetch is not
                # mistaken for "the site says zero".
                "reported_by_source": (
                    {
                        "nominations": self.reported_nominations,
                        "awards": self.reported_awards,
                        "award_categories": (
                            None
                            if self.reported_award_categories is None
                            else list(self.reported_award_categories)
                        ),
                    }
                    if self.detail_status == DETAIL_OK
                    else None
                ),
                "missing_fields": self.missing_fields,
                "issues": self.issues,
            },
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Movie":
        """Rebuild a Movie from data/movies.json.

        Needed so that an incremental run can merge new editions into films that
        were scraped earlier. The key names line up with the dataclass fields, so
        Nomination(**row) and Credits(**row) work directly.

        Strict about structure, tolerant about values: `slug` and `goya.nominations`
        must be present, because a record missing them is broken and quietly
        treating it as "no nominations" would hide that. Optional fields fall
        back to their defaults.
        """
        quality = payload.get("data_quality") or {}
        reported = quality.get("reported_by_source") or {}

        movie = cls(
            slug=payload["slug"],
            title=payload.get("title"),
            title_original=payload.get("title_original"),
            synopsis=payload.get("synopsis"),
            countries=list(payload.get("countries") or []),
            countries_raw=payload.get("countries_raw"),
            duration_minutes=payload.get("duration_minutes"),
            credits=Credits(**(payload.get("credits") or {})),
            reported_nominations=reported.get("nominations", 0),
            reported_awards=reported.get("awards", 0),
            reported_award_categories=(
                list(reported["award_categories"])
                if reported.get("award_categories") is not None
                else None
            ),
            detail_status=quality.get("detail_status", DETAIL_OK),
            missing_fields=list(quality.get("missing_fields") or []),
            issues=list(quality.get("issues") or []),
        )
        movie.nominations = [
            Nomination(**row) for row in payload["goya"]["nominations"]
        ]
        return movie