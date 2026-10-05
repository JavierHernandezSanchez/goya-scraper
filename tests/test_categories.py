"""The curated category mapping.

Two things need protecting: the renames we verified, and the labels we decided
NOT to merge. The second matters as much as the first.
"""

import pytest

from goya_scraper.categories import (
    CANONICAL_BY_RAW,
    KEPT_AS_IS,
    KEEP_LEGACY_SHORT,
    KEEP_LEGACY_SCREENPLAY,
    MERGES,
    canonical_category,
    renamed_labels,
)


class TestVerifiedRenames:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Mejor dirección artística", "Mejor dirección de arte"),
            ("Mejor dirección de arte", "Mejor dirección de arte"),
            ("Mejor película hispanoamericana", "Mejor película iberoamericana"),
            ("Mejor película iberoamericana", "Mejor película iberoamericana"),
        ],
    )
    def test_renamed_awards_resolve_to_one_name(self, raw, expected):
        assert canonical_category(raw) == expected

    def test_both_old_names_land_on_the_same_canonical(self):
        assert canonical_category("Mejor dirección artística") == canonical_category(
            "Mejor dirección de arte"
        )

    def test_every_merge_is_self_consistent(self):
        for merge in MERGES:
            for raw in merge["raws"]:
                assert canonical_category(raw) == merge["canonical"]


class TestNamesWeRefuseToMerge:
    """The reason these stay separate is that the source does not say which
    subtype they were. Splitting them would be inventing data."""

    @pytest.mark.parametrize("raw", [KEEP_LEGACY_SCREENPLAY, KEEP_LEGACY_SHORT])
    def test_historical_labels_pass_through(self, raw):
        assert canonical_category(raw) == raw

    def test_they_are_not_merged_into_the_current_ones(self):
        # A 1987 "Mejor guion" might have been original or adapted; we cannot know.
        assert canonical_category("Mejor guion") != "Mejor guion original"
        assert canonical_category("Mejor guion") != "Mejor guion adaptado"
        # A 1990 "Mejor cortometraje" might have been fiction, animation or documentary.
        for subtype in ("ficción", "animación", "documental"):
            assert canonical_category("Mejor cortometraje") != f"Mejor cortometraje de {subtype}"

    def test_each_kept_label_documents_why(self):
        for entry in KEPT_AS_IS:
            assert entry["why"]
            assert entry["editions"]


class TestUnaffectedCategories:
    @pytest.mark.parametrize(
        "raw",
        [
            "Mejor película",
            "Mejor dirección",
            "Mejor actor de reparto",
            "Mejor guion original",
            "Mejor cortometraje de ficción",
            "Mejor canción original",
        ],
    )
    def test_ordinary_categories_are_untouched(self, raw):
        assert canonical_category(raw) == raw
        assert raw not in CANONICAL_BY_RAW


class TestFutureProofing:
    def test_an_unknown_award_passes_through(self):
        # If the Academy adds a category, we keep working. It is canonical
        # until someone decides otherwise.
        assert canonical_category("Mejor invento del año") == "Mejor invento del año"

    def test_the_map_is_explicit_not_computed(self):
        """No fuzzy matching: a lookup table, so the result is predictable."""
        assert renamed_labels() == {
            "Mejor dirección artística": "Mejor dirección de arte",
            "Mejor película hispanoamericana": "Mejor película iberoamericana",
        }

    def test_canonical_values_are_themselves_keys(self):
        # So a canonical name can be fed back in unchanged.
        for canonical in CANONICAL_BY_RAW.values():
            assert canonical_category(canonical) == canonical


class TestMappingIsCoveredByTheData:
    """The mapping is a claim about the source, so it should be checked against
    the source. These run over the real 40-edition dataset."""

    @pytest.fixture(scope="class")
    @classmethod
    def document(cls):
        from goya_scraper import storage

        return storage.load()

    @staticmethod
    def raw_editions(document):
        result = {}
        for movie in document["movies"]:
            for nomination in movie["goya"]["nominations"]:
                result.setdefault(nomination["category_raw"], set()).add(
                    nomination["edition"]
                )
        return result

    @pytest.mark.skipif(
        not __import__("pathlib").Path("data/movies.json").exists(),
        reason="needs a generated dataset",
    )
    def test_renamed_awards_never_coexist_in_an_edition(self, document):
        raw_editions = self.raw_editions(document)
        for merge in MERGES:
            spans = [raw_editions.get(raw, set()) for raw in merge["raws"]]
            assert not (spans[0] & spans[1]), f"{merge['canonical']}: coexisten"

    @pytest.mark.skipif(
        not __import__("pathlib").Path("data/movies.json").exists(),
        reason="needs a generated dataset",
    )
    def test_renamed_awards_cover_contiguous_editions(self, document):
        raw_editions = self.raw_editions(document)
        for merge in MERGES:
            spans = sorted(
                (min(e), max(e))
                for e in (raw_editions.get(raw, set()) for raw in merge["raws"])
                if e
            )
            assert spans[1][0] == spans[0][1] + 1, f"{merge['canonical']}: no contiguas"

    @pytest.mark.skipif(
        not __import__("pathlib").Path("data/movies.json").exists(),
        reason="needs a generated dataset",
    )
    def test_every_raw_label_is_mapped_to_its_canonical(self, document):
        for movie in document["movies"]:
            for nomination in movie["goya"]["nominations"]:
                assert nomination["category"] == canonical_category(
                    nomination["category_raw"]
                )

    @pytest.mark.skipif(
        not __import__("pathlib").Path("data/movies.json").exists(),
        reason="needs a generated dataset",
    )
    def test_mapping_actually_reduces_the_number_of_names(self, document):
        raw = {
            n["category_raw"]
            for m in document["movies"]
            for n in m["goya"]["nominations"]
        }
        canonical = {
            n["category"]
            for m in document["movies"]
            for n in m["goya"]["nominations"]
        }
        assert len(canonical) < len(raw)
        assert len(canonical) == 31  # 33 raw names, two renames collapse a pair each