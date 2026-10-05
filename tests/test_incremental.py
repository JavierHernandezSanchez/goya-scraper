"""Incremental behaviour: the second run must do as little as possible.

Two independent mechanisms, both tested here:

1. The HTML cache. If a page is already on disk we do not ask for it again.
2. `_meta.editions_scraped`. An edition already recorded is not processed again.
"""

import pytest

from goya_scraper import storage
from goya_scraper.model import Movie, Nomination
from goya_scraper.parse_edition import parse_editions_index
from goya_scraper.parse_movie import parse_movie
from goya_scraper.run import HOME_PATH, discover_editions


class TestDiscoverEditions:
    def test_reads_all_forty_from_the_home_page(self, home):
        editions = parse_editions_index(home)
        assert len(editions) == 40

    def test_first_and_last(self, home):
        editions = parse_editions_index(home)
        assert editions[0] == (1, 1987)
        assert editions[-1] == (40, 2026)

    def test_sorted_by_edition(self, home):
        editions = parse_editions_index(home)
        assert [e for e, _ in editions] == sorted(e for e, _ in editions)

    def test_year_matches_edition_plus_1986(self, home):
        # True for all 40, but we read it rather than compute it.
        for edition, year in parse_editions_index(home):
            assert year == edition + 1986

    def test_uses_the_home_cache(self, tmp_path, home):
        class Client:
            def __init__(self):
                self.calls = []

            def get(self, path):
                self.calls.append(path)
                return home

        client = Client()
        assert len(discover_editions(client)) == 40
        assert client.calls == [HOME_PATH]

    def test_page_without_the_list_gives_nothing(self):
        assert parse_editions_index("<html><body>otra cosa</body></html>") == []

    def test_links_with_a_different_shape_are_ignored(self):
        html = """
        <ol class="lista-anios__lista">
          <li><a href="/36-edicion/">2022</a></li>
          <li><a href="/no-es-edicion/">2021</a></li>
          <li><a href="/37-edicion/">sin año</a></li>
        </ol>
        """
        assert parse_editions_index(html) == [(36, 2022)]


class TestMovieRoundTrip:
    """from_dict and to_dict are symmetric, which incremental runs rely on."""

    def test_survives_a_round_trip(self, buen_patron):
        movie = parse_movie(buen_patron, "el-buen-patron")
        movie.nominations = [
            Nomination(36, 2022, "Mejor película", ["El buen patrón"], True, "nota")
        ]
        assert Movie.from_dict(movie.to_dict()) == movie

    def test_a_movie_from_the_json_reloads_identically(self, tmp_path):
        movie = Movie(slug="x", title="X")
        movie.nominations = [Nomination(1, 1987, "Mejor película", ["X"], True)]
        storage.save(storage.build_document([movie], [1]), tmp_path / "m.json")
        reloaded = storage.load(tmp_path / "m.json")["movies"][0]
        assert Movie.from_dict(reloaded) == movie

    def test_a_record_missing_goya_is_rejected(self, tmp_path):
        # Tolerating this would silently turn a broken record into "a film with
        # no nominations", which is exactly the kind of quiet data loss we avoid.
        with pytest.raises(KeyError):
            Movie.from_dict({"slug": "x"})

    def test_optional_fields_fall_back_to_defaults(self):
        movie = Movie.from_dict({
            "slug": "x",
            "goya": {"nominations": []},
        })
        assert movie.title is None
        assert movie.countries == []
        assert movie.credits.directors == []
        assert movie.reported_nominations == 0
        assert movie.detail_status == "ok"


class TestSkipAlreadyScrapedEditions:
    def test_pending_is_derived_from_editions_scraped(self, home):
        done = {36}
        editions = parse_editions_index(home)
        pending = [(e, y) for e, y in editions if e not in done]
        assert len(pending) == 39
        assert 36 not in [e for e, _ in pending]

    def test_empty_document_means_everything_is_pending(self, home):
        document = storage.empty_document()
        editions = parse_editions_index(home)
        pending = [(e, y) for e, y in editions
                   if e not in set(document["_meta"]["editions_scraped"])]
        assert len(pending) == 40

    def test_editions_scraped_survives_a_new_run(self, tmp_path):
        target = tmp_path / "movies.json"
        document = storage.build_document([Movie(slug="x", title="X")], [36])
        storage.save(document, target)

        reloaded = storage.load(target)
        assert reloaded["_meta"]["editions_scraped"] == [36]

    def test_counts_are_recomputed_for_a_merged_document(self, tmp_path):
        target = tmp_path / "movies.json"
        first = Movie(slug="a", title="A")
        second = Movie(slug="b", title="B")
        storage.save(storage.build_document([first], [1]), target)

        reloaded = storage.load(target)
        movies = [Movie.from_dict(m) for m in reloaded["movies"]]
        movies.append(second)
        storage.save(storage.build_document(movies, [1, 2]), target)

        final = storage.load(target)
        assert final["_meta"]["counts"]["movies"] == 2
        assert final["_meta"]["editions_scraped"] == [1, 2]