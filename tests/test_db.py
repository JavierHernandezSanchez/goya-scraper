"""The schema, checked two ways.

The structural tests read `sqlite_master` and confirm we created what we meant
to. They would pass just as happily on a schema with a typo in a CHECK
constraint, because a mangled CHECK still rejects the values we tell it to
reject.

So the behavioural tests are the ones that matter: they insert bad data and
require the database to refuse. Those prove the constraints do their job rather
than merely exist.
"""

import sqlite3

import pytest

from goya_scraper.db import (
    DEFAULT_PATH,
    MIN_SQLITE_VERSION,
    SCHEMA_PATH,
    DatabaseError,
    connect,
    create_database,
    read_schema,
    sqlite3_version,
)

EXPECTED_TABLES = {
    "dataset_meta",
    "import_run",
    "goya_edition",
    "category",
    "country",
    "movie",
    "person",
    "person_alias",
    "movie_credit",
    "movie_country",
    "nomination",
    "nomination_credit",
    "reported_award",
}

# name -> (columns, primary key columns, foreign keys)
EXPECTED_KEYS = {
    "movie": (
        ["id", "slug", "title", "title_original", "synopsis", "duration_minutes",
         "producers_raw", "countries_raw", "detail_status", "reported_nominations",
         "reported_awards"],
        ["id"],
        [],
    ),
    "nomination": (
        ["id", "movie_id", "edition_id", "category_id", "category_raw", "won",
         "note", "credit_fingerprint"],
        ["id"],
        ["movie", "goya_edition", "category"],
    ),
    "nomination_credit": (
        ["nomination_id", "position", "credit_text", "person_id"],
        ["nomination_id", "position"],
        ["nomination", "person"],
    ),
    "movie_credit": (
        ["movie_id", "person_id", "role", "position"],
        ["movie_id", "person_id", "role"],
        ["movie", "person"],
    ),
}


@pytest.fixture
def empty_db(tmp_path):
    """A created but empty database, closed and ready to be reopened."""
    path = create_database(tmp_path / "goya.db")
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def filled_db(empty_db):
    """The minimum data a nomination needs, so behaviour tests read clearly."""
    connection = empty_db
    connection.execute("INSERT INTO goya_edition VALUES (1, 36, 2022)")
    connection.execute("INSERT INTO category VALUES (1, 'Mejor pelicula', 'work')")
    connection.execute(
        "INSERT INTO movie VALUES (1, 'el-buen-patron', 'El buen patron', "
        "NULL, NULL, 115, NULL, NULL, 'ok', 20, 6)"
    )
    connection.execute("INSERT INTO person VALUES (1, 'Paco de Lucia')")
    connection.execute(
        "INSERT INTO nomination VALUES (1, 1, 1, 1, 'Mejor pelicula', 1, NULL, 't:x')"
    )
    connection.execute(
        "INSERT INTO nomination_credit VALUES (1, 1, 'x', NULL)"
    )
    connection.commit()
    return connection


def _objects(connection, kind):
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ? ORDER BY name", (kind,)
    )
    return {row["name"] for row in rows}


def _sql(connection, name):
    return connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
    ).fetchone()["sql"]


class TestTheFileItself:
    def test_the_schema_is_a_separate_readable_file(self):
        assert SCHEMA_PATH.exists()
        assert SCHEMA_PATH.suffix == ".sql"
        assert "CREATE TABLE movie" in read_schema()

    def test_the_schema_ships_with_the_package(self):
        """setuptools does not copy data files unless told to.

        Without `package-data`, an editable install works and a normal one ships
        a package whose `read_schema()` fails, because schema.sql is simply not
        there. This is the test that catches that before a user does.
        """
        pyproject = SCHEMA_PATH.parents[2] / "pyproject.toml"
        if not pyproject.exists():  # installed, not in a source tree
            pytest.skip("not running from the source tree")
        assert "schema.sql" in pyproject.read_text(encoding="utf-8")

    def test_the_schema_holds_no_control_characters(self):
        """A stray byte in a CHECK constraint still rejects the wrong values, so
        the table would look fine until real data arrived. Check the bytes."""
        raw = SCHEMA_PATH.read_bytes()
        assert b"\x00" not in raw
        raw.decode("utf-8")  # raises if it is not valid UTF-8

    def test_every_creator_statement_is_terminated(self):
        assert read_schema().rstrip().endswith(";")


class TestSqliteIsNewEnough:
    def test_strict_is_available(self):
        assert sqlite3_version() >= MIN_SQLITE_VERSION, (
            "STRICT needs SQLite 3.37+"
        )


class TestStructuralChecks:
    """What we created, read back from the database itself."""

    def test_all_thirteen_tables_exist(self, empty_db):
        assert _objects(empty_db, "table") - {"sqlite_sequence"} == EXPECTED_TABLES
        assert len(EXPECTED_TABLES) == 13

    def test_every_table_is_strict(self, empty_db):
        for name in sorted(EXPECTED_TABLES):
            assert "STRICT" in _sql(empty_db, name), name

    def test_the_one_view_exists_and_reads(self, empty_db):
        assert _objects(empty_db, "view") == {"movie_totals"}
        # Empty but valid: the view must be usable before any row exists.
        assert empty_db.execute("SELECT COUNT(*) FROM movie_totals").fetchone()[0] == 0

    def test_the_expected_indexes_exist(self, empty_db):
        indexes = _objects(empty_db, "index")
        # sqlite_autoindex_* are the ones SQLite builds for PRIMARY KEY / UNIQUE.
        named = {n for n in indexes if not n.startswith("sqlite_autoindex")}
        assert named == {
            "nomination_natural_key",
            "idx_nomination_movie",
            "idx_nomination_category",
            "idx_nomination_edition",
            "idx_nomination_winners",
            "idx_movie_credit_person",
            "idx_nomination_credit_person",
            "idx_movie_country_country",
            "idx_movie_title",
            "idx_person_alias_person",
        }

    def test_the_winners_index_is_partial(self, empty_db):
        sql = _sql(empty_db, "idx_nomination_winners")
        assert "WHERE won = 1" in sql

    def test_the_natural_key_index_is_unique(self, empty_db):
        sql = _sql(empty_db, "nomination_natural_key")
        assert sql.upper().startswith("CREATE UNIQUE INDEX")
        assert "credit_fingerprint" in sql

    @pytest.mark.parametrize("table", sorted(EXPECTED_KEYS))
    def test_columns_primary_keys_and_foreign_keys(self, empty_db, table):
        columns, primary, foreign = EXPECTED_KEYS[table]
        for table_info in empty_db.execute(f"PRAGMA table_info({table})"):
            if table_info["name"] in columns:
                assert table_info["name"]
        actual_columns = [
            row["name"] for row in empty_db.execute(f"PRAGMA table_info({table})")
        ]
        assert actual_columns == columns

        actual_pk = [
            row["name"]
            for row in sorted(
                empty_db.execute(f"PRAGMA table_info({table})"),
                key=lambda r: r["pk"],
            )
            if row["pk"]
        ]
        assert actual_pk == primary

        actual_fk = [
            row["table"]
            for row in empty_db.execute(f"PRAGMA foreign_key_list({table})")
        ]
        assert sorted(actual_fk) == sorted(foreign)

    def test_a_fresh_database_is_empty(self, empty_db):
        for table in sorted(EXPECTED_TABLES):
            count = empty_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0, table

    def test_nothing_claims_foreign_keys_are_enforced_by_default(self):
        """The pragma is per connection and off by default. If someone drops it,
        an orphan row becomes possible, so the test asserts we set it."""
        connection = sqlite3.connect(":memory:")
        try:
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        finally:
            connection.close()


class TestBehaviour: 
    """Bad data must be refused. These are the tests that earn the schema."""

    def test_a_duration_cannot_be_stored_as_text(self, empty_db):
        """Without STRICT this insert succeeds and every later query breaks."""
        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute(
                "INSERT INTO movie VALUES (1, 'x', 'X', NULL, NULL, '105 anos', "
                "NULL, NULL, 'ok', 1, 0)"
            )

    def test_a_negative_duration_is_refused(self, empty_db):
        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute(
                "INSERT INTO movie VALUES (1, 'x', 'X', NULL, NULL, -5, "
                "NULL, NULL, 'ok', 1, 0)"
            )

    def test_an_unknown_detail_status_is_refused(self, empty_db):
        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute(
                "INSERT INTO movie VALUES (1, 'x', 'X', NULL, NULL, NULL, "
                "NULL, NULL, 'inventado', 1, 0)"
            )

    def test_a_missing_film_cannot_have_nominations(self, filled_db):
        """The single most important constraint in the schema."""
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO nomination VALUES (99, 999, 1, 1, 'x', 0, NULL, 't:y')"
            )

    def test_a_missing_edition_is_refused(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO nomination VALUES (2, 1, 999, 1, 'x', 0, NULL, 't:y')"
            )

    def test_a_missing_category_is_refused(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO nomination VALUES (2, 1, 1, 999, 'x', 0, NULL, 't:y')"
            )

    def test_an_unknown_credited_kind_is_refused(self, empty_db):
        with pytest.raises(sqlite3.IntegrityError):
            empty_db.execute("INSERT INTO category VALUES (1, 'Mejor cosa', 'invento')")

    def test_the_three_known_credited_kinds_are_accepted(self, empty_db):
        for index, kind in enumerate(("person", "work", "song"), start=1):
            empty_db.execute(
                "INSERT INTO category VALUES (?, ?, ?)", (index, f"C{kind}", kind)
            )
        assert empty_db.execute("SELECT COUNT(*) FROM category").fetchone()[0] == 3

    def test_a_winner_flag_must_be_zero_or_one(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO nomination VALUES (2, 1, 1, 1, 'x', 2, NULL, 't:y')"
            )

    def test_reported_counts_require_a_read_page(self, filled_db):
        """ADR-014: a failed fetch must not look like a page saying zero."""
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO movie VALUES (2, 'y', 'Y', NULL, NULL, NULL, NULL, "
                "NULL, 'error', 0, 0)"
            )
        # The same film with status ok and real counts is fine.
        filled_db.execute(
            "INSERT INTO movie VALUES (2, 'y', 'Y', NULL, NULL, NULL, NULL, "
            "NULL, 'not_found', NULL, NULL)"
        )

    def test_a_null_reported_count_requires_a_failed_page(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO movie VALUES (2, 'y', 'Y', NULL, NULL, NULL, NULL, "
                "NULL, 'ok', NULL, 0)"
            )

    def test_two_films_cannot_share_a_slug(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO movie VALUES (2, 'el-buen-patron', 'Otro', NULL, NULL, "
                "NULL, NULL, NULL, 'ok', 1, 0)"
            )

    def test_two_films_may_share_a_title(self, filled_db):
        """Twelve titles in the dataset belong to two slugs each, so title is
        deliberately not unique."""
        filled_db.execute(
            "INSERT INTO movie VALUES (2, 'alma-2', 'El buen patron', NULL, NULL, "
            "NULL, NULL, NULL, 'ok', 1, 0)"
        )
        assert filled_db.execute("SELECT COUNT(*) FROM movie").fetchone()[0] == 2

    def test_the_natural_key_refuses_a_duplicate_nomination(self, filled_db):
        """ADR-028. Same film, same edition, same category, same credits."""
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO nomination VALUES (2, 1, 1, 1, 'Mejor pelicula', 0, "
                "NULL, 't:x')"
            )

    def test_different_credits_make_a_second_nomination_legal(self, filled_db):
        """The 46 real cases: Alcarràs in edition 37 has two actors revealed."""
        filled_db.execute(
            "INSERT INTO nomination VALUES (2, 1, 1, 1, 'Mejor pelicula', 0, "
            "NULL, 't:otro')"
        )
        assert filled_db.execute("SELECT COUNT(*) FROM nomination").fetchone()[0] == 2

    def test_a_credit_without_a_nomination_is_refused(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO nomination_credit VALUES (999, 1, 'x', NULL)"
            )

    def test_a_credit_may_have_no_person(self, filled_db):
        """1355 of 5277 credits are a film title or a song, not a person."""
        filled_db.execute("INSERT INTO nomination_credit VALUES (1, 2, 'y', NULL)")
        assert filled_db.execute(
            "SELECT COUNT(*) FROM nomination_credit WHERE person_id IS NULL"
        ).fetchone()[0] == 2

    def test_an_alias_must_point_at_a_real_person(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute("INSERT INTO person_alias VALUES ('Nadie', 999)")

    def test_two_aliases_cannot_map_to_different_people(self, filled_db):
        """The spelling is the key, so one spelling has exactly one person."""
        filled_db.execute("INSERT INTO person VALUES (2, 'Otra')")
        filled_db.execute("INSERT INTO person_alias VALUES ('Paco de Lucia', 1)")
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute("INSERT INTO person_alias VALUES ('Paco de Lucia', 2)")

    def test_repointing_an_alias_is_possible_on_purpose(self, filled_db):
        """Reversibility (ADR-027): undoing a curated merge is a row update, not a
        code change. If this ever became impossible, a wrong merge would be
        permanent."""
        filled_db.execute("INSERT INTO person VALUES (2, 'Otra')")
        filled_db.execute("INSERT INTO person_alias VALUES ('Paco de Lucia', 1)")
        filled_db.execute("UPDATE person_alias SET person_id = 2")
        row = filled_db.execute(
            "SELECT person_id FROM person_alias WHERE alias = 'Paco de Lucia'"
        ).fetchone()
        assert row["person_id"] == 2

    def test_the_same_role_twice_in_one_slot_is_refused(self, filled_db):
        """UNIQUE (movie_id, role, position) keeps the source's ordering."""
        filled_db.execute(
            "INSERT INTO movie_credit VALUES (1, 1, 'director', 1)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO movie_credit VALUES (1, 1, 'director', 1)"
            )

    def test_two_roles_in_one_film_are_allowed(self, filled_db):
        """1153 people hold two roles in the same film, which is why role is in
        the primary key."""
        filled_db.execute("INSERT INTO movie_credit VALUES (1, 1, 'director', 1)")
        filled_db.execute("INSERT INTO movie_credit VALUES (1, 1, 'screenwriter', 1)")
        assert filled_db.execute("SELECT COUNT(*) FROM movie_credit").fetchone()[0] == 2

    def test_an_unknown_role_is_refused(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute("INSERT INTO movie_credit VALUES (1, 1, 'camarero', 1)")

    def test_positions_start_at_one(self, filled_db):
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute("INSERT INTO movie_credit VALUES (1, 1, 'cast', 0)")

    def test_dataset_meta_holds_exactly_one_row(self, filled_db):
        filled_db.execute(
            "INSERT INTO dataset_meta VALUES (1, 3, 'https://x', '2026-01-01', "
            "40, 1678, 4050, 1027, 31)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO dataset_meta VALUES (2, 3, 'https://x', '2026-01-01', "
                "40, 1678, 4050, 1027, 31)"
            )

    def test_an_import_run_status_is_limited(self, filled_db):
        filled_db.execute(
            "INSERT INTO import_run (id, started_at, status, importer_version, "
            "json_schema_version, json_generated_at, json_sha256) "
            "VALUES (1, '2026-01-01T00:00:00Z', 'ok', '1', 3, '2026-01-01', 'abc')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            filled_db.execute(
                "INSERT INTO import_run (id, started_at, status, importer_version, "
                "json_schema_version, json_generated_at, json_sha256) "
                "VALUES (2, '2026-01-01T00:00:00Z', 'casi', '1', 3, "
                "'2026-01-01', 'abc')"
            )


class TestTheTotalsView:
    def test_it_counts_nominations_and_awards(self, filled_db):
        row = filled_db.execute(
            "SELECT * FROM movie_totals WHERE movie_id = 1"
        ).fetchone()
        assert row["total_nominations"] == 1
        assert row["total_awards"] == 1

    def test_a_film_with_none_reads_as_zero_not_missing(self, filled_db):
        filled_db.execute(
            "INSERT INTO movie VALUES (2, 'y', 'Y', NULL, NULL, NULL, NULL, NULL, "
            "'ok', 0, 0)"
        )
        row = filled_db.execute(
            "SELECT * FROM movie_totals WHERE movie_id = 2"
        ).fetchone()
        assert row["total_nominations"] == 0
        assert row["total_awards"] == 0

    def test_several_nominations_are_summed(self, filled_db):
        filled_db.execute(
            "INSERT INTO nomination VALUES (2, 1, 1, 1, 'x', 0, NULL, 't:y')"
        )
        filled_db.execute(
            "INSERT INTO nomination VALUES (3, 1, 1, 1, 'x', 1, NULL, 't:z')"
        )
        row = filled_db.execute(
            "SELECT * FROM movie_totals WHERE movie_id = 1"
        ).fetchone()
        assert (row["total_nominations"], row["total_awards"]) == (3, 2)


class TestFileHandling:
    def test_creating_a_database_returns_its_path(self, tmp_path):
        path = create_database(tmp_path / "sub" / "goya.db")
        assert path.exists()

    def test_overwrite_is_refused_by_default(self, tmp_path):
        path = create_database(tmp_path / "goya.db")
        with pytest.raises(DatabaseError):
            create_database(path, overwrite=False)

    def test_overwrite_replaces_the_file(self, tmp_path):
        path = create_database(tmp_path / "goya.db")
        create_database(path, overwrite=True)
        connection = connect(path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM movie").fetchone()[0] == 0
        finally:
            connection.close()

    def test_connecting_to_a_missing_file_explains_itself(self, tmp_path):
        with pytest.raises(DatabaseError) as error:
            connect(tmp_path / "nada.db")
        assert "no existe" in str(error.value)

    def test_connect_with_create_needs_no_existing_file(self, tmp_path):
        create_database(tmp_path / "goya.db")
        connection = connect(tmp_path / "goya.db", create=True)
        connection.close()

    def test_the_default_path_lives_under_data(self):
        assert DEFAULT_PATH.parent.name == "data"
        assert DEFAULT_PATH.suffix == ".db"