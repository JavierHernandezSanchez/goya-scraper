"""Normalisation rules. These are the rules most likely to silently corrupt data,
so they get their own tests with the exact strings found in the source."""

from goya_scraper.model import (
    clean_text,
    parse_countries,
    parse_duration,
    split_people,
)


class TestCleanText:
    def test_collapses_whitespace(self):
        assert clean_text("  La  vida\n  secreta \n de las palabras ") == (
            "La vida secreta de las palabras"
        )

    def test_none_stays_none(self):
        assert clean_text(None) is None

    def test_empty_becomes_none(self):
        # The source has plenty of empty <dd> elements. An empty string would
        # be indistinguishable from "we looked and found nothing".
        assert clean_text("   \n  ") is None


class TestSplitPeople:
    def test_single_name(self):
        assert split_people("Isabel Coixet") == ["Isabel Coixet"]

    def test_comma_separated(self):
        assert split_people("Isabel Peña, Mabel Lozano") == ["Isabel Peña", "Mabel Lozano"]

    def test_y_separated(self):
        assert split_people("Antonio Resines y Assumpta Serna") == [
            "Antonio Resines",
            "Assumpta Serna",
        ]

    def test_e_separated(self):
        # "e" instead of "y", found in Paco Bagur, Freddy Córdoba e Iban José
        assert split_people("Paco Bagur, Freddy Córdoba e Iban José") == [
            "Paco Bagur",
            "Freddy Córdoba",
            "Iban José",
        ]

    def test_mixed_separators(self):
        assert split_people(
            "Mónica Molina, Carolina Silva y Fernando Fernán- Gómez"
        ) == ["Mónica Molina", "Carolina Silva", "Fernando Fernán- Gómez"]

    def test_capital_y_inside_surname_is_not_a_separator(self):
        # "Agustín Díaz Yanes" is one person, not two.
        assert split_people("Agustín Díaz Yanes") == ["Agustín Díaz Yanes"]

    def test_over_splitting_is_the_accepted_trade_off(self):
        # A name that genuinely contains " y " will be split. We accept this on
        # purpose: splitting too much is far less harmful than not splitting,
        # because a merged name loses a nomination credit entirely.
        # Verified over 559 real person fields in this source: zero cases.
        assert split_people("Fernández y García") == ["Fernández", "García"]

    def test_duplicates_removed_keeping_order(self):
        # The source really does contain "Thomas Vinterberg, Thomas Vinterberg".
        assert split_people("Thomas Vinterberg, Thomas Vinterberg") == ["Thomas Vinterberg"]

    def test_apostrophe_is_fine(self):
        assert split_people("María Fernanda D'Ocon") == ["María Fernanda D'Ocon"]

    def test_empty_input_gives_empty_list(self):
        assert split_people(None) == []
        assert split_people("") == []


class TestParseCountries:
    def test_spain_variants_collapse(self):
        # 73% of films are either "España" or "Española". Both mean Spain.
        assert parse_countries("España") == (["España"], "España")
        assert parse_countries("Española") == (["España"], "Española")

    def test_comma_separated(self):
        assert parse_countries("España, Francia") == (
            ["España", "Francia"],
            "España, Francia",
        )

    def test_slash_separated(self):
        assert parse_countries("Dinamarca/Suecia") == (
            ["Dinamarca", "Suecia"],
            "Dinamarca/Suecia",
        )

    def test_y_separated(self):
        assert parse_countries("España, Francia y Portugal") == (
            ["España", "Francia", "Portugal"],
            "España, Francia y Portugal",
        )

    def test_raw_value_is_always_kept(self):
        # So the normalisation stays auditable and reversible.
        _, raw = parse_countries("  española,  Francia/Bélgica ")
        assert raw == "española, Francia/Bélgica"

    def test_unknown_country_is_kept_not_guessed(self):
        assert parse_countries("Narnia") == (["Narnia"], "Narnia")

    def test_empty_input(self):
        assert parse_countries(None) == ([], None)


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("105 minutos") == 105

    def test_missing_unit_still_parses(self):
        assert parse_duration("118") == 118

    def test_no_value(self):
        assert parse_duration(None) is None

    def test_no_digits(self):
        assert parse_duration("minutos") is None