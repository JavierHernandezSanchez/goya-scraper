"""Downloading posters during the run.

All of it runs against the same fake session as the other HTTP tests, so
nothing here touches the network.
"""

import pytest
import requests

from conftest import FakeResponse, make_client
from goya_scraper.http_client import RobotsDisallowed
from goya_scraper.model import Movie
from goya_scraper.run import POSTER_DIR, add_movie, fetch_movie, fetch_poster

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
URL = "https://www.premiosgoya.com/wp-content/uploads/cartel.jpg"

PAGE = """
<article class="pelicula">
  <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
  <img class="attachment-cartel size-cartel"
       src="/wp-content/uploads/cartel.jpg">
</article>
"""


@pytest.fixture
def poster_dir(tmp_path, monkeypatch):
    """Point POSTER_DIR at a temporary directory so tests never write to data/."""
    directory = tmp_path / "posters"
    monkeypatch.setattr("goya_scraper.run.POSTER_DIR", directory)
    return directory


def a_movie_with_poster() -> Movie:
    return Movie(slug="ejemplo", title="Ejemplo", poster_url=URL)


class TestFillingAGapInAnExistingRecord:
    """The second bug, found by actually running the thing.

    `add_movie` only ever merged nominations, so a poster downloaded on a later
    pass was thrown away: the record that survived was the old one, without it.
    384 films hit this. Filling a gap is not overwriting, so it does not
    conflict with keeping the detail page from the first pass.
    """

    def test_a_poster_reaches_a_record_that_had_none(self):
        movies = {"ejemplo": Movie(slug="ejemplo", title="Ejemplo")}  # no poster
        fresh = Movie(slug="ejemplo", title="Ejemplo", poster_url=URL,
                      poster_path="data/posters/ejemplo.jpg")

        add_movie(movies, fresh)

        assert movies["ejemplo"].poster_url == URL
        assert movies["ejemplo"].poster_path == "data/posters/ejemplo.jpg"

    def test_a_poster_already_there_is_not_overwritten(self):
        movies = {"ejemplo": Movie(slug="ejemplo", title="Ejemplo",
                                   poster_url="https://x/viejo.jpg",
                                   poster_path="data/posters/viejo.jpg")}
        fresh = Movie(slug="ejemplo", title="Ejemplo", poster_url=URL,
                      poster_path="data/posters/nuevo.jpg")

        add_movie(movies, fresh)

        assert movies["ejemplo"].poster_url == "https://x/viejo.jpg"

    def test_filling_the_gap_does_not_touch_the_detail_page(self):
        """The first pass's detail is kept; only the gap is filled."""
        movies = {"ejemplo": Movie(slug="ejemplo", title="El título bueno")}
        fresh = Movie(slug="ejemplo", title="Otro", poster_url=URL)

        add_movie(movies, fresh)

        assert movies["ejemplo"].title == "El título bueno"
        assert movies["ejemplo"].poster_url == URL


class TestDownloadingDuringTheRun:
    def test_a_poster_is_saved_and_recorded(self, poster_dir):
        client, _ = make_client([FakeResponse(200, content=JPEG)], tmp_path=poster_dir.parent)
        movie = a_movie_with_poster()

        fetch_poster(client, movie)

        assert movie.poster_path == "data/posters/ejemplo.jpg"
        assert (poster_dir / "ejemplo.jpg").exists()

    def test_a_film_without_a_poster_asks_for_nothing(self, poster_dir):
        client, session = make_client([], tmp_path=poster_dir.parent)
        movie = Movie(slug="sin-cartel", title="Sin cartel")

        fetch_poster(client, movie)

        assert movie.poster_url is None
        assert movie.poster_path is None
        assert session.calls == [], "sin cartel no se pide nada"

    def test_a_failure_leaves_the_film_intact(self, poster_dir):
        # The run must not stop over one image: the film keeps its record and
        # says the poster is missing.
        client, _ = make_client([FakeResponse(404, "")], tmp_path=poster_dir.parent)
        movie = a_movie_with_poster()

        fetch_poster(client, movie)

        assert movie.poster_path is None
        assert movie.issues, "el fallo queda anotado en el registro"
        assert not list(poster_dir.glob("*"))

    def test_a_network_failure_is_tolerated(self, poster_dir):
        client, _ = make_client(
            [requests.ConnectionError("down")], tmp_path=poster_dir.parent
        )
        movie = a_movie_with_poster()

        fetch_poster(client, movie)

        assert movie.poster_path is None

    def test_a_response_that_is_not_an_image_is_tolerated(self, poster_dir):
        client, _ = make_client(
            [FakeResponse(200, content=b"<html>no disponible</html>")],
            tmp_path=poster_dir.parent,
        )
        movie = a_movie_with_poster()

        fetch_poster(client, movie)

        assert movie.poster_path is None
        assert not list(poster_dir.glob("*"))

    def test_a_second_run_reuses_the_file(self, poster_dir):
        client, session = make_client(
            [FakeResponse(200, content=JPEG)], tmp_path=poster_dir.parent
        )
        movie = a_movie_with_poster()

        fetch_poster(client, movie)
        asked = len(session.calls)
        fetch_poster(client, movie)

        assert movie.poster_path == "data/posters/ejemplo.jpg"
        assert len(session.calls) == asked, "la segunda vez no se vuelve a pedir"

    def test_a_refused_image_is_not_requested(self, poster_dir):
        client, session = make_client(
            [FakeResponse(200, text="User-agent: *\nDisallow: /wp-content/")],
            tmp_path=poster_dir.parent,
            respect_robots=True,
        )
        movie = a_movie_with_poster()

        with pytest.raises(RobotsDisallowed):
            client.download(URL, POSTER_DIR, movie.slug)

        assert not any(c["url"].endswith(".jpg") for c in session.calls)


class TestTheRunKeepsGoing:
    def test_a_film_whose_poster_fails_still_lands(self, poster_dir):
        # The page is fine, the image is not. The film must arrive anyway: it
        # was nominated, and its nominations are worth more than its poster.
        outcomes = [
            FakeResponse(200, text=PAGE),   # the movie page
            FakeResponse(404, ""),           # its poster
        ]
        client, _ = make_client(outcomes, tmp_path=poster_dir.parent)

        movie = fetch_movie(client, "ejemplo", [])

        assert movie.slug == "ejemplo"
        assert movie.detail_status == "ok"
        assert movie.poster_url == URL
        assert movie.poster_path is None

    def test_a_film_with_a_poster_records_both(self, poster_dir):
        outcomes = [
            FakeResponse(200, text=PAGE),
            FakeResponse(200, content=JPEG),
        ]
        client, _ = make_client(outcomes, tmp_path=poster_dir.parent)

        movie = fetch_movie(client, "ejemplo", [])

        assert movie.poster_url == URL
        assert movie.poster_path == "data/posters/ejemplo.jpg"