"""End-to-end: parse a whole edition, then check our numbers against the
counters the Academy publishes on each movie page.

This is the free quality check described in ADR-012.
"""

from goya_scraper.parse_edition import parse_edition
from goya_scraper.parse_movie import parse_movie

EDITION = 36
YEAR = 2022

# One real movie page per film, kept small on purpose: this test checks the
# cross-validation logic, not the HTTP layer.
MOVIE_FIXTURES = {
    "el-buen-patron": "pelicula_el-buen-patron.html",   # 20 nominations, 6 awards
    "maixabel": "pelicula_maixabel.html",               # 14 nominations, 3 awards
    "otra-ronda": "pelicula_otra-ronda.html",           # 1 nomination, 1 award
    "yalla": "pelicula_yalla.html",                     # 1 nomination, 0 awards
}


def test_cross_check_against_reported_counters(edition_36, load):
    by_movie = parse_edition(edition_36, EDITION, YEAR)
    checked = 0

    for slug, filename in MOVIE_FIXTURES.items():
        nominations = by_movie[slug]
        movie = parse_movie(load(filename), slug)
        movie.nominations = nominations
        checked += 1

        assert movie.total_nominations == movie.reported_nominations, slug
        assert movie.total_awards == movie.reported_awards, slug

    assert checked == 4


def test_a_film_with_no_awards_keeps_its_nomination(edition_36, load):
    by_movie = parse_edition(edition_36, EDITION, YEAR)
    movie = parse_movie(load("pelicula_yalla.html"), "yalla")
    movie.nominations = by_movie["yalla"]

    assert movie.total_nominations == 1
    assert movie.total_awards == 0
    assert movie.nominations[0].won is False


def test_repeated_nominations_are_all_kept(edition_36, load):
    """The same film can hold several rows of the same category."""
    by_movie = parse_edition(edition_36, EDITION, YEAR)
    movie = parse_movie(load("pelicula_el-buen-patron.html"), "el-buen-patron")
    movie.nominations = by_movie["el-buen-patron"]

    assert movie.total_nominations == 20
    assert movie.distinct_categories == 17
    assert movie.total_awards == 6
    assert movie.editions == [36]


def test_no_slug_appears_in_two_editions(edition_1, edition_36):
    """Verified against the real data: identity is unambiguous (ADR-002)."""
    old = parse_edition(edition_1, 1, 1987)
    new = parse_edition(edition_36, EDITION, YEAR)
    assert not (set(old) & set(new))