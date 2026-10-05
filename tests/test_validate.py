"""Validation: the checks that catch impossible or suspicious records.

Built on the real document shape, so a test failure means a real rule broke.
"""

from goya_scraper.model import Credits, Movie, make_nomination
from goya_scraper.storage import build_document
from goya_scraper.validate import (
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARNING,
    coverage,
    render,
    validate,
)


def movie_with(
    slug="x",
    title="X",
    nominations=(),
    reported=None,
    detail_status="ok",
    awards=0,
    nominations_count=0,
    **kwargs,
):
    """A Movie built to order, for provoking specific failures.

    Uses make_nomination so the fixture behaves like a real scrape: the
    category is canonicalised and category_raw is filled in.
    """
    rows = [
        make_nomination(edition, edition + 1986, category, credited, won)
        for edition, category, credited, won in nominations
    ]
    return Movie(
        slug=slug,
        title=title,
        credits=Credits(**kwargs.pop("credits", {})),
        reported_nominations=nominations_count,
        reported_awards=awards,
        # None means "nothing recorded" (schema v1/v2). A list means the page
        # told us which awards it claims, possibly an empty one.
        reported_award_categories=(
            None
            if reported is None
            else list(reported.get("award_categories") or [])
        ),
        detail_status=detail_status,
        nominations=rows,
        **kwargs,
    )


def checks_of(findings, level=None):
    return {
        f.check for f in findings if level is None or f.level == level
    }


def find(findings, check):
    return next((f for f in findings if f.check == check), None)


class TestHealthyDocument:
    def test_no_findings_at_all(self):
        movie = movie_with(
            slug="el-buen-patron",
            title="El buen patrón",
            nominations=[
                (36, "Mejor película", ["El buen patrón"], True),
                (36, "Mejor dirección", ["Fernando León de Aranoa"], True),
                (36, "Mejor actor de reparto", ["Celso Bugallo"], False),
            ],
            reported={"award_categories": ["Mejor película", "Mejor dirección"]},
            nominations_count=3,
            awards=2,
        )
        assert validate(build_document([movie], [36])) == []

    def test_a_film_with_no_awards_is_not_a_problem(self):
        # The vast majority of nominated films win nothing. That is normal.
        movie = movie_with(
            slug="yalla",
            title="Yalla",
            nominations=[(36, "Mejor cortometraje", ["Yalla"], False)],
            reported={"award_categories": []},
            nominations_count=1,
            awards=0,
        )
        assert validate(build_document([movie], [36])) == []


class TestImpossibleStates:
    def test_more_awards_than_nominations(self):
        # The exact case from the brief.
        movie = movie_with(
            slug="raro", title="Raro",
            nominations=[(36, "Mejor película", ["Raro"], True)],
            reported={"award_categories": []},
            nominations_count=1, awards=1,
        )
        document = build_document([movie], [36])
        # Simulate a hand edit that makes an impossible record.
        document["movies"][0]["goya"]["total_awards"] = 3

        finding = find(validate(document), "awards_exceed_nominations")
        assert finding is not None
        assert finding.level == LEVEL_ERROR
        assert finding.slug == "raro"

    def test_nomination_total_does_not_match_the_list(self):
        movie = movie_with(
            slug="x", title="X",
            nominations=[(36, "Mejor película", ["X"], True)],
            reported={"award_categories": ["Mejor película"]},
            nominations_count=1, awards=1,
        )
        document = build_document([movie], [36])
        document["movies"][0]["goya"]["total_nominations"] = 99
        assert find(validate(document), "nomination_total_mismatch") is not None

    def test_award_total_does_not_match_won_flags(self):
        movie = movie_with(
            slug="x", title="X",
            nominations=[(36, "Mejor película", ["X"], True)],
            reported={"award_categories": ["Mejor película"]},
            nominations_count=1, awards=1,
        )
        document = build_document([movie], [36])
        document["movies"][0]["goya"]["total_awards"] = 5
        assert find(validate(document), "award_total_mismatch") is not None

    def test_editions_list_does_not_match_the_nominations(self):
        movie = movie_with(
            slug="x", title="X",
            nominations=[(36, "Mejor película", ["X"], True)],
            reported={"award_categories": ["Mejor película"]},
            nominations_count=1, awards=1,
        )
        document = build_document([movie], [36])
        document["movies"][0]["goya"]["editions"] = [1, 2, 3]
        assert find(validate(document), "editions_mismatch") is not None

    def test_film_without_nominations(self):
        movie = movie_with(slug="vacio", title="Vacío", reported={"award_categories": []})
        assert find(validate(build_document([movie], [36])), "films_without_nominations")

    def test_duplicate_slug(self):
        one = movie_with(slug="mismo", title="Uno",
                         nominations=[(36, "Mejor película", ["Uno"], True)],
                         reported={"award_categories": ["Mejor película"]},
                         nominations_count=1, awards=1)
        two = movie_with(slug="mismo", title="Otro",
                         nominations=[(36, "Mejor dirección", ["Otro"], False)],
                         reported={"award_categories": []},
                         nominations_count=1, awards=0)
        finding = find(validate(build_document([one, two], [36])), "duplicate_slug")
        assert finding is not None
        assert "2 veces" in finding.message

    def test_counts_that_were_edited_by_hand(self):
        movie = movie_with(slug="x", title="X",
                           nominations=[(36, "Mejor película", ["X"], True)],
                           reported={"award_categories": ["Mejor película"]},
                           nominations_count=1, awards=1)
        document = build_document([movie], [36])
        document["_meta"]["counts"]["movies"] = 500
        finding = find(validate(document), "counts_disagree")
        assert finding is not None
        assert "500" in finding.message

    def test_every_error_is_reported_not_just_the_first(self):
        movie = movie_with(slug="x", title="X")
        document = build_document([movie], [36])
        goya = document["movies"][0]["goya"]
        goya["total_nominations"] = 7
        goya["total_awards"] = 9
        goya["editions"] = [99]
        found = checks_of(validate(document), LEVEL_ERROR)
        assert {"nomination_total_mismatch", "award_total_mismatch",
                "editions_mismatch", "films_without_nominations"} <= found


class TestDisagreementWithTheSource:
    def test_awards_disagree(self):
        movie = movie_with(slug="x", title="X",
                           nominations=[(36, "Mejor película", ["X"], True)],
                           reported={"award_categories": ["Mejor película"]},
                           nominations_count=1, awards=3)
        finding = find(validate(build_document([movie], [36])),
                       "awards_disagree_with_source")
        assert finding is not None
        assert finding.level == LEVEL_WARNING
        assert "1 premios" in finding.message and "3" in finding.message

    def test_the_disputed_category_is_named(self):
        """The useful part: not just 'the totals differ' but which award."""
        movie = movie_with(
            slug="la-nina-de-tus-ojos", title="La niña de tus ojos",
            nominations=[
                (13, "Mejor película", ["La niña de tus ojos"], True),
                (13, "Mejor actriz protagonista", ["Penélope Cruz"], True),
            ],
            reported={"award_categories": [
                "Mejor película",
                "Mejor actriz protagonista",
                "Mejor actor revelación",
            ]},
            nominations_count=2, awards=2,
        )
        finding = find(validate(build_document([movie], [13])),
                       "award_claimed_only_by_movie_page")
        assert finding is not None
        assert "Mejor actor revelación" in finding.message

    def test_award_only_the_edition_page_marks(self):
        movie = movie_with(
            slug="el-rey-de-la-granja", title="El rey de la granja",
            nominations=[(17, "Mejor película de animación", ["El rey de la granja"], True)],
            # The page was read and it declares no awards at all: an empty list,
            # not None. That is a real answer, and it conflicts with us.
            reported={"award_categories": []},
            nominations_count=1, awards=0,
        )
        finding = find(validate(build_document([movie], [17])),
                       "award_claimed_only_by_edition_page")
        assert finding is not None
        assert "Mejor película de animación" in finding.message
        assert "Mejor película de animación" in finding.message

    def test_a_v1_file_says_it_cannot_compare_categories(self):
        """A dataset written before award_categories existed must not look clean
        just because the comparison silently did nothing."""
        movie = movie_with(
            slug="x", title="X",
            nominations=[(17, "Mejor película de animación", ["X"], True)],
            reported=None,  # schema v1/v2: nothing recorded
            nominations_count=1, awards=1,
        )
        findings = validate(build_document([movie], [17]))
        assert find(findings, "award_categories_not_recorded") is not None

    def test_missing_detail_page_is_reported(self):
        movie = movie_with(slug="fantasma", title=None, detail_status="not_found",
                           nominations=[(36, "Mejor película", ["F"], False)],
                           reported=None)
        findings = validate(build_document([movie], [36]))
        assert find(findings, "no_detail_page") is not None
        # And we do not also claim its counters disagree, since they are null.
        assert find(findings, "awards_disagree_with_source") is None


class TestWholeDataset:
    def test_tied_categories_are_informational_not_a_problem(self):
        # Two winners for one category is legitimate, and must not be flagged.
        a = movie_with(slug="a", title="A",
                       nominations=[(28, "Mejor película", ["A"], True)],
                       reported={"award_categories": ["Mejor película"]},
                       nominations_count=1, awards=1)
        b = movie_with(slug="b", title="B",
                       nominations=[(28, "Mejor película", ["B"], True)],
                       reported={"award_categories": ["Mejor película"]},
                       nominations_count=1, awards=1)
        findings = validate(build_document([a, b], [28]))
        finding = find(findings, "tied_categories")
        assert finding is not None
        assert finding.level == LEVEL_INFO
        assert LEVEL_ERROR not in checks_of(findings, LEVEL_ERROR)

    def test_three_way_tie_is_one_finding_not_three(self):
        movies = [
            movie_with(slug=f"t{i}", title=f"T{i}",
                       nominations=[(17, "Mejor película de animación", [f"T{i}"], True)],
                       reported={"award_categories": ["Mejor película de animación"]},
                       nominations_count=1, awards=1)
            for i in range(3)
        ]
        findings = [f for f in validate(build_document(movies, [17]))
                    if f.check == "tied_categories"]
        assert len(findings) == 1
        assert "1 categoría(s)" in findings[0].message

    def test_film_in_two_editions_is_informational(self):
        movie = movie_with(slug="x", title="X",
                           nominations=[(36, "Mejor película", ["X"], True),
                                        (40, "Mejor película", ["X"], True)],
                           reported={"award_categories": ["Mejor película"]},
                           nominations_count=2, awards=2)
        finding = find(validate(build_document([movie], [36, 40])),
                       "films_in_several_editions")
        assert finding is not None
        assert finding.level == LEVEL_INFO

    def test_no_editions_recorded_is_an_error(self):
        movie = movie_with(slug="x", title="X",
                           nominations=[(36, "Mejor película", ["X"], True)],
                           reported={"award_categories": ["Mejor película"]},
                           nominations_count=1, awards=1)
        assert find(validate(build_document([movie], [])), "no_editions")


class TestOrderingAndReporting:
    def test_errors_come_before_warnings(self):
        bad = movie_with(slug="x", title="X",
                         nominations=[(36, "Mejor película", ["X"], True)],
                         reported={"award_categories": ["Otra cosa"]},
                         nominations_count=1, awards=9)
        levels = [f.level for f in validate(build_document([bad], [36]))]
        assert LEVEL_ERROR not in levels or levels.index(LEVEL_ERROR) < levels.index(LEVEL_WARNING)

    def test_coverage_counts_present_fields(self):
        movie = movie_with(
            slug="x", title="X",
            nominations=[(36, "Mejor película", ["X"], True)],
            reported={"award_categories": ["Mejor película"]},
            nominations_count=1, awards=1,
            credits={"directors": ["Alguien"]},
        )
        coverage_map = dict((name, (present, total))
                            for name, present, total in coverage(build_document([movie], [36])))
        assert coverage_map["title"] == (1, 1)
        assert coverage_map["directors"] == (1, 1)
        assert coverage_map["cast"] == (0, 1)
        assert coverage_map["title_original"] == (0, 1)

    def test_render_includes_summary_and_every_finding(self):
        movie = movie_with(slug="x", title="X",
                           nominations=[(36, "Mejor película", ["X"], True)],
                           reported={"award_categories": []},
                           nominations_count=1, awards=5)
        document = build_document([movie], [36])
        report = render(document, validate(document))
        assert "VALIDACIÓN" in report
        assert "1 películas" in report
        assert "Cobertura de datos" in report
        assert "awards_disagree_with_source" in report

    def test_render_of_a_clean_document_says_zero_problems(self):
        movie = movie_with(slug="x", title="X",
                           nominations=[(36, "Mejor película", ["X"], True)],
                           reported={"award_categories": ["Mejor película"]},
                           nominations_count=1, awards=1)
        document = build_document([movie], [36])
        assert "0 errores, 0 avisos" in render(document, validate(document))


class TestRenamedAwardsAreNotFalseConflicts:
    """A renamed award must not look like a disagreement.

    The film page carries the label of its year: a 2013 film says
    "Mejor dirección artística", while our canonical name is "Mejor dirección de
    arte". Comparing them literally reported ~35 phantom conflicts.
    """

    def old_label_film(self, slug="una-pelicula", category="Mejor dirección artística"):
        return movie_with(
            slug=slug, title="Una película",
            nominations=[(13, category, ["Ganadora"], True)],
            reported={"award_categories": [category]},
            nominations_count=1, awards=1,
        )

    def test_no_conflict_when_the_page_uses_the_old_label(self):
        assert validate(build_document([self.old_label_film()], [13])) == []

    def test_no_conflict_for_the_renamed_latin_american_award(self):
        movie = movie_with(
            slug="el-secreto-de-sus-ojos", title="El secreto de sus ojos",
            nominations=[(24, "Mejor película hispanoamericana",
                          ["El secreto de sus ojos"], True)],
            reported={"award_categories": ["Mejor película hispanoamericana"]},
            nominations_count=1, awards=1,
        )
        assert validate(build_document([movie], [24])) == []

    def test_a_real_conflict_is_still_reported_after_canonicalising(self):
        movie = movie_with(
            slug="x", title="X",
            nominations=[(13, "Mejor dirección artística", ["Ganadora"], True)],
            reported={"award_categories": [
                "Mejor dirección artística",
                "Mejor actor revelación",
            ]},
            nominations_count=1, awards=1,
        )
        findings = validate(build_document([movie], [13]))
        assert find(findings, "award_claimed_only_by_movie_page") is not None

    def test_the_message_uses_the_sites_own_wording(self):
        # We compare canonically, but a person reading it needs to match the
        # string they would find on the web.
        movie = movie_with(
            slug="x", title="X",
            nominations=[(13, "Mejor dirección artística", ["Ganadora"], False)],
            reported={"award_categories": ["Mejor dirección artística",
                                           "Mejor actor revelación"]},
            nominations_count=1, awards=0,
        )
        finding = find(validate(build_document([movie], [13])),
                       "award_claimed_only_by_movie_page")
        assert "Mejor actor revelación" in finding.message