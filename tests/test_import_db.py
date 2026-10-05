"""Importing a document into SQLite.

The importer is where the model meets the data, so these tests are mostly about
whether what the JSON says is what the database ends up holding. The row counts
are pinned to the real dataset: if a future change makes the import lose a
nomination, that shows up here as a number rather than as a quiet omission.
"""

import json
import pathlib
import sqlite3

import pytest

from goya_scraper import db, import_db, storage
from goya_scraper.import_db import DocumentNotImportable, ImportReport

DATASET = pathlib.Path("data/movies.json")
needs_dataset = pytest.mark.skipif(
    not DATASET.exists(), reason="needs a generated dataset"
)


def minimal_movie(slug="una-pelicula", **overrides):
    """One film with one nomination: the smallest thing that imports."""
    movie = {
        "slug": slug,
        "url": f"https://www.premiosgoya.com/pelicula/{slug}/",
        "title": "Una pelicula",
        "title_original": None,
        "synopsis": None,
        "countries": ["España"],
        "countries_raw": "Española",
        "duration_minutes": 100,
        "credits": {
            "directors": ["Alma Gárate"],
            "screenwriters": [],
            "cast": ["Carmen Maura"],
            "producers_raw": "Tornasol Films, S.A.",
        },
        "goya": {
            "editions": [36],
            "total_nominations": 2,
            "total_awards": 1,
            "nominations": [
                {
                    "edition": 36,
                    "ceremony_year": 2022,
                    "category": "Mejor película",
                    "category_raw": "Mejor película",
                    "credited": ["Una pelicula"],
                    "won": True,
                    "note": "Por Una pelicula",
                },
                {
                    "edition": 36,
                    "ceremony_year": 2022,
                    "category": "Mejor dirección",
                    "category_raw": "Mejor dirección",
                    "credited": ["Alma Gárate"],
                    "won": False,
                    "note": "Por Una pelicula",
                },
            ],
        },
        "data_quality": {
            "detail_status": "ok",
            "reported_by_source": {
                "nominations": 2,
                "awards": 1,
                "award_categories": ["Mejor película"],
            },
            "missing_fields": ["title_original"],
            "issues": [],
        },
    }
    movie.update(overrides)
    return movie


def minimal_document(movies=None):
    return {
        "_meta": {
            "schema_version": 3,
            "source": "https://www.premiosgoya.com",
            "generated_at": "2026-01-01T00:00:00Z",
            "editions_scraped": [36],
            "counts": {},
        },
        "movies": movies if movies is not None else [minimal_movie()],
    }


class Imported:
    """A small imported database: the report plus a connection to read it."""

    def __init__(self, report, connection, path):
        self.report = report
        self.connection = connection
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.connection.close()
        return False


@pytest.fixture
def imported(tmp_path):
    """Import the smallest possible document and hand back both results."""

    def _import(document=None, name="goya.db"):
        path = tmp_path / name
        report = import_db.import_document(document or minimal_document(), path)
        return Imported(report, db.connect(path), path)

    return _import


class TestTheReport:
    def test_a_clean_import_has_no_problems(self, imported):
        with imported() as result:
            assert result.report.ok
            assert result.report.problems == []

    def test_the_report_counts_what_landed(self, imported):
        report = imported().report
        assert report.movies == 1
        assert report.nominations == 2
        assert report.awards == 1
        assert report.persons == 2  # the director and the actor
        assert report.movie_credits == 2

    def test_the_report_renders_for_a_human(self):
        text = ImportReport(movies=1678, nominations=4050).render()
        assert "1678" in text and "4050" in text
        assert "problema" not in text

    def test_problems_are_shown_when_present(self):
        text = ImportReport(problems=["algo"]).render()
        assert "1 problema(s)" in text
        assert "algo" in text


class TestTheWholeDataset:
    """Counts pinned to the real 40-edition file."""

    @needs_dataset
    def test_every_table_matches_the_analysis(self, tmp_path):
        path = tmp_path / "goya.db"
        report = import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            expected = {
                "goya_edition": 40,
                "category": 31,
                "country": 48,
                "movie": 1678,
                "person": 6033,
                "person_alias": 6130,
                "movie_credit": 10389,
                "movie_country": 1861,
                "nomination": 4050,
                "nomination_credit": 5277,
                "reported_award": 1027,
            }
            for table, count in expected.items():
                actual = connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                assert actual == count, f"{table}: {actual} != {count}"
            assert report.ok
        finally:
            connection.close()

    @needs_dataset
    def test_the_database_is_internally_consistent(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            connection.close()

    @needs_dataset
    def test_the_totals_view_agrees_with_the_metadata(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            row = connection.execute(
                "SELECT SUM(total_nominations) AS n, SUM(total_awards) AS w "
                "FROM movie_totals"
            ).fetchone()
            meta = connection.execute("SELECT * FROM dataset_meta").fetchone()
            assert row["n"] == meta["nominations"]
            assert row["w"] == meta["awards"]
            assert (row["n"], row["w"]) == (4050, 1027)
        finally:
            connection.close()

    @needs_dataset
    def test_the_json_is_never_modified(self, tmp_path):
        """movies.json stays the source of truth."""
        before = DATASET.read_bytes()
        import_db.import_file(DATASET, tmp_path / "goya.db")
        assert DATASET.read_bytes() == before

    @needs_dataset
    def test_the_hash_describes_the_file_that_was_imported(self, tmp_path):
        import hashlib

        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            stored = connection.execute(
                "SELECT json_sha256 FROM import_run"
            ).fetchone()[0]
            assert stored == hashlib.sha256(DATASET.read_bytes()).hexdigest()
        finally:
            connection.close()


class TestWhatTheDocumentSays:
    def test_a_film_keeps_its_slug_and_title(self, imported):
        connection = imported().connection
        row = connection.execute("SELECT * FROM movie").fetchone()
        assert row["slug"] == "una-pelicula"
        assert row["title"] == "Una pelicula"
        assert row["duration_minutes"] == 100

    def test_the_raw_country_text_is_kept_next_to_the_relation(self, imported):
        connection = imported().connection
        assert connection.execute(
            "SELECT countries_raw FROM movie"
        ).fetchone()[0] == "Española"
        assert connection.execute(
            "SELECT c.name FROM movie_country mc "
            "JOIN country c ON c.id = mc.country_id"
        ).fetchone()[0] == "España"

    def test_a_missing_page_means_no_reported_counts(self, tmp_path):
        """ADR-014: NULL is 'we never read it'; 0 is 'the page said zero'.

        Two films in this dataset claim zero awards while the edition awarded
        them, and that claim has to survive the import intact."""
        movie = minimal_movie()
        movie["data_quality"] = {"detail_status": "error", "reported_by_source": None}
        path = tmp_path / "goya.db"
        report = import_db.import_document(minimal_document([movie]), path)
        assert report.ok

        connection = db.connect(path)
        try:
            row = connection.execute(
                "SELECT detail_status, reported_nominations, reported_awards FROM movie"
            ).fetchone()
            assert row["detail_status"] == "error"
            assert row["reported_nominations"] is None
            assert row["reported_awards"] is None
        finally:
            connection.close()

    def test_a_page_that_says_zero_keeps_the_zero(self, tmp_path):
        """El rey de la granja: the page says 0 awards, the edition says 1."""
        movie = minimal_movie()
        movie["data_quality"]["reported_by_source"] = {
            "nominations": 2,
            "awards": 0,
            "award_categories": [],
        }
        movie["goya"]["total_awards"] = 0
        movie["goya"]["nominations"][0]["won"] = False
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document([movie]), path)
        connection = db.connect(path)
        try:
            row = connection.execute(
                "SELECT reported_awards FROM movie"
            ).fetchone()
            assert row["reported_awards"] == 0
            # An empty list means the page said none, so it produces no rows.
            assert connection.execute(
                "SELECT COUNT(*) FROM reported_award"
            ).fetchone()[0] == 0
        finally:
            connection.close()


def _tmp_db():
    import tempfile

    return pathlib.Path(tempfile.mkdtemp()) / "goya.db"


class TestNominationIsTheCore:
    def test_a_nomination_links_film_edition_and_category(self, imported):
        connection = imported().connection
        # Ordered by category so the row is the same one on every run.
        row = connection.execute(
            "SELECT n.won, c.name, c.credited_kind, e.number, m.slug, n.category_raw "
            "FROM nomination n "
            "JOIN category c ON c.id = n.category_id "
            "JOIN goya_edition e ON e.id = n.edition_id "
            "JOIN movie m ON m.id = n.movie_id "
            "WHERE c.name = 'Mejor película'"
        ).fetchone()
        assert row["slug"] == "una-pelicula"
        assert row["number"] == 36
        assert row["name"] == "Mejor película"
        assert row["credited_kind"] == "work"
        assert row["won"] == 1
        assert row["category_raw"] == "Mejor película"

    def test_every_nomination_points_at_all_three(self, imported):
        """No orphans: the three foreign keys are what make the model queryable."""
        connection = imported().connection
        orphans = connection.execute(
            "SELECT COUNT(*) FROM nomination n "
            "WHERE NOT EXISTS (SELECT 1 FROM movie m WHERE m.id = n.movie_id) "
            "   OR NOT EXISTS (SELECT 1 FROM goya_edition e WHERE e.id = n.edition_id) "
            "   OR NOT EXISTS (SELECT 1 FROM category c WHERE c.id = n.category_id)"
        ).fetchone()[0]
        assert orphans == 0

    def test_the_ceremony_year_is_stored_once_per_edition(self, imported):
        connection = imported().connection
        assert connection.execute(
            "SELECT ceremony_year FROM goya_edition"
        ).fetchone()[0] == 2022
        assert connection.execute(
            "SELECT COUNT(*) FROM goya_edition"
        ).fetchone()[0] == 1

    def test_winning_is_a_column_and_not_a_table(self, imported):
        """ADR-029: no `award` table exists, and one could not hold ties."""
        connection = imported().connection
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "award" not in tables
        assert "nomination" in tables

    def test_two_winners_in_one_category_are_both_stored(self, tmp_path):
        """The real tie cases: edition 17 had three winners for one award."""
        first = minimal_movie("aaa")
        second = minimal_movie("bbb")
        document = minimal_document([first, second])
        report = import_db.import_document(document, tmp_path / "goya.db")
        connection = db.connect(tmp_path / "goya.db")
        try:
            winners = connection.execute(
                "SELECT COUNT(*) FROM nomination n JOIN category c ON c.id = n.category_id "
                "WHERE c.name = 'Mejor película' AND n.won = 1"
            ).fetchone()[0]
            assert winners == 2
            assert report.awards == 2
        finally:
            connection.close()

    def test_a_category_with_no_winner_is_allowed(self, tmp_path):
        movie = minimal_movie()
        movie["goya"]["nominations"][0]["won"] = False
        movie["goya"]["nominations"][1]["won"] = False
        report = import_db.import_document(
            minimal_document([movie]), tmp_path / "goya.db"
        )
        assert report.awards == 0
        assert report.nominations == 2

    def test_a_film_may_hold_two_actors_in_one_category(self, tmp_path):
        """46 real cases, e.g. Alcarràs in edition 37."""
        movie = minimal_movie()
        movie["goya"]["nominations"][1]["credited"] = [
            "Alma Gárate",
            "Carmen Maura",
        ]
        movie["goya"]["nominations"][1]["won"] = True
        report = import_db.import_document(
            minimal_document([movie]), tmp_path / "goya.db"
        )
        assert report.nominations == 2
        assert report.awards == 2


class TestCreditsAndPeople:
    def test_a_person_credit_resolves_to_a_person(self, imported):
        connection = imported().connection
        row = connection.execute(
            "SELECT nc.credit_text, p.name FROM nomination_credit nc "
            "JOIN person p ON p.id = nc.person_id"
        ).fetchone()
        assert row["credit_text"] == "Alma Gárate"
        assert row["name"] == "Alma Gárate"

    def test_a_work_credit_does_not_resolve(self, imported):
        """The credited string is the film's own title, so it needs no person."""
        connection = imported().connection
        resolved = connection.execute(
            "SELECT COUNT(*) FROM nomination_credit WHERE person_id IS NOT NULL"
        ).fetchone()[0]
        assert resolved == 1

    def test_credits_keep_their_position(self, imported):
        connection = imported().connection
        positions = [
            row["position"]
            for row in connection.execute(
                "SELECT nc.position FROM nomination_credit nc "
                "JOIN nomination n ON n.id = nc.nomination_id "
                "JOIN category c ON c.id = n.category_id "
                "WHERE c.name = 'Mejor dirección'"
            )
        ]
        assert positions == [1]

    def test_two_roles_in_one_film_become_two_rows(self, imported):
        movie = minimal_movie()
        movie["credits"]["screenwriters"] = ["Alma Gárate"]
        document = minimal_document([movie])
        path = _tmp_db()
        import_db.import_document(document, path)
        connection = db.connect(path)
        try:
            roles = [
                row["role"]
                for row in connection.execute(
                    "SELECT mc.role FROM movie_credit mc "
                    "JOIN person p ON p.id = mc.person_id WHERE p.name = 'Alma Gárate' "
                    "ORDER BY mc.role"
                )
            ]
            assert roles == ["director", "screenwriter"]
        finally:
            connection.close()

    def test_the_technical_crew_survives_only_through_nominations(self, imported):
        """Sound, photography and wardrobe have no field on the film page, so
        without nomination_credit they would not exist at all."""
        movie = minimal_movie()
        movie["goya"]["nominations"].append(
            {
                "edition": 36,
                "ceremony_year": 2022,
                "category": "Mejor sonido",
                "category_raw": "Mejor sonido",
                "credited": ["Pau Costa"],
                "won": True,
                "note": "Por Una pelicula",
            }
        )
        document = minimal_document([movie])
        path = _tmp_db()
        import_db.import_document(document, path)
        connection = db.connect(path)
        try:
            from_credits = connection.execute(
                "SELECT COUNT(*) FROM movie_credit"
            ).fetchone()[0]
            from_nominations = connection.execute(
                "SELECT COUNT(DISTINCT person_id) FROM nomination_credit "
                "WHERE person_id IS NOT NULL"
            ).fetchone()[0]
            assert from_credits == 2
            assert from_nominations == 2  # the director plus Pau Costa
        finally:
            connection.close()


class TestReportedAwards:
    def test_what_the_page_claimed_is_kept_apart(self, imported):
        connection = imported().connection
        row = connection.execute("SELECT * FROM reported_award").fetchone()
        assert row["category_raw"] == "Mejor película"
        assert connection.execute(
            "SELECT COUNT(*) FROM reported_award"
        ).fetchone()[0] == 1

    def test_a_page_that_claimed_nothing_leaves_no_row(self, tmp_path):
        """Distinct from a zero: 'not registered' is not 'said none'."""
        movie = minimal_movie()
        movie["data_quality"]["reported_by_source"]["award_categories"] = None
        path = _tmp_db()
        import_db.import_document(minimal_document([movie]), path)
        connection = db.connect(path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM reported_award"
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT reported_awards FROM movie"
            ).fetchone()[0] == 1
        finally:
            connection.close()


class TestRefusingToGuess:
    def test_an_unknown_category_stops_the_import(self, tmp_path):
        """A new award means somebody has to say what its credit column holds."""
        movie = minimal_movie()
        movie["goya"]["nominations"][1]["category"] = "Mejor invento del año"
        movie["goya"]["nominations"][1]["category_raw"] = "Mejor invento del año"
        report = import_db.import_document(
            minimal_document([movie]), tmp_path / "goya.db"
        )
        assert not report.ok
        assert any("credited_kind" in problem for problem in report.problems)

    def test_the_nominations_of_that_category_are_skipped_not_guessed(self, tmp_path):
        movie = minimal_movie()
        movie["goya"]["nominations"][1]["category"] = "Mejor invento del año"
        movie["goya"]["nominations"][1]["category_raw"] = "Mejor invento del año"
        report = import_db.import_document(
            minimal_document([movie]), tmp_path / "goya.db"
        )
        assert report.nominations == 1  # only Mejor película
        assert any("omitida" in problem for problem in report.problems)

    def test_the_problems_are_saved_with_the_import(self, tmp_path):
        movie = minimal_movie()
        movie["goya"]["nominations"][1]["category"] = "Mejor invento"
        movie["goya"]["nominations"][1]["category_raw"] = "Mejor invento"
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document([movie]), path)
        connection = db.connect(path)
        try:
            notes = connection.execute("SELECT notes FROM import_run").fetchone()[0]
            assert "credited_kind" in notes
        finally:
            connection.close()


class TestReproducibility:
    def test_importing_twice_gives_the_same_rows(self, tmp_path):
        """ADR-035: ids are assigned in sorted order, not by SQLite."""
        first = tmp_path / "a.db"
        second = tmp_path / "b.db"
        import_db.import_document(minimal_document(), first)
        import_db.import_document(minimal_document(), second)

        def signature(path):
            connection = db.connect(path)
            try:
                rows = connection.execute(
                    "SELECT id, movie_id, edition_id, category_id, category_raw, "
                    "won, note, credit_fingerprint FROM nomination ORDER BY id"
                ).fetchall()
                people = connection.execute(
                    "SELECT id, name FROM person ORDER BY id"
                ).fetchall()
                return [tuple(r) for r in rows] + [tuple(r) for r in people]
            finally:
                connection.close()

        assert signature(first) == signature(second)

    def test_movie_ids_follow_the_slug_order(self, tmp_path):
        """Ordering is explicit, so it cannot drift between runs."""
        movies = [minimal_movie("zzz"), minimal_movie("aaa"), minimal_movie("mmm")]
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document(movies), path)
        connection = db.connect(path)
        try:
            slugs = [
                row["slug"] for row in connection.execute("SELECT slug FROM movie")
            ]
            assert slugs == ["aaa", "mmm", "zzz"]
        finally:
            connection.close()

    def test_reimporting_replaces_rather_than_appends(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document(), path)
        import_db.import_document(minimal_document(), path)
        connection = db.connect(path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM movie").fetchone()[0] == 1
            assert (
                connection.execute("SELECT COUNT(*) FROM nomination").fetchone()[0] == 2
            )
        finally:
            connection.close()

    def test_a_failure_rolls_the_whole_import_back(self, tmp_path):
        """Not atomic with respect to the old file, but atomic within itself.

        The trigger has to be something the database refuses. A missing film page
        is not: it stores as NULL, which is a meaningful answer (ADR-014). A
        nomination pointing at no film is the real thing."""
        path = tmp_path / "goya.db"
        broken = minimal_movie()
        broken["goya"]["nominations"] = [
            {
                "edition": 999,  # no such edition
                "ceremony_year": 3000,
                "category": "Mejor película",
                "category_raw": "Mejor película",
                "credited": ["Una pelicula"],
                "won": False,
                "note": None,
            }
        ]
        with pytest.raises(sqlite3.IntegrityError):
            import_db.import_document(minimal_document([broken]), path)

        connection = db.connect(path)
        try:
            for table in ("movie", "nomination", "person", "import_run"):
                count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count == 0, f"{table} tiene {count} filas tras el rollback"
        finally:
            connection.close()

    def test_a_rolled_back_import_leaves_a_usable_empty_database(self, tmp_path):
        """The file is deleted before the schema is written, so recovery means
        re-running the import, not recovering the previous file."""
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document(), path)
        broken = minimal_movie()
        broken["slug"] = "rotta"
        broken["goya"]["nominations"] = []
        broken["data_quality"]["reported_by_source"]["awards"] = "muchos"
        with pytest.raises(sqlite3.IntegrityError):
            import_db.import_document(minimal_document([broken]), path)

        connection = db.connect(path)
        try:
            # Schema intact, rows gone. Re-importing is the recovery.
            assert connection.execute(
                "SELECT COUNT(*) FROM movie"
            ).fetchone()[0] == 0
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            connection.close()

    def test_an_empty_document_imports_an_empty_database(self, tmp_path):
        path = tmp_path / "goya.db"
        report = import_db.import_document(minimal_document([]), path)
        connection = db.connect(path)
        try:
            assert report.nominations == 0
            assert connection.execute("SELECT COUNT(*) FROM movie").fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM movie_totals"
            ).fetchone()[0] == 0
        finally:
            connection.close()


class TestProvenance:
    def test_the_json_metadata_is_copied(self, imported):
        connection = imported().connection
        row = connection.execute("SELECT * FROM dataset_meta").fetchone()
        assert row["schema_version"] == 3
        assert row["source"] == "https://www.premiosgoya.com"
        assert row["generated_at"] == "2026-01-01T00:00:00Z"

    def test_the_run_records_what_landed(self, imported):
        connection = imported().connection
        row = connection.execute("SELECT * FROM import_run").fetchone()
        assert row["status"] == "ok"
        assert row["movies"] == 1
        assert row["nominations"] == 2
        assert row["awards"] == 1
        assert row["persons"] == 2

    def test_a_document_without_bytes_has_an_empty_hash(self, tmp_path):
        report = import_db.import_document(minimal_document(), tmp_path / "goya.db")
        connection = db.connect(tmp_path / "goya.db")
        try:
            assert connection.execute(
                "SELECT json_sha256 FROM import_run"
            ).fetchone()[0] == ""
            assert report.ok
        finally:
            connection.close()

    def test_dataset_meta_holds_a_single_row(self, imported):
        connection = imported().connection
        assert connection.execute("SELECT COUNT(*) FROM dataset_meta").fetchone()[0] == 1


class TestImportFile:
    def test_a_missing_file_explains_itself(self, tmp_path):
        with pytest.raises(DocumentNotImportable) as error:
            import_db.import_file(tmp_path / "nada.json", tmp_path / "goya.db")
        assert "no existe" in str(error.value)

    @needs_dataset
    def test_it_reads_the_real_file(self, tmp_path):
        report = import_db.import_file(DATASET, tmp_path / "goya.db")
        assert report.ok
        assert report.movies == 1678


class TestSeparation:
    def test_the_scraper_does_not_import_the_database(self):
        """ADR-036: the scraper must never need sqlite3."""
        import subprocess
        import sys

        code = (
            "import sys; import goya_scraper.run, goya_scraper.storage; "
            "assert 'goya_scraper.db' not in sys.modules, sorted("
            "m for m in sys.modules if m.startswith('goya_scraper')); "
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=pathlib.Path(__file__).resolve().parents[1],
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

    def test_the_report_describes_the_database_not_our_intentions(self, imported):
        """Counts come from asking the database, not from counting as we go."""
        with imported() as result:
            assert result.path.exists()
            for table in (
                "person",
                "person_alias",
                "movie_credit",
                "movie_country",
            ):
                actual = result.connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                field = {
                    "person": "persons",
                    "person_alias": "person_aliases",
                    "movie_credit": "movie_credits",
                    "movie_country": "movie_countries",
                }[table]
                assert getattr(result.report, field) == actual, table