"""Parsing a movie page, using real pages from edition 36 (2022)."""

import pytest

from goya_scraper.parse_movie import NotAMoviePageError, parse_movie


class TestRichMoviePage:
    """El buen patrón: 20 nominations, 6 awards, 6 definition-list fields."""

    @pytest.fixture
    def movie(self, buen_patron):
        return parse_movie(buen_patron, "el-buen-patron")

    def test_title(self, movie):
        assert movie.title == "El buen patrón"

    def test_slug_comes_from_the_caller(self, movie):
        # The page itself never says its slug; we take it from the URL we asked for.
        assert movie.slug == "el-buen-patron"

    def test_countries_normalised_and_raw_kept(self, movie):
        # The source says "Española" (referring to the film, not the country).
        # 73% of films use one form or the other, so both must map to España
        # while the raw value stays available.
        assert movie.countries == ["España"]
        assert movie.countries_raw == "Española"

    def test_directors(self, movie):
        assert movie.credits.directors == ["Fernando León de Aranoa"]

    def test_screenwriters(self, movie):
        assert movie.credits.screenwriters == ["Fernando León de Aranoa"]

    def test_cast(self, movie):
        assert "Javier Bardem" in movie.credits.cast
        assert "Manolo Solo" in movie.credits.cast

    def test_producers_stay_raw(self, movie):
        # A string, not a list: company names contain commas, so splitting them
        # would invent data (ADR-008).
        assert isinstance(movie.credits.producers_raw, str)
        assert movie.credits.producers_raw == (
            "Reposado Producciones Cinematográficas, Básculas Blanco, A.I.E, "
            "Mediaproducción, S.L.U."
        )

    def test_duration_is_an_integer(self, movie):
        assert movie.duration_minutes == 115

    def test_sinopsis(self, movie):
        assert movie.synopsis.startswith("Básculas Blanco")
        assert len(movie.synopsis) > 100

    def test_absent_fields_are_reported(self, movie):
        assert movie.title_original is None
        assert "title_original" in movie.missing_fields

    def test_self_reported_counters(self, movie):
        assert movie.reported_nominations == 20
        assert movie.reported_awards == 6


class TestMostCompleteMoviePage:
    """Otra ronda: the only fixture that has a 'Título original' field."""

    def test_title_original_present_and_not_listed_as_missing(self, otra_ronda):
        movie = parse_movie(otra_ronda, "otra-ronda")
        # A real case where the field adds information: the Spanish release
        # title differs from the original.
        assert movie.title_original == "Druk"
        assert "title_original" not in movie.missing_fields

    def test_nothing_is_missing(self, otra_ronda):
        movie = parse_movie(otra_ronda, "otra-ronda")
        assert movie.missing_fields == []

    def test_source_typos_are_kept_verbatim(self, otra_ronda):
        # The site itself reads "Zentropa Entertainments3 ApS" (missing space).
        # We do not correct the source; that would be inventing data.
        assert "Zentropa Entertainments3 ApS" in parse_movie(otra_ronda, "otra-ronda").credits.producers_raw


class TestMovieWithoutAwards:
    """Yalla won nothing, so the site omits the 'Goyas' counter entirely."""

    @pytest.fixture
    def movie(self, yalla):
        return parse_movie(yalla, "yalla")

    def test_missing_awards_counter_means_zero_not_unknown(self, movie):
        # The easy bug to write here: treating the absent element as None.
        assert movie.reported_awards == 0

    def test_nominations_counter_still_read(self, movie):
        assert movie.reported_nominations == 1

    def test_absent_fields_listed(self, movie):
        assert movie.title_original is None
        assert movie.missing_fields  # at least title_original


class TestCountries:
    def test_single_country(self, maixabel):
        movie = parse_movie(maixabel, "maixabel")
        assert movie.countries == ["España"]
        assert movie.countries_raw == "Española"

    def test_slash_separated_countries(self):
        # "Dinamarca/Suecia" is a real value in this source.
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
          <dl><div><dt>Nacionalidad</dt><dd>Dinamarca/Suecia</dd></div></dl>
        </article>
        """
        movie = parse_movie(html, "ejemplo")
        assert movie.countries == ["Dinamarca", "Suecia"]
        assert movie.countries_raw == "Dinamarca/Suecia"

    def test_nested_interpretes_div_is_handled(self):
        # <dd class="interpretes"><div class="interpretes-lista">A, B</div></dd>
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
          <dl><div><dt>Intérpretes</dt><dd class="interpretes">
            <div class="interpretes-lista">Ana Paz, Luis Paz</div>
          </dd></div></dl>
        </article>
        """
        assert parse_movie(html, "ejemplo").credits.cast == ["Ana Paz", "Luis Paz"]


class TestRejectsNonMoviePages:
    def test_404_page_raises(self, not_found):
        with pytest.raises(NotAMoviePageError):
            parse_movie(not_found, "no-existe")

    def test_empty_html_raises(self):
        with pytest.raises(NotAMoviePageError):
            parse_movie("<html><body></body></html>", "vacio")


class TestTextCleanup:
    def test_html_entities_are_decoded(self):
        # Real title in the source: "Blue & Malone, detectives imaginarios"
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Blue &amp; Malone</h1></div>
        </article>
        """
        movie = parse_movie(html, "blue-malone")
        assert movie.title == "Blue & Malone"