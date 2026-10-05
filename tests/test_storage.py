"""Reading and writing data/movies.json.

These tests write to a temporary directory, never to the real data/ folder.
"""

import json

import pytest

from goya_scraper.model import (
    DETAIL_ERROR,
    DETAIL_OK,
    Credits,
    Movie,
    Nomination,
)
from goya_scraper.storage import (
    SCHEMA_VERSION,
    CorruptDocumentError,
    build_document,
    compute_counts,
    empty_document,
    load,
    save,
)


def make_movie(slug="el-buen-patron", title="El buen patrón", **kwargs) -> Movie:
    movie = Movie(slug=slug, title=title, **kwargs)
    movie.credits = Credits(
        directors=["Fernando León de Aranoa"],
        producers_raw="Reposado Producciones Cinematográficas, Mediaproducción, S.L.U.",
    )
    movie.reported_nominations = 20
    movie.reported_awards = 6
    movie.nominations = [
        Nomination(36, 2022, "Mejor película", ["El buen patrón"], True, "productores"),
        Nomination(36, 2022, "Mejor dirección", ["Fernando León de Aranoa"], True),
        Nomination(36, 2022, "Mejor actor de reparto", ["Celso Bugallo"], False),
        Nomination(36, 2022, "Mejor actor de reparto", ["Manolo Solo"], False),
    ]
    return movie


@pytest.fixture
def target(tmp_path):
    return tmp_path / "data" / "movies.json"


class TestEmptyDocument:
    def test_shape(self):
        document = empty_document()
        assert set(document) == {"_meta", "movies"}
        assert document["movies"] == []
        assert document["_meta"]["schema_version"] == SCHEMA_VERSION
        assert document["_meta"]["generated_at"] is None

    def test_source_is_the_official_site(self):
        assert empty_document()["_meta"]["source"] == "https://www.premiosgoya.com"


class TestCounts:
    def test_derived_from_the_movies(self):
        movies = [make_movie().to_dict()]
        assert compute_counts(movies) == {
            "editions": 1,
            "movies": 1,
            "nominations": 4,
            "awards": 2,
            "distinct_categories": 3,
        }

    def test_empty(self):
        assert compute_counts([])["movies"] == 0

    def test_counts_are_recomputed_on_save_not_trusted(self, target):
        document = build_document([make_movie()], [36])
        document["_meta"]["counts"]["movies"] = 999  # sabotage
        save(document, target)
        assert load(target)["_meta"]["counts"]["movies"] == 1


class TestBuildDocument:
    def test_movies_sorted_by_title_ignoring_accents(self):
        document = build_document(
            [
                make_movie(slug="z", title="Zambrano"),
                make_movie(slug="a", title="Ámbar"),
                make_movie(slug="b", title="berlín blues"),
            ],
            [36],
        )
        titles = [m["title"] for m in document["movies"]]
        # "Ámbar" must not land after "Zambrano" just because of the accent.
        assert titles == ["Ámbar", "berlín blues", "Zambrano"]

    def test_titleless_movie_sorts_last_and_is_kept(self):
        document = build_document(
            [make_movie(slug="sin-ficha", title=None), make_movie(slug="con", title="Amar")],
            [36],
        )
        titles = [m["title"] for m in document["movies"]]
        assert titles == ["Amar", None]

    def test_editions_are_sorted_and_unique(self):
        document = build_document([make_movie()], [36, 36, 1])
        assert document["_meta"]["editions_scraped"] == [1, 36]


class TestRoundTrip:
    def test_write_then_read_gives_the_same_data(self, target):
        document = build_document([make_movie()], [36])
        save(document, target)
        assert load(target) == document

    def test_file_is_indented_and_keeps_accented_characters(self, target):
        save(build_document([make_movie()], [36]), target)
        raw = target.read_text(encoding="utf-8")
        assert "El buen patrón" in raw          # not "El buen patr\u00f3n"
        assert "\\u" not in raw
        # indent=2, and a movie object sits inside the "movies" array, so its
        # keys land six spaces in.
        assert '\n      "slug": "el-buen-patron"' in raw

    def test_file_ends_with_a_newline(self, target):
        save(build_document([make_movie()], [36]), target)
        assert target.read_text(encoding="utf-8").endswith("}\n")

    def test_is_valid_json(self, target):
        save(build_document([make_movie()], [36]), target)
        json.loads(target.read_text(encoding="utf-8"))

    def test_creates_missing_directories(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "movies.json"
        save(build_document([make_movie()], [36]), deep)
        assert deep.exists()

    def test_no_temporary_file_left_behind(self, target):
        save(build_document([make_movie()], [36]), target)
        assert not target.with_name(target.name + ".tmp").exists()


class TestAtomicity:
    def test_previous_file_survives_a_failed_write(self, target, monkeypatch):
        save(build_document([make_movie()], [36]), target)
        good = target.read_text(encoding="utf-8")

        # Simulate dying while serialising the new document.
        document = build_document([make_movie(slug="otro", title="Otro")], [37])
        monkeypatch.setattr(
            json, "dumps", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError):
            save(document, target)

        assert target.read_text(encoding="utf-8") == good


class TestLoad:
    def test_missing_file_gives_empty_document(self, target):
        assert load(target) == empty_document()

    def test_corrupt_file_raises_instead_of_silently_discarding(self, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ this is not json", encoding="utf-8")
        with pytest.raises(CorruptDocumentError):
            load(target)

    def test_document_missing_keys_is_tolerated(self, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"_meta": {}, "movies": []}', encoding="utf-8")
        document = load(target)
        assert document["_meta"]["editions_scraped"] == []
        assert document["_meta"]["schema_version"] == SCHEMA_VERSION


class TestDataQualityIsHonest:
    def test_reported_counters_present_when_page_was_read(self):
        movie = make_movie()
        quality = movie.to_dict()["data_quality"]
        assert quality["reported_by_source"] == {
            "nominations": 20,
            "awards": 6,
            # None means "we never recorded it"; make_movie does not set it.
            "award_categories": None,
        }

    def test_award_categories_are_kept(self):
        movie = make_movie()
        movie.reported_award_categories = ["Mejor película", "Mejor dirección"]
        assert movie.to_dict()["data_quality"]["reported_by_source"]["award_categories"] == [
            "Mejor película",
            "Mejor dirección",
        ]

    def test_reported_counters_are_null_when_the_page_failed(self):
        # Otherwise a failed fetch would look like "the site says zero".
        movie = make_movie()
        movie.detail_status = DETAIL_ERROR
        assert movie.to_dict()["data_quality"]["reported_by_source"] is None

    def test_status_is_preserved(self):
        movie = make_movie()
        movie.detail_status = DETAIL_ERROR
        movie.issues.append("timeout")
        quality = movie.to_dict()["data_quality"]
        assert quality["detail_status"] == DETAIL_ERROR
        assert quality["issues"] == ["timeout"]

    def test_ok_status_when_everything_worked(self):
        assert make_movie().to_dict()["data_quality"]["detail_status"] == DETAIL_OK


class TestMovieSerialisation:
    def test_url_is_built_from_the_slug(self):
        assert make_movie().to_dict()["url"] == (
            "https://www.premiosgoya.com/pelicula/el-buen-patron/"
        )

    def test_repeated_category_is_kept_as_two_nominations(self):
        goya = make_movie().to_dict()["goya"]
        reparto = [n for n in goya["nominations"] if n["category"] == "Mejor actor de reparto"]
        assert len(reparto) == 2
        assert goya["total_nominations"] == 4

    def test_absent_fields_are_null_not_empty(self):
        movie = make_movie()
        payload = movie.to_dict()
        assert payload["title_original"] is None
        assert payload["duration_minutes"] is None

    def test_producers_are_a_single_string(self):
        credits = make_movie().to_dict()["credits"]
        assert isinstance(credits["producers_raw"], str)

    def test_field_order_is_stable(self):
        # Key order is meaningful in the file, so it is worth pinning down.
        assert list(make_movie().to_dict()) == [
            "slug", "url", "title", "title_original", "synopsis", "countries",
            "countries_raw", "duration_minutes", "credits", "goya", "data_quality",
        ]