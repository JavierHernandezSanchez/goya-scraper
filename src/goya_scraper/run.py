"""The run: from the home page to data/movies.json.

The whole flow is here, reading top to bottom. Nothing else orchestrates.
"""

import logging
import sys

from . import storage
from .http_client import HttpClient, HttpError
from .model import DETAIL_ERROR, DETAIL_NOT_FOUND, DETAIL_OK, Movie, Nomination
from .parse_edition import parse_edition, parse_editions_index
from .parse_movie import NotAMoviePageError, parse_movie
from .validate import LEVEL_ERROR, LEVEL_WARNING, render, validate

log = logging.getLogger("goya_scraper")

HOME_PATH = "/"


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout,
    )


def discover_editions(client: HttpClient) -> list[tuple[int, int]]:
    """Ask the site which editions exist. One request, then free from cache."""
    editions = parse_editions_index(client.get(HOME_PATH))
    if editions:
        log.info(
            "found %s editions (%s-%s)",
            len(editions), editions[0][1], editions[-1][1],
        )
    return editions


def fetch_movie(client: HttpClient, slug: str, nominations: list[Nomination]) -> Movie:
    """Build a Movie, including what happened when the page could not be read.

    A film we could not fetch is still a film that was nominated, so the record
    is kept with its nominations and detail_status says what went wrong. Losing
    the nominations would be the worse outcome.
    """
    try:
        movie = parse_movie(client.get(f"/pelicula/{slug}/"), slug)
        movie.detail_status = DETAIL_OK
    except NotAMoviePageError as exc:
        movie = Movie(slug=slug, detail_status=DETAIL_NOT_FOUND)
        movie.issues.append(f"movie page not usable: {exc}")
        log.warning("%s: %s", slug, exc)
    except HttpError as exc:
        # A 404 means the page is not there; anything else means we could not
        # read it. Those are different problems and the JSON must tell them apart.
        status = DETAIL_NOT_FOUND if exc.status == 404 else DETAIL_ERROR
        movie = Movie(slug=slug, detail_status=status)
        movie.issues.append(f"could not fetch movie page: {exc}")
        log.error("%s: %s", slug, exc)

    movie.nominations = nominations
    return movie


def add_movie(movies: dict[str, Movie], movie: Movie) -> None:
    """Deduplicate by slug.

    The slug is the identity the server gives us, so a plain dict keyed by it is
    the whole deduplication strategy (ADR-002). A film already present keeps its
    detail page and gains the new nominations.
    """
    existing = movies.get(movie.slug)
    if existing is None:
        movies[movie.slug] = movie
        return

    already = {
        (n.edition, n.category, tuple(n.credited))
        for n in existing.nominations
    }
    fresh = [
        n for n in movie.nominations
        if (n.edition, n.category, tuple(n.credited)) not in already
    ]
    if not fresh:
        log.info("%s already up to date, nothing added", movie.slug)
        return

    log.info(
        "%s already exists (%s nominations), merging %s more",
        movie.slug, existing.total_nominations, len(fresh),
    )
    existing.nominations.extend(fresh)


def scrape_edition(
    client: HttpClient, edition: int, year: int, movies: dict[str, Movie]
) -> bool:
    """Fetch one edition and merge its films into the collection.

    Returns True when the edition produced nominations. A failed edition is not
    recorded as done, so the next run will try it again.
    """
    log.info("fetching edition %s nominations", edition)
    try:
        html = client.get(f"/{edition}-edicion/nominaciones/")
    except HttpError as exc:
        log.error("could not fetch edition %s: %s", edition, exc)
        return False

    by_movie = parse_edition(html, edition, year)
    if not by_movie:
        log.error("edition %s yielded no nominations", edition)
        return False

    rows = sum(len(v) for v in by_movie.values())
    winners = sum(1 for v in by_movie.values() for n in v if n.won)
    categories = {n.category for v in by_movie.values() for n in v}
    log.info(
        "edition %s: %s categories, %s nominations, %s movies, %s winners",
        edition, len(categories), rows, len(by_movie), winners,
    )

    for position, (slug, nominations) in enumerate(sorted(by_movie.items()), 1):
        log.info("[%s/%s] %s", position, len(by_movie), slug)
        add_movie(movies, fetch_movie(client, slug, nominations))
    return True


def summarise(movies: dict[str, Movie]) -> None:
    """Log what we ended up with, including the free cross-check."""
    values = list(movies.values())
    incomplete = [m for m in values if m.detail_status != DETAIL_OK]
    checked = [m for m in values if m.detail_status == DETAIL_OK]
    mismatched = [
        m for m in checked
        if (m.total_nominations, m.total_awards)
        != (m.reported_nominations, m.reported_awards)
    ]

    log.info(
        "done: %s movies, %s nominations, %s awards",
        len(values),
        sum(m.total_nominations for m in values),
        sum(m.total_awards for m in values),
    )
    if incomplete:
        log.warning(
            "%s movie(s) without a usable detail page: %s",
            len(incomplete), ", ".join(sorted(m.slug for m in incomplete)),
        )
    log.info(
        "cross-check against the site's own counters: %s/%s match",
        len(checked) - len(mismatched), len(checked),
    )
    for movie in mismatched:
        log.warning(
            "MISMATCH %s: nominations %s vs %s, awards %s vs %s",
            movie.slug, movie.total_nominations, movie.reported_nominations,
            movie.total_awards, movie.reported_awards,
        )


def report_findings(document: dict) -> None:
    """Validate what we wrote and log the outcome.

    Validation failures never stop the run: the data is still worth having, and
    the report says exactly what to look at.
    """
    findings = validate(document)
    print(render(document, findings))

    errors = [f for f in findings if f.level == LEVEL_ERROR]
    warnings = [f for f in findings if f.level == LEVEL_WARNING]
    if errors:
        log.error("validation found %s error(s)", len(errors))
    if warnings:
        log.warning("validation found %s warning(s)", len(warnings))


def main() -> None:
    setup_logging()
    client = HttpClient()

    document = storage.load()
    done = set(document["_meta"]["editions_scraped"])
    movies = {
        movie["slug"]: Movie.from_dict(movie) for movie in document["movies"]
    }
    if movies:
        log.info("loaded %s movies from %s", len(movies), storage.DEFAULT_PATH)

    editions = discover_editions(client)
    pending = [(e, y) for e, y in editions if e not in done]
    log.info(
        "%s editions already done, %s pending", len(done), len(pending)
    )

    scraped: list[int] = sorted(done)
    for position, (edition, year) in enumerate(pending, 1):
        log.info("=== edition %s/%s: %s ===", position, len(pending), edition)
        if scrape_edition(client, edition, year, movies):
            scraped.append(edition)
            # Save after every edition. A full run takes about 35 minutes, and
            # without this an interruption at edition 30 would lose all of it.
            storage.save(storage.build_document(list(movies.values()), scraped))

    document = storage.build_document(list(movies.values()), scraped)
    storage.save(document)
    summarise(movies)
    report_findings(document)


if __name__ == "__main__":
    main()