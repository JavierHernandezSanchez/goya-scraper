"""Parse a movie page.

Pure function: HTML in, data out. No network, no filesystem.
"""

import logging

from bs4 import BeautifulSoup

from .model import Credits, Movie, clean_text, parse_countries, parse_duration, split_people

log = logging.getLogger(__name__)

SELECTOR_ARTICLE = "article.pelicula"
SELECTOR_TITLE = ".pelicula__header__titulo h1"
SELECTOR_SYNOPSIS = ".pelicula__header__sinopsis"
SELECTOR_NOMINATIONS_COUNT = ".pelicula__header__premios--nominaciones span"
SELECTOR_AWARDS_COUNT = ".pelicula__header__premios--goyas span"

# The page also carries a list of the awards the film won. It mostly agrees with
# the edition pages, but not always, and when it does not, knowing *which*
# category differs is what makes the conflict explainable.
SELECTOR_AWARDS_SECTION = "section.pelicula__premios--goyas"
SELECTOR_AWARD_CATEGORY = "h3.pelicula__premio__categoria"

# The definition list uses dt/dd pairs, so new fields need no selector changes.
# The Spanish labels are what we key on; see docs/data-model.md.
LABEL_COUNTRIES = "Nacionalidad"
LABEL_DIRECTORS = "Dirección"
LABEL_SCREENWRITERS = "Guion"
LABEL_PRODUCERS = "Producción"
LABEL_CAST = "Intérpretes"
LABEL_TITLE_ORIGINAL = "Título original"
LABEL_DURATION = "Duración"

# Schema fields we expect to be able to fill. Used to build missing_fields.
EXPECTED_FIELDS = (
    "title_original",
    "synopsis",
    "countries",
    "duration_minutes",
)


class NotAMoviePageError(ValueError):
    """The HTML is not a movie page."""


def _read_definition_list(article) -> dict[str, str | None]:
    """Turn every <dt>/<dd> pair into a label -> value mapping."""
    fields = {}
    for row in article.select("dl > div"):
        label = row.select_one("dt")
        value = row.select_one("dd")
        if not label or not value:
            continue
        fields[clean_text(label.get_text())] = clean_text(value.get_text(" "))
    return fields


def _read_count(article, selector: str) -> int:
    """Read one of the counters the page publishes for itself.

    The awards counter is omitted entirely when the movie won nothing, so a
    missing element means zero, not unknown.
    """
    tag = article.select_one(selector)
    if not tag:
        return 0
    digits = "".join(ch for ch in tag.get_text() if ch.isdigit())
    return int(digits) if digits else 0


def _read_award_categories(article) -> list[str]:
    """Read the categories the page claims this film won.

    Empty when the page has no awards section, which is how a film with zero
    awards looks: the whole block is omitted, not listed as empty.
    """
    section = article.select_one(SELECTOR_AWARDS_SECTION)
    if not section:
        return []
    return [
        clean_text(tag.get_text())
        for tag in section.select(SELECTOR_AWARD_CATEGORY)
        if clean_text(tag.get_text())
    ]


def parse_movie(html: str, slug: str) -> Movie:
    """Parse a movie page into a Movie.

    Raises NotAMoviePageError when the HTML is not a movie page (e.g. a 404).
    """
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one(SELECTOR_ARTICLE)
    if not article:
        raise NotAMoviePageError(f"no {SELECTOR_ARTICLE} in the page for /pelicula/{slug}/")

    title_tag = article.select_one(SELECTOR_TITLE)
    title = clean_text(title_tag.get_text()) if title_tag else None
    if not title:
        raise NotAMoviePageError(f"movie page without a title for /pelicula/{slug}/")

    fields = _read_definition_list(article)
    countries, countries_raw = parse_countries(fields.get(LABEL_COUNTRIES))

    synopsis_tag = article.select_one(SELECTOR_SYNOPSIS)

    movie = Movie(
        slug=slug,
        title=title,
        title_original=fields.get(LABEL_TITLE_ORIGINAL),
        synopsis=clean_text(synopsis_tag.get_text(" ")) if synopsis_tag else None,
        countries=countries,
        countries_raw=countries_raw,
        duration_minutes=parse_duration(fields.get(LABEL_DURATION)),
        credits=Credits(
            directors=split_people(fields.get(LABEL_DIRECTORS)),
            screenwriters=split_people(fields.get(LABEL_SCREENWRITERS)),
            cast=split_people(fields.get(LABEL_CAST)),
            producers_raw=fields.get(LABEL_PRODUCERS),
        ),
        reported_nominations=_read_count(article, SELECTOR_NOMINATIONS_COUNT),
        reported_awards=_read_count(article, SELECTOR_AWARDS_COUNT),
        reported_award_categories=(
            _read_award_categories(article)
            if _read_count(article, SELECTOR_AWARDS_COUNT)
            else None
        ),
    )

    movie.missing_fields = [
        name for name in EXPECTED_FIELDS if getattr(movie, name) in (None, [])
    ]
    return movie