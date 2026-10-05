"""Deduplication: one film, one record, however many times it is nominated.

The whole strategy is a dict keyed by the slug the server gives us (ADR-002).
These tests pin down that behaviour without any network access.
"""

from goya_scraper.http_client import HttpError
from goya_scraper.model import Movie, Nomination
from goya_scraper.run import add_movie, fetch_movie


def nomination(edition, category, credited, won=False):
    return Nomination(edition, edition + 1986, category, credited, won)


def movie_for(slug, edition, categories):
    movie = Movie(slug=slug, title=slug.replace("-", " ").title())
    movie.nominations = [
        nomination(edition, category, [slug]) for category in categories
    ]
    return movie


class TestOneFilmOneRecord:
    def test_same_slug_twice_gives_one_movie(self):
        movies: dict[str, Movie] = {}
        add_movie(movies, movie_for("el-buen-patron", 36, ["Mejor película"]))
        add_movie(movies, movie_for("el-buen-patron", 36, ["Mejor dirección"]))
        assert list(movies) == ["el-buen-patron"]

    def test_twenty_rows_of_one_film_are_one_movie(self):
        """El buen patrón: 20 nomination rows across 17 categories."""
        movies: dict[str, Movie] = {}
        categories = [f"Categoría {i % 17}" for i in range(20)]
        movie = Movie(slug="el-buen-patron", title="El buen patrón")
        movie.nominations = [nomination(36, c, ["x"]) for c in categories]
        add_movie(movies, movie)
        assert len(movies) == 1
        assert movies["el-buen-patron"].total_nominations == 20
        assert movies["el-buen-patron"].distinct_categories == 17

    def test_nominations_are_merged_not_replaced(self):
        movies: dict[str, Movie] = {}
        add_movie(movies, movie_for("f", 36, ["Mejor película"]))
        add_movie(movies, movie_for("f", 36, ["Mejor dirección"]))
        assert movies["f"].total_nominations == 2

    def test_awards_survive_the_merge(self):
        movies: dict[str, Movie] = {}
        winner = movie_for("f", 36, ["Mejor película"])
        winner.nominations[0].won = True
        add_movie(movies, winner)
        add_movie(movies, movie_for("f", 36, ["Mejor dirección"]))
        assert movies["f"].total_awards == 1
        assert movies["f"].total_nominations == 2

    def test_detail_page_from_the_first_pass_is_kept(self):
        movies: dict[str, Movie] = {}
        first = movie_for("f", 36, ["Mejor película"])
        first.synopsis = "Un buen patrón."
        add_movie(movies, first)
        # A later edition re-nominates it; that page fetch must not wipe the synopsis.
        add_movie(movies, movie_for("f", 40, ["Mejor dirección"]))
        assert movies["f"].synopsis == "Un buen patrón."

    def test_different_slugs_stay_separate(self):
        # Three real films whose titles are single common words. Title-based
        # deduplication would have merged them; slug-based keeps them apart.
        movies: dict[str, Movie] = {}
        for slug in ["amor", "bella", "tres"]:
            add_movie(movies, movie_for(slug, 36, ["Mejor película"]))
        assert len(movies) == 3


class TestMultiEdition:
    """No film really competes twice, but the model allows it and merges."""

    def test_editions_are_collected(self):
        movies: dict[str, Movie] = {}
        add_movie(movies, movie_for("f", 36, ["Mejor película"]))
        add_movie(movies, movie_for("f", 40, ["Mejor dirección"]))
        assert movies["f"].editions == [36, 40]

    def test_totals_span_both_editions(self):
        movies: dict[str, Movie] = {}
        add_movie(movies, movie_for("f", 36, ["Mejor película"]))
        add_movie(movies, movie_for("f", 40, ["Mejor dirección"]))
        assert movies["f"].total_nominations == 2


class TestFetchFailureKeepsTheNominations:
    """A film whose page we cannot read is still a film that was nominated."""

    class NotFoundClient:
        def get(self, path):
            raise HttpError("HTTP 404", status=404)

    class BrokenClient:
        def get(self, path):
            raise HttpError("connection reset", status=None)

    def test_404_is_reported_as_not_found(self):
        movie = fetch_movie(
            self.NotFoundClient(), "fantasma", [nomination(36, "Mejor película", ["x"])]
        )
        assert movie.detail_status == "not_found"

    def test_nominations_are_not_lost(self):
        movie = fetch_movie(
            self.NotFoundClient(), "fantasma", [nomination(36, "Mejor película", ["x"])]
        )
        assert movie.total_nominations == 1
        assert movie.title is None
        assert movie.issues

    def test_network_error_is_distinguished_from_404(self):
        # Both are failures, but they need different fixes, so they are
        # reported differently. This distinction is the whole point of the field.
        movie = fetch_movie(self.BrokenClient(), "x", [])
        assert movie.detail_status == "error"

    def test_unusable_html_is_reported_as_not_found(self):
        class JunkClient:
            def get(self, path):
                return "<html><body>not a movie</body></html>"

        movie = fetch_movie(JunkClient(), "x", [])
        assert movie.detail_status == "not_found"