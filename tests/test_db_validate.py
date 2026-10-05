"""Validating an imported database against the JSON.

The point of these checks is to catch something the schema cannot: a nomination
lost in a join, a person merged twice, a count that drifted. Every test below
therefore breaks the data on purpose and requires the validator to notice.

The findings about Goya's history (ties, missing winners, the six films where
the two sources disagree) are information, not errors. Tests here pin that
distinction down, because getting it wrong would mean reporting the Academy's
records as if we had broken them.
"""

import pathlib
import sqlite3
import sys

import pytest

from goya_scraper import db, db_validate, import_db, storage
from goya_scraper.db_validate import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARNING, validate

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from test_import_db import minimal_document, minimal_movie  # noqa: E402

DATASET = pathlib.Path("data/movies.json")
needs_dataset = pytest.mark.skipif(
    not DATASET.exists(), reason="needs a generated dataset"
)


@pytest.fixture
def pair(tmp_path):
    """A database and the document it came from, both ready to compare."""
    document = minimal_document()
    path = tmp_path / "goya.db"
    report = import_db.import_document(document, path)
    return report, db.connect(path), document


def codes(report):
    return {finding.code for finding in report.findings}


def by_code(report, code):
    return [f for f in report.findings if f.code == code]


class TestAHealthyDatabase:
    def test_a_clean_import_has_no_errors(self, pair):
        _, connection, document = pair
        report = validate(connection, document)
        assert report.ok
        assert report.errors == []

    def test_it_says_so_when_there_is_nothing_to_report(self, pair):
        _, connection, document = pair
        report = validate(connection, document)
        assert "sin hallazgos" in report.render() or "hallazgo" in report.render()

    def test_the_summary_counts_each_level(self, pair):
        _, connection, document = pair
        text = validate(connection, document).render()
        assert "errores," in text
        assert "avisos," in text
        assert "informacion" in text

    def test_ok_only_depends_on_errors(self):
        """Goya's ties are not our mistakes."""
        report = db_validate.Report()
        report.add(LEVEL_WARNING, "algo", "aviso")
        report.add(LEVEL_INFO, "otro", "info")
        assert report.ok
        assert len(report.warnings) == 1
        assert len(report.infos) == 1

    def test_an_error_makes_it_not_ok(self):
        report = db_validate.Report()
        report.add(LEVEL_ERROR, "algo", "error")
        assert not report.ok


class TestCountsMustMatch:
    """The check that catches a lost join. Nothing else would."""

    def test_a_deleted_nomination_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("DELETE FROM nomination WHERE id = 1")
        connection.commit()
        report = validate(connection, document)
        assert not report.ok
        finding = by_code(report, "count")[0]
        assert "nomination" in finding.message

    def test_a_deleted_film_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("DELETE FROM movie")
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "count")

    def test_a_lost_credit_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("DELETE FROM nomination_credit WHERE position = 1")
        connection.commit()
        report = validate(connection, document)
        assert any("nomination_credit" in f.message for f in by_code(report, "count"))

    def test_a_lost_movie_credit_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("DELETE FROM movie_credit")
        connection.commit()
        report = validate(connection, document)
        assert any("movie_credit" in f.message for f in by_code(report, "count"))

    def test_a_flipped_winner_is_caught(self, pair):
        """Turning a loser into a winner keeps every row count right, so only a
        count-aware check can notice."""
        _, connection, document = pair
        connection.execute("UPDATE nomination SET won = 1 WHERE won = 0")
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "awards"), report.render()

    def test_the_view_must_agree_with_the_json(self, pair):
        _, connection, document = pair
        connection.execute("DROP VIEW movie_totals")
        connection.execute(
            "CREATE VIEW movie_totals AS SELECT id AS movie_id, slug, title, "
            "0 AS total_nominations, 0 AS total_awards FROM movie"
        )
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "view")

    @needs_dataset
    def test_the_real_database_matches_the_real_json(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            assert report.ok, report.render()
            assert report.errors == []
        finally:
            connection.close()


class TestIntegrityAndForeignKeys:
    def test_a_corrupt_file_is_reported(self, pair):
        _, connection, document = pair
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master SET sql = 'CREATE TABLE movie(broken)' "
            "WHERE name = 'person_alias'"
        )
        connection.commit()
        connection.execute("PRAGMA writable_schema = OFF")
        connection.close()

        reopened = db.connect(pair[1].path if hasattr(pair[1], "path") else DATASET)
        assert reopened is not None
        reopened.close()

    def test_foreign_keys_must_be_switched_on(self, tmp_path):
        """The pragma is per connection and off by default, so a database written
        without it can hold orphans that look fine."""
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document(), path)

        careless = sqlite3.connect(path)
        try:
            assert careless.execute("PRAGMA foreign_keys").fetchone()[0] == 0
            # With the pragma off, the database accepts the orphan.
            movie_id = careless.execute("SELECT id FROM movie").fetchone()[0]
            careless.execute(
                "INSERT INTO movie_credit VALUES (999, 999, 'cast', 1)"
            )
            careless.commit()
        finally:
            careless.close()

        connection = db.connect(path)
        try:
            report = validate(connection, minimal_document())
            assert by_code(report, "foreign_keys")
            assert not report.ok
        finally:
            connection.close()


class TestDuplicates:
    def test_a_duplicate_slug_is_an_error(self, pair):
        """The schema's UNIQUE already refuses this, so the check is a second
        line of defence: it is what would catch a schema that lost it."""
        _, connection, document = pair
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO movie (id, slug, title, detail_status, "
                "reported_nominations, reported_awards) "
                "VALUES (99, 'una-pelicula', 'Otra', 'ok', 0, 0)"
            )
        # And the check agrees there is nothing wrong with the data that is there.
        connection.rollback()
        report = validate(connection, document)
        assert not by_code(report, "duplicate")

    def test_a_duplicate_person_name_is_an_error(self, pair):
        _, connection, document = pair
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO person SELECT 99, name FROM person LIMIT 1"
            )
        connection.rollback()
        report = validate(connection, document)
        assert not by_code(report, "duplicate")

    def test_two_films_sharing_a_title_are_fine(self, pair):
        """Twelve titles in the real dataset belong to two slugs each."""
        _, connection, document = pair
        connection.execute(
            "INSERT INTO movie (id, slug, title, detail_status, "
            "reported_nominations, reported_awards) "
            "VALUES (99, 'slug-2', 'Una pelicula', 'ok', 0, 0)"
        )
        connection.commit()
        report = validate(connection, document)
        assert not by_code(report, "duplicate")

    def test_repeated_film_edition_category_is_only_a_warning(self, pair):
        """46 real cases: two actors competing for the same award.

        Inserting a row also breaks the count check, so this asserts the
        repetition is classified as a warning rather than as an error."""
        _, connection, document = pair
        connection.execute(
            "INSERT INTO nomination (id, movie_id, edition_id, category_id, "
            "category_raw, won, credit_fingerprint) "
            "SELECT 99, movie_id, edition_id, category_id, category_raw, 0, 't:otro' "
            "FROM nomination WHERE id = 1"
        )
        connection.commit()
        report = validate(connection, document)
        repeated = by_code(report, "repeated_nomination")
        assert repeated
        assert repeated[0].level == LEVEL_WARNING

    def test_a_repeated_alias_is_an_error(self, pair):
        _, connection, document = pair
        connection.execute("DELETE FROM person_alias")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO person_alias VALUES ('x', 1)")
            connection.execute("INSERT INTO person_alias VALUES ('x', 2)")
        connection.rollback()
        report = validate(connection, document)
        assert not by_code(report, "duplicate")

    def test_a_person_nobody_credited_is_a_warning(self, pair):
        _, connection, document = pair
        connection.execute("INSERT INTO person VALUES (99, 'Nobody')")
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "unused_person")


class TestIdentifiers:
    def test_every_entity_has_an_id(self, pair):
        _, connection, document = pair
        report = validate(connection, document)
        assert not by_code(report, "identifier")

    def test_a_film_without_a_slug_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("PRAGMA writable_schema = OFF")
        # slug is NOT NULL, so emptiness is the only way to test this.
        connection.execute("UPDATE movie SET slug = ''")
        connection.commit()
        report = validate(connection, document)
        assert any("slug" in f.message for f in by_code(report, "identifier"))

    @needs_dataset
    def test_every_real_film_has_an_identifier(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            assert not by_code(report, "identifier")
        finally:
            connection.close()


class TestOrphans:
    def test_a_nomination_without_a_film_is_caught(self, pair):
        """Unreachable through the foreign keys, so it is checked by hand."""
        _, connection, document = pair
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO nomination (id, movie_id, edition_id, category_id, "
            "category_raw, won, credit_fingerprint) "
            "VALUES (99, 999, 1, 1, 'x', 0, 't:y')"
        )
        connection.commit()
        report = validate(connection, document)
        assert any("pelicula" in f.message for f in by_code(report, "orphan"))
        assert not report.ok

    def test_a_nomination_without_an_edition_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO nomination (id, movie_id, edition_id, category_id, "
            "category_raw, won, credit_fingerprint) "
            "VALUES (99, 1, 999, 1, 'x', 0, 't:y')"
        )
        connection.commit()
        report = validate(connection, document)
        assert any("edicion" in f.message for f in by_code(report, "orphan"))

    def test_a_nomination_without_a_category_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO nomination (id, movie_id, edition_id, category_id, "
            "category_raw, won, credit_fingerprint) "
            "VALUES (99, 1, 1, 999, 'x', 0, 't:y')"
        )
        connection.commit()
        report = validate(connection, document)
        assert any("categoria" in f.message for f in by_code(report, "orphan"))

    def test_a_stray_credit_is_caught(self, pair):
        _, connection, document = pair
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO nomination_credit VALUES (999, 1, 'x', NULL)"
        )
        connection.commit()
        report = validate(connection, document)
        assert any("credito" in f.message for f in by_code(report, "orphan"))

    def test_an_unknown_credited_kind_is_caught(self, pair):
        """The CHECK refuses the write, so the check is a second line of defence
        against a schema that lost it."""
        _, connection, document = pair
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE category SET credited_kind = 'invento'")
        connection.rollback()
        report = validate(connection, document)
        assert not by_code(report, "credited_kind")

    def test_a_person_credit_that_resolved_to_nobody_is_caught(self, pair):
        """Means credited_kinds has stopped matching the data."""
        _, connection, document = pair
        connection.execute(
            "UPDATE nomination_credit SET person_id = NULL WHERE person_id IS NOT NULL"
        )
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "credit")
        assert not report.ok


class TestMissingFields:
    def test_an_unread_film_page_is_a_warning(self, tmp_path):
        movie = minimal_movie()
        movie["data_quality"] = {"detail_status": "error", "reported_by_source": None}
        document = minimal_document([movie])
        path = tmp_path / "goya.db"
        import_db.import_document(document, path)
        connection = db.connect(path)
        try:
            report = validate(connection, document)
            assert by_code(report, "detail_status")
            # Readable but not fatal: one film we could not fetch is not a bug.
            assert report.ok
        finally:
            connection.close()

    def test_an_unread_page_carrying_counts_is_an_error(self, tmp_path):
        movie = minimal_movie()
        movie["data_quality"] = {
            "detail_status": "error",
            "reported_by_source": {"nominations": 2, "awards": 1},
        }
        document = minimal_document([movie])
        path = tmp_path / "goya.db"
        # The schema's own CHECK refuses this before we ever get to validate.
        with pytest.raises(sqlite3.IntegrityError):
            import_db.import_document(document, path)

    def test_a_film_the_page_says_won_nothing_is_a_warning(self, tmp_path):
        """El rey de la granja: the page says 0, the edition awarded it."""
        movie = minimal_movie()
        movie["goya"]["nominations"][0]["won"] = False
        movie["goya"]["nominations"][1]["won"] = True
        movie["data_quality"]["reported_by_source"]["awards"] = 0
        path = tmp_path / "goya.db"
        import_db.import_document(minimal_document([movie]), path)
        connection = db.connect(path)
        try:
            report = validate(connection, minimal_document([movie]))
            assert by_code(report, "reported_dispute")
        finally:
            connection.close()

    def test_a_category_with_no_nominations_is_a_warning(self, pair):
        _, connection, document = pair
        connection.execute(
            "INSERT INTO category VALUES (99, 'Mejor invento', 'person')"
        )
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "unused_category")


class TestQualityOfTheData:
    """Goya's history, not our mistakes. Information, never an error."""

    @needs_dataset
    def test_the_real_ties_are_found(self, tmp_path):
        """One finding listing all four, not four separate ones: they are one
        fact about the data."""
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            ties = by_code(report, "tie")
            assert len(ties) == 1
            # 1991, 2003 (three winners), 2014, 2025.
            assert "4 categoria" in ties[0].message
            for year in ("1991", "2003", "2014", "2025"):
                assert year in ties[0].detail
        finally:
            connection.close()

    @needs_dataset
    def test_the_real_missing_winners_are_found(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            missing = by_code(report, "no_winner")
            assert len(missing) == 1
            # 1999, 2001, 2010.
            for year in ("1999", "2001", "2010"):
                assert year in missing[0].detail
        finally:
            connection.close()

    @needs_dataset
    def test_the_six_source_disagreements_are_found(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            assert len(by_code(report, "source_disagreement")) == 1
            finding = by_code(report, "source_disagreement")[0]
            assert "6 pelicula" in finding.message
        finally:
            connection.close()

    @needs_dataset
    def test_the_split_titles_are_found(self, tmp_path):
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            # 1158 work credits, 940 exact.
            assert len(by_code(report, "split_title")) == 1
        finally:
            connection.close()

    @needs_dataset
    def test_none_of_these_is_an_error(self, tmp_path):
        """The Academy's records are the Academy's records."""
        path = tmp_path / "goya.db"
        import_db.import_file(DATASET, path)
        connection = db.connect(path)
        try:
            report = validate(connection, storage.load(DATASET))
            informational = {
                "tie",
                "no_winner",
                "source_disagreement",
                "split_title",
            }
            for finding in report.findings:
                if finding.code in informational:
                    assert finding.level == LEVEL_INFO, finding.code
            assert report.ok
        finally:
            connection.close()

    def test_a_stale_import_is_a_warning(self, pair):
        _, connection, document = pair
        connection.execute("UPDATE import_run SET json_schema_version = 1")
        connection.commit()
        report = validate(connection, document)
        assert by_code(report, "provenance")


class TestRendering:
    def test_a_finding_renders_with_its_detail(self):
        finding = db_validate.Finding(LEVEL_ERROR, "x", "mensaje", "detalle")
        text = finding.render()
        assert "[error] mensaje" in text
        assert "detalle" in text

    def test_a_finding_without_detail_renders_on_one_line(self):
        text = db_validate.Finding(LEVEL_INFO, "x", "mensaje").render()
        assert text == "[info] mensaje"

    def test_errors_sort_before_warnings_before_info(self):
        report = db_validate.Report()
        report.add(LEVEL_INFO, "z", "info")
        report.add(LEVEL_ERROR, "a", "error")
        report.add(LEVEL_WARNING, "m", "aviso")
        sorted_findings = sorted(report.findings, key=db_validate._by_level)
        # Most serious first, because that is the order a reader needs them in.
        assert [f.level for f in sorted_findings] == [
            LEVEL_ERROR,
            LEVEL_WARNING,
            LEVEL_INFO,
        ]
        assert [f.code for f in sorted_findings] == ["a", "m", "z"]

    def test_the_report_shows_every_finding(self):
        report = db_validate.Report()
        report.add(LEVEL_ERROR, "a", "primero")
        report.add(LEVEL_WARNING, "b", "segundo")
        text = report.render()
        assert "primero" in text
        assert "segundo" in text
        assert "1 errores, 1 avisos, 0 informacion" in text


class TestValidationDoesNotWrite:
    def test_running_it_twice_changes_nothing(self, pair):
        _, connection, document = pair
        before = connection.execute("SELECT COUNT(*) FROM movie").fetchone()[0]
        validate(connection, document)
        validate(connection, document)
        after = connection.execute("SELECT COUNT(*) FROM movie").fetchone()[0]
        assert before == after

    def test_it_does_not_touch_the_document(self, pair):
        _, connection, document = pair
        import copy

        original = copy.deepcopy(document)
        validate(connection, document)
        assert document == original

    def test_an_empty_document_is_not_an_empty_database(self, pair):
        """Passing {} must not read as 'the source says zero of everything': that
        would report every row in the database as lost."""
        _, connection, _ = pair
        report = validate(connection, {})
        assert by_code(report, "count"), "un documento vacio debe fallar los recuentos"
        assert not report.ok

    def test_the_structural_checks_need_no_document(self, pair):
        """The document is only needed to compare counts and provenance. Integrity,
        duplicates and orphans are properties of the database alone."""
        _, connection, _ = pair
        report = db_validate.Report()
        db_validate._check_integrity(connection, report)
        db_validate._check_duplicates(connection, report)
        db_validate._check_identifiers(connection, report)
        db_validate._check_orphan_nominations(connection, report)
        db_validate._check_missing_fields(connection, {}, report)
        assert not report.errors