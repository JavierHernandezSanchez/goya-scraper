"""Check an imported database against the JSON it came from.

`validate.py` checks the document on its own terms: does it hang together as a
scraping result. This module checks something else: does the database say what
the document said. The two can disagree in ways neither would notice alone. A
nomination lost in the join, a person merged twice, a count off by one because a
category was refused, and every table would still be internally consistent.

The checks are pure reads. Nothing here writes, and nothing here repairs. A
mismatch is reported so a person decides what to do about it.

Separately, `quality()` reuses the document's own findings to explain what is
*inside* the data: the ties, the missing winners, the six films where the film
page and the edition disagree. Those are properties of Goya's history, not
mistakes in our work.
"""

import sqlite3

from dataclasses import dataclass, field
from pathlib import Path

from . import db

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"

#: Least serious first, so `LEVELS.index` can rank a finding by how much it
#: matters. `_by_level` inverts it: a report is read most-serious-first.
LEVELS = (LEVEL_INFO, LEVEL_WARNING, LEVEL_ERROR)


@dataclass
class Finding:
    level: str
    code: str
    message: str
    detail: str | None = None

    def render(self) -> str:
        text = f"[{self.level}] {self.message}"
        if self.detail:
            text += f"\n         {self.detail}"
        return text


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, detail: str | None = None) -> None:
        self.findings.append(Finding(level, code, message, detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == LEVEL_ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == LEVEL_WARNING]

    @property
    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.level == LEVEL_INFO]

    @property
    def ok(self) -> bool:
        """No errors. Warnings and info describe the data, not our work."""
        return not self.errors

    def render(self) -> str:
        counts = {level: len(getattr(self, f"{level}s")) for level in LEVELS}
        header = (
            f"{counts[LEVEL_ERROR]} errores, "
            f"{counts[LEVEL_WARNING]} avisos, "
            f"{counts[LEVEL_INFO]} informacion"
        )
        if not self.findings:
            return f"validacion: sin hallazgos\n{header}"
        lines = [f"validacion: {len(self.findings)} hallazgo(s)"]
        lines.extend(f"  {f.render()}" for f in sorted(self.findings, key=_by_level))
        lines.append("")
        lines.append(header)
        return "\n".join(lines)


def _by_level(finding: Finding) -> tuple[int, str]:
    """Sort key: most serious first, then by code so the order is stable.

    `LEVELS` runs least-serious-first, hence the inversion. Without it a report
    would open with "sin ganador marcado" and bury a count mismatch at the
    bottom, which is the wrong way round for anything a person has to act on.
    """
    return (-LEVELS.index(finding.level), finding.code)


def validate(connection: sqlite3.Connection, document: dict) -> Report:
    """Every check. No writes, no repair, no network."""
    report = Report()
    _check_integrity(connection, report)
    _check_counts(connection, document, report)
    _check_foreign_keys(connection, report)
    _check_duplicates(connection, report)
    _check_identifiers(connection, report)
    _check_orphan_nominations(connection, report)
    _check_missing_fields(connection, document, report)
    quality(connection, document, report)
    return report


# ------------------------------------------------------------ integrity ----


def _check_integrity(connection, report) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        report.add(LEVEL_ERROR, "integrity", f"integrity_check: {result}")


def _check_foreign_keys(connection, report) -> None:
    rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    if rows:
        listed = ", ".join(f"{r['table']}.rowid={r['rowid']}" for r in rows[:5])
        report.add(
            LEVEL_ERROR,
            "foreign_keys",
            f"{len(rows)} fila(s) con clave foranea huerfana",
            listed,
        )


def _check_counts(connection, document, report) -> None:
    """Every row count the JSON can state must match what the database holds.

    This is the check that catches a lost join. Nothing else would: the schema
    would be satisfied either way.
    """
    movies = document.get("movies") or []
    nominations = [
        n for m in movies for n in (m.get("goya") or {}).get("nominations") or []
    ]
    categories = {n["category"] for n in nominations}
    editions = {n["edition"] for n in nominations}

    expected = {
        "movie": len(movies),
        "nomination": len(nominations),
        "category": len(categories),
        "goya_edition": len(editions),
        "country": len({c for m in movies for c in (m.get("countries") or [])}),
        "nomination_credit": sum(len(n["credited"]) for n in nominations),
        "movie_credit": sum(
            len((m.get("credits") or {}).get(role) or [])
            for m in movies
            for role in ("directors", "screenwriters", "cast")
        ),
        "movie_country": sum(len(m.get("countries") or []) for m in movies),
        "reported_award": sum(
            len(((m.get("data_quality") or {}).get("reported_by_source") or {}).get(
                "award_categories"
            ) or [])
            for m in movies
        ),
    }
    for table, count in expected.items():
        actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if actual != count:
            report.add(
                LEVEL_ERROR,
                "count",
                f"{table}: el JSON tiene {count}, la base de datos {actual}",
            )

    awards_json = sum(1 for n in nominations if n["won"])
    awards_db = connection.execute(
        "SELECT COALESCE(SUM(won), 0) FROM nomination"
    ).fetchone()[0]
    if awards_json != awards_db:
        report.add(
            LEVEL_ERROR,
            "awards",
            f"ganadoras: el JSON tiene {awards_json}, la base de datos {awards_db}",
        )

    view = connection.execute(
        "SELECT COALESCE(SUM(total_nominations), 0), "
        "COALESCE(SUM(total_awards), 0) FROM movie_totals"
    ).fetchone()
    if (view[0], view[1]) != (len(nominations), awards_json):
        report.add(
            LEVEL_ERROR,
            "view",
            f"movie_totals suma {view[0]} nominaciones y {view[1]} premios; "
            f"el JSON tiene {len(nominations)} y {awards_json}",
        )


# ------------------------------------------------------------ structure ----


def _check_duplicates(connection, report) -> None:
    checks = (
        ("movie", "slug", "dos peliculas con el mismo slug"),
        ("person", "name", "dos personas con el mismo nombre"),
        ("category", "name", "dos categorias con el mismo nombre"),
        ("country", "name", "dos paises con el mismo nombre"),
    )
    for table, column, message in checks:
        rows = connection.execute(
            f"SELECT {column}, COUNT(*) AS n FROM {table} "
            f"GROUP BY {column} HAVING n > 1"
        ).fetchall()
        if rows:
            listed = ", ".join(repr(r[column]) for r in rows[:5])
            report.add(
                LEVEL_ERROR,
                "duplicate",
                f"{table}: {len(rows)} {message}",
                listed,
            )

    repeated = connection.execute(
        "SELECT movie_id, edition_id, category_id, COUNT(*) AS n "
        "FROM nomination GROUP BY 1, 2, 3 HAVING n > 1"
    ).fetchall()
    if repeated:
        report.add(
            LEVEL_WARNING,
            "repeated_nomination",
            f"{len(repeated)} pelicula/edicion/categoria con mas de una "
            "nominacion",
            "esperado: dos actores pueden competir en la misma categoria. "
            "Comprueba que no se trate de un duplicado",
        )

    aliases = connection.execute(
        "SELECT alias, COUNT(*) AS n FROM person_alias GROUP BY alias HAVING n > 1"
    ).fetchall()
    if aliases:
        report.add(
            LEVEL_ERROR, "duplicate", f"{len(aliases)} alias repetido(s)"
        )

    stranded = connection.execute(
        "SELECT COUNT(*) FROM person p WHERE NOT EXISTS ("
        "SELECT 1 FROM person_alias a WHERE a.person_id = p.id"
        "    OR EXISTS (SELECT 1 FROM movie_credit mc WHERE mc.person_id = p.id)"
        "    OR EXISTS (SELECT 1 FROM nomination_credit nc WHERE nc.person_id = p.id))"
    ).fetchone()[0]
    if stranded:
        report.add(
            LEVEL_WARNING,
            "unused_person",
            f"{stranded} persona(s) sin credito ni alias",
        )


def _check_identifiers(connection, report) -> None:
    """Nothing may be identified by its text alone."""
    checks = (
        ("movie", "id", "pelicula sin identificador"),
        ("person", "id", "persona sin identificador"),
        ("nomination", "id", "nominacion sin identificador"),
        ("goya_edition", "id", "edicion sin identificador"),
        ("category", "id", "categoria sin identificador"),
    )
    for table, column, message in checks:
        missing = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
        ).fetchone()[0]
        if missing:
            report.add(LEVEL_ERROR, "identifier", f"{table}: {missing} {message}")

    without_slug = connection.execute(
        "SELECT COUNT(*) FROM movie WHERE slug IS NULL OR slug = ''"
    ).fetchone()[0]
    if without_slug:
        report.add(
            LEVEL_ERROR, "identifier", f"{without_slug} pelicula(s) sin slug"
        )


def _check_orphan_nominations(connection, report) -> None:
    """Every nomination belongs to a film, an edition and a category.

    Unreachable through foreign keys, so it is checked by hand: the constraint
    says the id exists, not that the right kind of row is on the other end.
    """
    orphans = {
        "pelicula": connection.execute(
            "SELECT COUNT(*) FROM nomination n LEFT JOIN movie m ON m.id = n.movie_id "
            "WHERE m.id IS NULL"
        ).fetchone()[0],
        "edicion": connection.execute(
            "SELECT COUNT(*) FROM nomination n "
            "LEFT JOIN goya_edition e ON e.id = n.edition_id WHERE e.id IS NULL"
        ).fetchone()[0],
        "categoria": connection.execute(
            "SELECT COUNT(*) FROM nomination n "
            "LEFT JOIN category c ON c.id = n.category_id WHERE c.id IS NULL"
        ).fetchone()[0],
    }
    for kind, count in orphans.items():
        if count:
            report.add(
                LEVEL_ERROR, "orphan", f"{count} nominacion(es) sin {kind}"
            )

    stray = connection.execute(
        "SELECT COUNT(*) FROM nomination_credit nc "
        "LEFT JOIN nomination n ON n.id = nc.nomination_id WHERE n.id IS NULL"
    ).fetchone()[0]
    if stray:
        report.add(LEVEL_ERROR, "orphan", f"{stray} credito(s) sin nominacion")

    kinds = connection.execute(
        "SELECT c.name, c.credited_kind FROM category c"
    ).fetchall()
    wrong = [
        r["name"]
        for r in kinds
        if r["credited_kind"] not in ("person", "work", "song")
    ]
    if wrong:
        report.add(
            LEVEL_ERROR,
            "credited_kind",
            f"{len(wrong)} categoria(s) con credited_kind desconocido",
            ", ".join(wrong[:5]),
        )

    # A person category whose credits never resolved to a person would mean the
    # mapping stopped matching the data.
    unresolved = connection.execute(
        "SELECT COUNT(*) FROM nomination n "
        "JOIN category c ON c.id = n.category_id "
        "LEFT JOIN nomination_credit nc ON nc.nomination_id = n.id "
        "WHERE c.credited_kind = 'person' AND nc.person_id IS NULL"
    ).fetchone()[0]
    if unresolved:
        report.add(
            LEVEL_ERROR,
            "credit",
            f"{unresolved} credito(s) de categoria 'person' sin persona",
            "la tabla credited_kinds puede estar desfasada con los datos",
        )


def _check_missing_fields(connection, document, report) -> None:
    """Every film page the scraper did not read must say so, not look like a zero."""
    unreadable = connection.execute(
        "SELECT slug, detail_status FROM movie WHERE detail_status <> 'ok'"
    ).fetchall()
    if unreadable:
        listed = ", ".join(r["slug"] for r in unreadable[:5])
        report.add(
            LEVEL_WARNING,
            "detail_status",
            f"{len(unreadable)} ficha(s) no leida(s)",
            listed,
        )

    lying = connection.execute(
        "SELECT slug FROM movie WHERE detail_status <> 'ok' "
        "AND (reported_nominations IS NOT NULL OR reported_awards IS NOT NULL)"
    ).fetchall()
    if lying:
        report.add(
            LEVEL_ERROR,
            "detail_status",
            f"{len(lying)} ficha(s) sin leer con contadores informados",
        )

    empty = connection.execute(
        "SELECT COUNT(*) FROM nomination WHERE note IS NULL"
    ).fetchone()[0]
    if empty:
        report.add(
            LEVEL_INFO,
            "note",
            f"{empty} nominacion(es) sin nota",
            "la fuente casi siempre la trae; 4050 de 4050 la traen hoy",
        )

    absent = connection.execute(
        "SELECT COUNT(*) FROM movie WHERE reported_awards = 0 "
        "AND EXISTS (SELECT 1 FROM nomination n WHERE n.movie_id = movie.id "
        "AND n.won = 1)"
    ).fetchone()[0]
    if absent:
        report.add(
            LEVEL_WARNING,
            "reported_dispute",
            f"{absent} pelicula(s) cuya ficha dice 0 premios y la edicion premia",
        )

    absent_categories = connection.execute(
        "SELECT COUNT(*) FROM category c WHERE NOT EXISTS ("
        "SELECT 1 FROM nomination n WHERE n.category_id = c.id)"
    ).fetchone()[0]
    if absent_categories:
        report.add(
            LEVEL_WARNING,
            "unused_category",
            f"{absent_categories} categoria(s) sin nominaciones",
        )


# --------------------------------------------------------------- quality ----
# Everything below describes Goya's history, not our work. It is information, not
# an error, and it is the same set of facts validate.py reports on the document.


def quality(connection, document: dict, report: Report) -> None:
    """Facts about the data that a reader should know before querying it."""
    disputed = connection.execute(
        "SELECT COUNT(*) FROM movie_totals t JOIN movie m ON m.id = t.movie_id "
        "WHERE m.reported_awards IS NOT NULL "
        "AND m.reported_awards <> t.total_awards"
    ).fetchone()[0]
    if disputed:
        report.add(
            LEVEL_INFO,
            "source_disagreement",
            f"{disputed} pelicula(s) donde la ficha y la edicion no coinciden",
            "la pagina de la pelicula y la de la edicion son dos fuentes distintas",
        )

    ties = connection.execute(
        "SELECT e.ceremony_year, c.name, SUM(n.won) AS winners "
        "FROM nomination n "
        "JOIN goya_edition e ON e.id = n.edition_id "
        "JOIN category c ON c.id = n.category_id "
        "GROUP BY e.id, c.id HAVING SUM(n.won) > 1"
    ).fetchall()
    if ties:
        listed = ", ".join(
            f"{r['ceremony_year']} {r['name']} ({r['winners']})" for r in ties
        )
        report.add(
            LEVEL_INFO,
            "tie",
            f"{len(ties)} categoria(s) con empate",
            listed,
        )

    unwon = connection.execute(
        "SELECT e.ceremony_year, c.name "
        "FROM nomination n "
        "JOIN goya_edition e ON e.id = n.edition_id "
        "JOIN category c ON c.id = n.category_id "
        "GROUP BY e.id, c.id HAVING SUM(n.won) = 0"
    ).fetchall()
    if unwon:
        listed = ", ".join(f"{r['ceremony_year']} {r['name']}" for r in unwon)
        report.add(
            LEVEL_INFO,
            "no_winner",
            f"{len(unwon)} categoria(s) sin ganador marcado",
            listed,
        )

    split = connection.execute(
        "SELECT COUNT(*) FROM nomination_credit nc "
        "JOIN nomination n ON n.id = nc.nomination_id "
        "JOIN category c ON c.id = n.category_id "
        "JOIN movie m ON m.id = n.movie_id "
        "WHERE c.credited_kind = 'work' AND nc.credit_text <> m.title"
    ).fetchone()[0]
    if split:
        report.add(
            LEVEL_INFO,
            "split_title",
            f"{split} credito(s) de obra no coinciden con el titulo",
            "la fuente parte el titulo por comas y por ' y '; el texto se "
            "conserva literal y nunca se une a una pelicula",
        )

    if document:
        run = connection.execute(
            "SELECT json_schema_version, json_generated_at, json_sha256 "
            "FROM import_run"
        ).fetchone()
        meta = document.get("_meta") or {}
        if run and run["json_schema_version"] != meta.get("schema_version"):
            report.add(
                LEVEL_WARNING,
                "provenance",
                f"la base de datos viene de un JSON de esquema "
                f"{run['json_schema_version']}, este es "
                f"{meta.get('schema_version')}",
            )


def render(connection: sqlite3.Connection, document: dict) -> str:
    """Validate and render, for the command line."""
    return validate(connection, document).render()


def main(argv: list[str] | None = None) -> int:
    """`python -m goya_scraper.db_validate [json] [db]`."""
    import argparse

    from . import storage

    parser = argparse.ArgumentParser(
        prog="python -m goya_scraper.db_validate",
        description="Comprueba la base de datos contra el JSON del que salió.",
    )
    parser.add_argument("json", nargs="?", type=Path, default=storage.DEFAULT_PATH)
    parser.add_argument("db", nargs="?", type=Path, default=db.DEFAULT_PATH)
    arguments = parser.parse_args(argv)

    document = storage.load(arguments.json)
    connection = db.connect(arguments.db)
    try:
        report = validate(connection, document)
    finally:
        connection.close()
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())