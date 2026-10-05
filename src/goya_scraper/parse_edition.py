"""Parse a Goya edition nominations page.

Pure function: HTML in, data out. No network, no filesystem.
"""

import logging
import re

from bs4 import BeautifulSoup

from .model import Nomination, clean_text, make_nomination, split_people

log = logging.getLogger(__name__)

# Verified against all 40 editions. See docs/sources.md.
SELECTOR_CATEGORY = "section.categoria-de-peliculas"
SELECTOR_CATEGORY_NAME = "h1.categoria-de-peliculas__titulo"
SELECTOR_ROW = "li.lista-de-peliculas__pelicula"

# The poster link always points at the movie, while the h2 text is the credited
# person. Using the h2 text as the title would give us 1678 "directors".
SELECTOR_MOVIE_LINK = "div.lista-de-peliculas__cartel a[href]"
SELECTOR_CREDITED = "h2.lista-de-peliculas__titulo a"
SELECTOR_NOTE = "div.lista-de-peliculas__texto p"

# The winner marker is a decorative image whose title says so in plain text.
# Must be scoped to the row, or any marker on the page would pollute the result.
SELECTOR_WINNER = 'img[title^="Ganadora"]'

# On the home page the site lists every edition with its ceremony year.
SELECTOR_EDITION_LINK = "ol.lista-anios__lista a[href]"
EDITION_HREF = re.compile(r"^/(\d+)-edicion/$")


def parse_editions_index(html: str) -> list[tuple[int, int]]:
    """Read (edition, ceremony_year) pairs from the home page.

    The year is read, never calculated, even though `year == edition + 1986`
    holds for all 40 editions. Reading costs nothing and stays correct if the
    Academy ever breaks the pattern.

    Returns a list sorted by edition.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: dict[int, int] = {}

    for link in soup.select(SELECTOR_EDITION_LINK):
        match = EDITION_HREF.match(link.get("href", "").strip())
        if not match:
            continue
        year_text = clean_text(link.get_text())
        if not year_text or not year_text.isdigit():
            log.warning("edition %s has no usable year, skipped", match.group(1))
            continue
        found[int(match.group(1))] = int(year_text)

    if not found:
        log.error(
            "no editions found on the home page. The structure may have changed."
        )
    return sorted(found.items())


def parse_edition(html: str, edition: int, ceremony_year: int) -> dict[str, list[Nomination]]:
    """Parse an edition's nominations page.

    Returns nominations grouped by movie slug. The slug is the movie identity the
    server itself provides, so no fuzzy matching is needed anywhere (ADR-002).

    Rows we cannot identify are logged and skipped rather than raising: a single
    malformed row must not lose the whole edition.
    """
    soup = BeautifulSoup(html, "html.parser")
    by_movie: dict[str, list[Nomination]] = {}
    skipped = 0

    for section in soup.select(SELECTOR_CATEGORY):
        name_tag = section.select_one(SELECTOR_CATEGORY_NAME)
        category = clean_text(name_tag.get_text()) if name_tag else None
        if not category:
            log.warning("edition %s: category without a name, skipped", edition)
            continue

        for row in section.select(SELECTOR_ROW):
            link = row.select_one(SELECTOR_MOVIE_LINK)
            if not link:
                skipped += 1
                continue

            slug = link["href"].strip("/").split("/")[-1]
            if not slug:
                skipped += 1
                continue

            credited_tag = row.select_one(SELECTOR_CREDITED)
            note_tag = row.select_one(SELECTOR_NOTE)

            by_movie.setdefault(slug, []).append(
                make_nomination(
                    edition=edition,
                    ceremony_year=ceremony_year,
                    category=category,
                    credited=split_people(
                        credited_tag.get_text() if credited_tag else None
                    ),
                    won=row.select_one(SELECTOR_WINNER) is not None,
                    note=clean_text(note_tag.get_text()) if note_tag else None,
                )
            )

    if skipped:
        log.warning("edition %s: %s row(s) skipped, no movie link", edition, skipped)
    if not by_movie:
        log.error(
            "edition %s: no nominations found. The page structure may have changed.",
            edition,
        )
    return by_movie