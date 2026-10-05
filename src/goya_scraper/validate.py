"""Check data/movies.json for problems.

Pure functions over the document we just wrote. Nothing here touches the
network, so validation runs on every execution for free.

The idea is that a suspicious record is never silently accepted: either it is
impossible (ERROR), it disagrees with what the site says (WARNING), or it is
just incomplete (INFO). Which is which matters, because the source itself has
known inconsistencies and we do not want to cry wolf about them.
"""

import logging
from collections import Counter
from dataclasses import dataclass

from .categories import CANONICAL_BY_RAW, KEPT_AS_IS, MERGES, canonical_category

log = logging.getLogger(__name__)

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"
LEVEL_INFO = "info"

_LEVEL_BY_NAME = {LEVEL_ERROR: 40, LEVEL_WARNING: 30, LEVEL_INFO: 20}

# The category mapping can only be checked against a dataset big enough to prove
# something about it. The real dataset has 1678 films; the tests use one.
MIN_MOVIES_TO_CHECK_CATEGORIES = 50


@dataclass(frozen=True)
class Finding:
    level: str
    check: str
    message: str
    slug: str = ""

    @property
    def sort_key(self) -> tuple[int, str, str]:
        return (-_LEVEL_BY_NAME.get(self.level, 0), self.check, self.slug)


def validate(document: dict) -> list[Finding]:
    """Return every problem found in the document, most severe first."""
    findings: list[Finding] = []
    findings += _check_document(document)
    findings += _check_counts(document)
    for movie in document["movies"]:
        findings += _check_movie(movie)
    findings += _check_totals(document)
    # Only meaningful on a dataset big enough to prove the mapping still holds:
    # a three-film document cannot show whether two labels ever coexist, and
    # would report a spurious warning on every unit test.
    if len(document["movies"]) >= MIN_MOVIES_TO_CHECK_CATEGORIES:
        findings += _check_categories(document)
    return sorted(findings, key=lambda f: f.sort_key)


# --- checks ---------------------------------------------------------------------


def _check_document(document: dict) -> list[Finding]:
    """Things about the file as a whole."""
    found: list[Finding] = []
    slugs = [m.get("slug") for m in document["movies"]]

    for slug, count in Counter(slugs).items():
        if count > 1:
            found.append(
                Finding(
                    LEVEL_ERROR,
                    "duplicate_slug",
                    f"aparece {count} veces; debería haber un solo registro",
                    slug,
                )
            )
    for slug in slugs:
        if not slug:
            found.append(
                Finding(LEVEL_ERROR, "missing_slug", "registro sin slug")
            )

    editions = set(document["_meta"]["editions_scraped"])
    if not editions:
        found.append(
            Finding(LEVEL_ERROR, "no_editions", "no se ha registrado ninguna edición")
        )
    return found


def _check_counts(document: dict) -> list[Finding]:
    """`_meta.counts` is derived, so a mismatch means the file was edited."""
    found: list[Finding] = []
    movies = document["movies"]
    nominations = [n for m in movies for n in m["goya"]["nominations"]]

    actual = {
        "editions": len({e for m in movies for e in m["goya"]["editions"]}),
        "movies": len(movies),
        "nominations": len(nominations),
        "awards": sum(1 for n in nominations if n["won"]),
        "distinct_categories": len({n["category"] for n in nominations}),
    }
    for key, value in actual.items():
        declared = document["_meta"]["counts"].get(key)
        if declared != value:
            found.append(
                Finding(
                    LEVEL_ERROR,
                    "counts_disagree",
                    f"_meta.counts.{key} = {declared}, pero los datos dan {value}",
                )
            )
    return found


def _check_movie(movie: dict) -> list[Finding]:
    """Everything checkable about a single film."""
    found: list[Finding] = []
    slug = movie.get("slug", "")
    goya = movie["goya"]
    rows = goya["nominations"]
    won = [n for n in rows if n["won"]]

    def error(check: str, message: str) -> Finding:
        return Finding(LEVEL_ERROR, check, message, slug)

    def warning(check: str, message: str) -> Finding:
        return Finding(LEVEL_WARNING, check, message, slug)

    # -- impossible states --
    if not rows:
        found.append(error("no_nominations", "no tiene ninguna nominación"))
    if goya["total_awards"] > goya["total_nominations"]:
        found.append(
            error(
                "awards_exceed_nominations",
                f"{goya['total_awards']} premios pero solo "
                f"{goya['total_nominations']} nominaciones",
            )
        )
    if goya["total_nominations"] != len(rows):
        found.append(
            error(
                "nomination_total_mismatch",
                f"total_nominations = {goya['total_nominations']} "
                f"pero la lista tiene {len(rows)}",
            )
        )
    if goya["total_awards"] != len(won):
        found.append(
            error(
                "award_total_mismatch",
                f"total_awards = {goya['total_awards']} "
                f"pero hay {len(won)} nominaciones con won=true",
            )
        )
    listed_editions = sorted({n["edition"] for n in rows})
    if goya["editions"] != listed_editions:
        found.append(
            error(
                "editions_mismatch",
                f"goya.editions = {goya['editions']} "
                f"pero las nominaciones son de {listed_editions}",
            )
        )

    # -- disagreement with the site's own counters --
    quality = movie["data_quality"]
    reported = quality["reported_by_source"]
    if quality["detail_status"] != "ok":
        found.append(
            warning(
                "no_detail_page",
                f"sin ficha utilizable (estado: {quality['detail_status']})",
            )
        )
    elif reported is not None:
        if goya["total_nominations"] != reported["nominations"]:
            found.append(
                warning(
                    "nominations_disagree_with_source",
                    f"nosotros {goya['total_nominations']}, "
                    f"la web {reported['nominations']}",
                )
            )
        if goya["total_awards"] != reported["awards"]:
            found.append(
                warning(
                    "awards_disagree_with_source",
                    f"nosotros {goya['total_awards']} premios "
                    f"(marcados como ganadoras en la edición), "
                    f"la ficha declara {reported['awards']}",
                )
            )
        # The film page uses the year's own label, so both sides have to be
        # canonicalised before comparing. Forgetting this makes every renamed
        # award look like a conflict.
        raw_categories = reported.get("award_categories")
        if raw_categories is None and reported.get("awards", 0) > 0:
            # Written before award_categories existed (schema v1 and v2), yet the
            # page claims awards. We cannot compare names we do not have, so say
            # so instead of silently reporting nothing. When it claims zero
            # awards there is nothing to compare anyway, which is consistent.
            found.append(
                warning(
                    "award_categories_not_recorded",
                    "la ficha no guardó qué premios dice haber ganado "
                    "(schema v1/v2); no se puede comparar por categoría",
                )
            )
        else:
            # raw_categories may legitimately be []: the page was read and it
            # declares no awards. Only None means "never recorded".
            normalized = {
                canonical_category(name): name
                for name in (raw_categories or [])
            }
            found += _check_award_categories(slug, won, normalized)

    return found


def _check_award_categories(slug: str, won: list[dict], theirs_by_name: dict) -> list[Finding]:
    """Name the exact award in dispute, when the two sources disagree.

    Knowing "the totals differ" is much less useful than "the site claims
    Best New Actor for this film but no edition marks a winner there".

    `theirs_by_name` maps canonical category -> the label the film page used. An
    empty mapping is meaningful: the page was read and it claims no awards, which
    is a real answer and can still conflict with us.
    """
    ours = {n["category"] for n in won}
    theirs = set(theirs_by_name)

    found = []
    only_ours = sorted(ours - theirs)
    only_theirs = sorted(theirs - ours)

    def quote(canonical_names: list[str]) -> str:
        # Show the site's own wording, so the message matches the web page.
        return [theirs_by_name.get(name, name) for name in canonical_names]

    if only_theirs:
        found.append(
            Finding(
                LEVEL_WARNING,
                "award_claimed_only_by_movie_page",
                f"la ficha se atribuye {quote(only_theirs)} "
                f"pero no hay ganador marcado en la página de la edición",
                slug,
            )
        )
    if only_ours:
        found.append(
            Finding(
                LEVEL_WARNING,
                "award_claimed_only_by_edition_page",
                f"la edición marca {only_ours} como ganada "
                f"pero la ficha no lo cuenta entre sus premios",
                slug,
            )
        )
    return found


def _check_categories(document: dict) -> list[Finding]:
    """Confirm the category mapping still holds against the real data.

    The mapping is a curated decision, so it can rot: if the Academy ever puts
    both names in the same edition, or stops using one of them, we want to know
    rather than trust a constant written months ago.
    """
    found: list[Finding] = []
    raw_editions: dict[str, set[int]] = {}

    for movie in document["movies"]:
        for nomination in movie["goya"]["nominations"]:
            raw_editions.setdefault(nomination["category_raw"], set()).add(
                nomination["edition"]
            )

    for merge in MERGES:
        spans = []
        for raw in merge["raws"]:
            editions = raw_editions.get(raw, set())
            if not editions:
                found.append(
                    Finding(
                        LEVEL_WARNING,
                        "category_no_longer_used",
                        f"«{raw}» ya no aparece en ninguna edición; "
                        f"el mapeo de «{merge['canonical']}» puede estar obsoleto",
                    )
                )
                continue
            spans.append((min(editions), max(editions)))

        if len(spans) == 2:
            older, newer = sorted(spans)
            overlap = any(
                ed in raw_editions.get(merge["raws"][0], set())
                for ed in raw_editions.get(merge["raws"][1], set())
            )
            if overlap:
                found.append(
                    Finding(
                        LEVEL_WARNING,
                        "category_names_overlap",
                        f"«{merge['raws'][0]}» y «{merge['raws'][1]}» "
                        f"coexisten; quizá ya no sean el mismo premio",
                    )
                )
            elif newer[0] != older[1] + 1:
                found.append(
                    Finding(
                        LEVEL_WARNING,
                        "category_rename_not_contiguous",
                        f"«{merge['canonical']}»: «{merge['raws'][0]}» acaba en "
                        f"ed.{older[1]} y «{merge['raws'][1]}» empieza en ed.{newer[0]}; "
                        f"no son ediciones contiguas",
                    )
                )

    canonical = {
        n["category"] for m in document["movies"] for n in m["goya"]["nominations"]
    }
    unmapped = sorted(
        raw
        for raw in raw_editions
        if canonical_category(raw) not in CANONICAL_BY_RAW
    )
    if unmapped:
        found.append(
            Finding(
                LEVEL_INFO,
                "categories_passing_through",
                f"{len(unmapped)} categoría(s) sin renombrar (ya canónicas): "
                f"{', '.join(unmapped[:4])}",
            )
        )
    return found


def _check_totals(document: dict) -> list[Finding]:
    """Checks that need to see the whole dataset."""
    found: list[Finding] = []

    # Categories with more than one winner. A tie is legitimate, so this is
    # informational: it is here so nobody "fixes" it later.
    winners_per_category: Counter = Counter()
    for movie in document["movies"]:
        for nomination in movie["goya"]["nominations"]:
            if nomination["won"]:
                winners_per_category[(nomination["edition"], nomination["category"])] += 1
    ties = {key: count for key, count in winners_per_category.items() if count > 1}
    if ties:
        detail = ", ".join(f"ed.{e} {c}" for (e, c) in sorted(ties))
        found.append(
            Finding(
                LEVEL_INFO,
                "tied_categories",
                f"{len(ties)} categoría(s) con más de un ganador: {detail}",
            )
        )

    empty = sorted(
        movie["slug"] for movie in document["movies"] if not movie["goya"]["nominations"]
    )
    if empty:
        found.append(
            Finding(
                LEVEL_ERROR,
                "films_without_nominations",
                f"{len(empty)} película(s) sin nominaciones: {', '.join(empty[:5])}",
            )
        )

    multi = sorted(
        movie["slug"] for movie in document["movies"] if len(movie["goya"]["editions"]) > 1
    )
    if multi:
        found.append(
            Finding(
                LEVEL_INFO,
                "films_in_several_editions",
                f"{len(multi)} película(s) en más de una edición: {', '.join(multi[:5])}",
            )
        )
    return found


# --- reporting ------------------------------------------------------------------


def coverage(document: dict) -> list[tuple[str, int, int]]:
    """How often each optional field could be filled. (field, present, total)"""
    movies = document["movies"]
    total = len(movies)
    fields = [
        ("title", lambda m: m["title"]),
        ("title_original", lambda m: m["title_original"]),
        ("synopsis", lambda m: m["synopsis"]),
        ("countries", lambda m: m["countries"]),
        ("duration_minutes", lambda m: m["duration_minutes"]),
        ("directors", lambda m: m["credits"]["directors"]),
        ("screenwriters", lambda m: m["credits"]["screenwriters"]),
        ("cast", lambda m: m["credits"]["cast"]),
        ("producers_raw", lambda m: m["credits"]["producers_raw"]),
    ]
    return [
        (name, sum(1 for m in movies if getter(m)), total)
        for name, getter in fields
    ]


def render(document: dict, findings: list[Finding]) -> str:
    """A report meant to be read, not parsed."""
    counts = Counter(f.level for f in findings)
    lines: list[str] = []

    lines.append("=" * 72)
    lines.append("VALIDACIÓN")
    lines.append("=" * 72)
    summary = document["_meta"]["counts"]
    lines.append(
        f"{summary['editions']} ediciones · {summary['movies']} películas · "
        f"{summary['nominations']} nominaciones · {summary['awards']} premios · "
        f"{summary['distinct_categories']} categorías"
    )
    lines.append(
        f"problemas: {counts[LEVEL_ERROR]} errores, "
        f"{counts[LEVEL_WARNING]} avisos, "
        f"{counts[LEVEL_INFO]} informational"
    )

    lines.append("")
    lines.append("-- Categorías " + "-" * 56)
    for merge in MERGES:
        old, new = merge["raws"]
        lines.append(
            f"  {merge['canonical']}: «{old}» (ed.{merge['editions'][0]}) "
            f"+ «{new}» (ed.{merge['editions'][1]}) — {merge['why']}"
        )
    for kept in KEPT_AS_IS:
        lines.append(
            f"  {kept['label']} (ed.{kept['editions']}): {kept['why']}"
        )

    lines.append("")
    lines.append("-- Cobertura de datos " + "-" * 48)
    for name, present, total in coverage(document):
        percent = 100 * present // total if total else 0
        lines.append(f"  {name:<18} {present:>5}/{total:<5} {percent:>3}%")

    for level, heading in (
        (LEVEL_ERROR, "ERROR"),
        (LEVEL_WARNING, "AVISO"),
        (LEVEL_INFO, "INFO"),
    ):
        group = [f for f in findings if f.level == level]
        if not group:
            continue
        lines.append("")
        lines.append(f"-- {heading} ({len(group)}) " + "-" * 44)
        for finding in group:
            where = f"[{finding.slug}] " if finding.slug else ""
            lines.append(f"  {finding.check}: {where}{finding.message}")

    lines.append("")
    return "\n".join(lines)