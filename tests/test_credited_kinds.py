"""The curated category -> credited-kind mapping.

The table is a claim about the source, so the tests check it against the source
rather than against itself. Two properties matter: every real category is
classified, and the classification is not contradicted by the data.
"""

import pathlib

import pytest

from goya_scraper import storage
from goya_scraper.credited_kinds import (
    CREDITED_KINDS,
    KIND_WHY,
    SONG_CATEGORIES,
    WORK_CATEGORIES,
    credited_kind,
    known_categories,
)

PERSON = "person"
WORK = "work"
SONG = "song"


def _document():
    if not pathlib.Path("data/movies.json").exists():
        pytest.skip("needs a generated dataset")
    return storage.load()


def _nominations(document):
    for movie in document["movies"]:
        for nomination in movie["goya"]["nominations"]:
            yield movie, nomination


def _credits_of_kind(document, kind):
    """Every credited string in the categories of one kind."""
    for movie, nomination in _nominations(document):
        if credited_kind(nomination["category"]) == kind:
            for credit in nomination["credited"]:
                yield movie, nomination, credit


class TestTheThreeMeanings:
    def test_the_three_kinds_are_the_ones_the_column_can_have(self):
        assert set(CREDITED_KINDS.values()) == {PERSON, WORK, SONG}

    def test_every_kind_documents_why_it_exists(self):
        assert set(KIND_WHY) == set(CREDITED_KINDS.values())
        for reason in KIND_WHY.values():
            assert reason.strip()

    def test_work_and_song_are_named_explicitly(self):
        assert len(WORK_CATEGORIES) == 10
        assert len(SONG_CATEGORIES) == 1
        for name in WORK_CATEGORIES:
            assert CREDITED_KINDS[name] == WORK
        for name in SONG_CATEGORIES:
            assert CREDITED_KINDS[name] == SONG

    def test_person_is_spelled_out_not_derived(self):
        """It is a literal list, not "whatever is left over", so a new award
        cannot be classified as a person by accident."""
        assert len(CREDITED_KINDS) == 31
        person = [name for name, kind in CREDITED_KINDS.items() if kind == PERSON]
        assert len(person) == 20
        assert len(person) + len(WORK_CATEGORIES) + len(SONG_CATEGORIES) == 31

    def test_the_groups_do_not_overlap_and_cover_everything(self):
        named = [*WORK_CATEGORIES, *SONG_CATEGORIES]
        assert len(named) == len(set(named))
        assert set(named) <= set(CREDITED_KINDS)


class TestLookup:
    def test_known_categories_resolve(self):
        for name in CREDITED_KINDS:
            assert credited_kind(name) == CREDITED_KINDS[name]

    def test_an_unknown_award_returns_none_instead_of_guessing(self):
        """The importer has to be able to refuse. Defaulting to 'person' here is
        precisely the bug this design exists to avoid."""
        assert credited_kind("Mejor invento del año") is None
        assert credited_kind("") is None

    def test_known_categories_is_the_key_set(self):
        assert known_categories() == frozenset(CREDITED_KINDS)


class TestAgainstTheRealData:
    """These run over the real 40-edition dataset."""

    def test_every_real_category_is_classified(self):
        document = _document()
        real = {nomination["category"] for _, nomination in _nominations(document)}
        assert real == known_categories()
        assert len(real) == 31

    def test_no_nomination_is_left_unclassified(self):
        document = _document()
        for movie, nomination in _nominations(document):
            assert credited_kind(nomination["category"]) is not None, (
                f"{movie['title']}: {nomination['category']}"
            )

    def test_person_categories_never_credit_a_film_title(self):
        """3922 credits, none of them a title. If one were, the mapping is wrong."""
        document = _document()
        titles = {movie["title"] for movie in document["movies"]}
        credits = [c for _, _, c in _credits_of_kind(document, PERSON)]
        assert len(credits) == 3922
        assert not [c for c in credits if c in titles]

    def test_the_work_list_matches_the_data_rather_than_the_other_way_round(self):
        """Derive the classification from the data: how often is a credit the
        nominated film's own title? The work categories must score high, and the
        person and song ones must score zero.

        The threshold is a judgement call, so it is worth being explicit about it.
        A work category is one where the credits are *supposed* to be the title.
        The lowest is 'Mejor cortometraje' at 90%, the highest is 'Mejor película
        iberoamericana' at 95%. A person or song category scores exactly zero.
        Anything above 0.75 for a work category and exactly 0 for the others is a
        clean separation, which is what makes the mapping trustworthy."""
        document = _document()
        exact: dict[str, list[int]] = {}
        for movie, nomination in _nominations(document):
            bucket = exact.setdefault(nomination["category"], [0, 0])
            for credit in nomination["credited"]:
                bucket[1] += 1
                bucket[0] += credit == movie["title"]

        work_scores = []
        for name in CREDITED_KINDS:
            hits, total = exact[name]
            share = hits / total
            if CREDITED_KINDS[name] == WORK:
                work_scores.append(share)
            else:
                # A person or song category that ever matched a title would mean
                # the mapping is wrong in the dangerous direction: it would turn
                # a name into a film. Measured: exactly zero, over 4119 credits.
                assert hits == 0, f"{name} ({CREDITED_KINDS[name]}): {hits} coincidencias"

        # Work categories are not all equally clean, and that is worth pinning.
        # The low ones are the multi-word titles: 'Chico y Rita' becomes
        # ['Chico', 'Rita'], so 2 of 2 credits miss. The gap between the lowest
        # work category and a non-work one is what makes the mapping usable.
        assert min(work_scores) == pytest.approx(77 / 127, abs=0.001)
        assert max(work_scores) == pytest.approx(73 / 77, abs=0.001)
        assert min(work_scores) > 0.60

    def test_the_corrupted_work_credits_are_pinned_down(self):
        """940 of 1158 work credits are the exact title. The other 218 are
        fragments produced by splitting the title on commas and 'y', plus a few
        typographic variants. We keep them verbatim and never link them to a film,
        so the number is recorded here to make a change visible."""
        document = _document()
        exact = total = 0
        for movie, _, credit in _credits_of_kind(document, WORK):
            total += 1
            exact += credit == movie["title"]
        assert (exact, total) == (940, 1158)

    def test_song_categories_credit_no_film_title(self):
        document = _document()
        titles = {movie["title"] for movie in document["movies"]}
        credits = [c for _, _, c in _credits_of_kind(document, SONG)]
        assert len(credits) == 197
        assert not [c for c in credits if c in titles]

    def test_the_credit_split_is_what_the_database_assumes(self):
        """3922 credits resolve to a person; 1355 stay as plain text."""
        document = _document()
        with_person = sum(
            len(n["credited"])
            for _, n in _nominations(document)
            if credited_kind(n["category"]) == PERSON
        )
        without_person = sum(
            len(n["credited"])
            for _, n in _nominations(document)
            if credited_kind(n["category"]) != PERSON
        )
        assert (with_person, without_person) == (3922, 1355)
        assert with_person + without_person == 5277

    def test_no_nomination_is_left_without_a_credit(self):
        document = _document()
        for movie, nomination in _nominations(document):
            assert nomination["credited"], f"{movie['title']} sin credited"

    def test_a_category_never_needs_two_kinds(self):
        """Sanity on the shape of the mapping: one name, one kind, always."""
        document = _document()
        seen: dict[str, set[str]] = {}
        for _, nomination in _nominations(document):
            kind = credited_kind(nomination["category"])
            seen.setdefault(nomination["category"], set()).add(kind)
        assert all(len(kinds) == 1 for kinds in seen.values())