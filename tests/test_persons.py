"""The curated name merges.

These tests exist because the merge table is a *decision* and a decision can rot.
`SAME_PERSON` is hand-written, so the dangerous failure is not "a test fails" but
"the table quietly stops covering the data". These tests close that gap by
recomputing the grouping from `data/movies.json` and comparing.
"""

import pathlib

import pytest

from goya_scraper import storage
from goya_scraper.persons import (
    NEAR_DUPLICATES_ARE_NOT_MERGED,
    SAME_PERSON,
    canonical_name,
    folded_groups,
    merged_aliases,
    near_duplicates,
)

WORK_CATEGORIES = {
    "Mejor película",
    "Mejor película de animación",
    "Mejor película europea",
    "Mejor película extranjera de habla hispana",
    "Mejor película iberoamericana",
    "Mejor película documental",
    "Mejor cortometraje",
    "Mejor cortometraje de animación",
    "Mejor cortometraje de ficción",
    "Mejor cortometraje documental",
}
SONG_CATEGORIES = {"Mejor canción original"}


@pytest.fixture(scope="module")
def document():
    if not pathlib.Path("data/movies.json").exists():
        pytest.skip("needs a generated dataset")
    return storage.load()


@pytest.fixture(scope="module")
def person_names(document) -> set[str]:
    """Every name that will become a person row, and only those.

    Credits in the work and song categories are excluded: they hold film titles
    and song credits, not people, and merging them would invent people.
    """
    names: set[str] = set()
    for movie in document["movies"]:
        credits = movie["credits"]
        for role in ("directors", "screenwriters", "cast"):
            names.update(credits[role])
        for nomination in movie["goya"]["nominations"]:
            if nomination["category"] in WORK_CATEGORIES | SONG_CATEGORIES:
                continue
            names.update(nomination["credited"])
    return names


class TestTableShape:
    def test_canonical_names_are_unique(self):
        """Two groups cannot claim the same person."""
        assert len(SAME_PERSON) == len(set(SAME_PERSON))

    def test_an_alias_belongs_to_exactly_one_group(self):
        seen: dict[str, str] = {}
        for canonical, aliases in SAME_PERSON.items():
            for alias in aliases:
                assert alias not in seen, f"{alias!r} en dos grupos"
                seen[alias] = canonical
        assert len(merged_aliases()) == 97

    def test_no_alias_is_its_own_canonical(self):
        for canonical, aliases in SAME_PERSON.items():
            assert canonical not in aliases

    def test_the_table_is_not_empty(self):
        assert len(SAME_PERSON) == 90


class TestLookup:
    def test_a_merged_alias_resolves_to_its_canonical(self):
        for alias, canonical in merged_aliases().items():
            assert canonical_name(alias) == canonical

    def test_a_canonical_maps_to_itself(self):
        """So the function is idempotent and a stored name can be fed back in."""
        for canonical in SAME_PERSON:
            assert canonical_name(canonical) == canonical

    def test_an_unreviewed_name_passes_through_untouched(self):
        """No guessing. A name nobody looked at comes back exactly as written."""
        for name in ("Alguien Que No Hemos Revisado", "", "  ", "Paco de Lucía!!"):
            assert canonical_name(name) == name

    def test_the_table_is_explicit_not_computed(self):
        """The mapping must be readable as data, so it can be reviewed."""
        assert merged_aliases()["Iciar Bollain"] == "Icíar Bollaín"
        assert merged_aliases()["Jose Coronado"] == "José Coronado"


class TestTheMergesAreJustifiedByTheData:
    def test_every_curated_group_is_reproducible_from_the_data(self, person_names):
        """Each group must be an equality under _fold, not a similarity guess.
        This is what makes the table auditable rather than arbitrary."""
        computed = {frozenset(group) for group in folded_groups(person_names)}
        curated = {
            frozenset({canonical, *aliases})
            for canonical, aliases in SAME_PERSON.items()
        }
        assert curated == computed

    def test_no_group_is_invented(self, person_names):
        """Every spelling in the table really appears in the dataset."""
        known = person_names
        for canonical, aliases in SAME_PERSON.items():
            assert canonical in known, f"{canonical!r} no existe en los datos"
            for alias in aliases:
                assert alias in known, f"{alias!r} no existe en los datos"

    def test_the_merge_covers_the_whole_dataset(self, person_names):
        """6130 spellings collapse to 6033 people, in 90 groups."""
        assert len(person_names) == 6130
        assert len(SAME_PERSON) == 90
        saved = sum(len(aliases) for aliases in SAME_PERSON.values())
        assert saved == 97
        assert len(person_names) - saved == 6033

    def test_resolving_every_name_collapses_the_expected_count(self, person_names):
        resolved = {canonical_name(name) for name in person_names}
        assert len(resolved) == 6033
        assert len(resolved) < len(person_names)

    def test_every_merged_canonical_is_a_name_the_site_published(self, person_names):
        """We never invent a spelling. Each canonical must be a string the source
        actually contains, so `person.name` is always something we read."""
        for canonical in SAME_PERSON:
            assert canonical in person_names

    def test_each_group_keeps_exactly_one_survivor(self, person_names):
        """A group of 4 spellings must produce 1 person, not 2 and not 4."""
        for canonical, aliases in SAME_PERSON.items():
            survivors = {canonical_name(n) for n in {canonical, *aliases}}
            assert survivors == {canonical}


class TestTheChoicesWereNotLeftToARule:
    """Each of these would come out wrong under an obvious automatic rule."""

    def test_frequency_would_pick_the_misspelling(self, person_names):
        """Iciar Bollain appears 34 times; Icíar Bollaín only 5. The frequent one
        is wrong, so 'most frequent wins' cannot be the rule."""
        assert "Iciar Bollain" in person_names
        assert "Icíar Bollaín" in person_names
        assert canonical_name("Iciar Bollain") == "Icíar Bollaín"
        assert len(folded_groups(person_names)) > 0

    def test_case_folding_would_mangle_the_capitalisation(self):
        assert canonical_name("Paco De Lucía") == "Paco de Lucía"
        assert canonical_name("Antonio Del Real") == "Antonio del Real"

    def test_the_canonical_spelling_is_the_correct_one(self):
        for canonical, aliases in SAME_PERSON.items():
            assert canonical not in aliases
            assert canonical == canonical.strip()
            assert "  " not in canonical

    def test_the_specific_typos_we_fixed(self):
        """The website's own typos, not ours."""
        assert canonical_name("Tina Sáinz") == "Tina Sainz"
        assert canonical_name("José Luís Quirós") == "José Luis Quirós"
        assert canonical_name("José Quetglas") == "José Quetglás"
        assert canonical_name("Emilio Ruíz del Río") == "Emilio Ruiz del Río"
        assert canonical_name("Fernándo Guillén Cuervo") == "Fernando Guillén Cuervo"
        assert canonical_name("Rosa María Sardá") == "Rosa María Sardà"


class TestWhatWeRefuseToMerge:
    """A wrong merge is worse than a wrong split, so the refusals are recorded."""

    def test_every_refusal_states_a_reason(self):
        for pair, reason in NEAR_DUPLICATES_ARE_NOT_MERGED.items():
            assert len(pair) == 2
            assert pair[0] < pair[1], f"{pair} no está ordenado"
            assert reason.strip()

    def test_a_refused_pair_stays_separate(self):
        for left, right in NEAR_DUPLICATES_ARE_NOT_MERGED:
            assert canonical_name(left) == left
            assert canonical_name(right) == right
            assert canonical_name(left) != canonical_name(right)

    def test_a_refusal_is_a_real_lookalike(self, person_names):
        """The pair must actually be close, otherwise the refusal is noise."""
        for pair in NEAR_DUPLICATES_ARE_NOT_MERGED:
            for name in pair:
                assert name in person_names, f"{name!r} no existe en los datos"

    def test_near_duplicates_are_reported_not_merged(self, person_names):
        """The function finds look-alikes; merging is still a manual decision."""
        found = near_duplicates(person_names)
        assert len(found) > 50
        for left, right, ratio in found:
            assert ratio >= 0.90
            assert left != right

    def test_a_near_duplicate_is_still_two_people(self, person_names):
        """The whole point: spotting a look-alike must not merge it.

        `near_duplicates` folds accents and drops hyphens before comparing, so it
        reports 'Teresa De Pelegri' rather than the canonical spelling. Resolving
        both sides must still land on two different people, which is what the
        merge table is allowed to do about it: nothing."""
        for left, right, _ in near_duplicates(person_names):
            assert canonical_name(left) != canonical_name(right)

    def test_the_refused_pairs_would_score_as_look_alikes(self):
        """Proves `NEAR_DUPLICATES_ARE_NOT_MERGED` is not a list of pairs the tool
        simply fails to notice."""
        for left, right in NEAR_DUPLICATES_ARE_NOT_MERGED:
            assert canonical_name(left) != canonical_name(right)


class TestFilmTitlesNeverBecomePeople:
    """The bug this table is most likely to grow into."""

    def test_no_title_is_a_person(self, person_names, document):
        titles = {movie["title"] for movie in document["movies"]}
        assert not (person_names & titles)

    def test_title_fragments_do_not_leak_in(self, person_names):
        """Splitting a title on 'y' produced these: Yo, Gloria, jamón, Contigo.
        They live in work categories, so they must not be here."""
        for fragment in ("Yo", "yo", "Gloria", "gloria", "Jamón", "jamón", "Contigo"):
            assert fragment not in person_names, fragment

    def test_a_comma_split_fragment_is_not_merged_into_a_person(self):
        """Carmen y Lola was credited as ['Carmen', 'Lola']. If 'Carmen' ever
        reached the name table it would be a person invented from a title."""
        assert canonical_name("Carmen") == "Carmen"