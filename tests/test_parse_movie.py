"""Parsing a movie page, using real pages from edition 36 (2022)."""

import pathlib
import re

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


class TestPoster:
    """219 of the 1678 real films have no poster, so both cases are normal."""

    def test_the_poster_url_is_absolute(self, buen_patron):
        movie = parse_movie(buen_patron, "el-buen-patron")
        assert movie.poster_url == (
            "https://www.premiosgoya.com/wp-content/uploads/2021/11/system/uploads"
            "/feature_film/poster/2150/EL_BUEN_PATRON_76x101_baja-320x457.jpg"
        )

    def test_a_relative_path_is_resolved_against_the_site(self):
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
          <img class="attachment-cartel size-cartel" src="/wp-content/uploads/a.jpg">
        </article>
        """
        movie = parse_movie(html, "ejemplo")
        assert movie.poster_url == "https://www.premiosgoya.com/wp-content/uploads/a.jpg"

    def test_the_social_icons_are_not_mistaken_for_the_poster(self):
        # The page carries Twitter/Facebook/... SVGs. Keying on the class rather
        # than on `img` is what keeps them out.
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
          <img src='/wp-content/themes/goya/img/redes/Twitter.svg'>
          <img src='/wp-content/themes/goya/img/redes/Facebook.svg'>
        </article>
        """
        movie = parse_movie(html, "ejemplo")
        assert movie.poster_url is None

    def test_a_page_without_a_poster_has_none(self):
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
        </article>
        """
        movie = parse_movie(html, "sin-cartel")
        assert movie.poster_url is None

    def test_an_empty_src_is_not_a_poster(self):
        html = """
        <article class="pelicula">
          <div class="pelicula__header__titulo"><h1>Ejemplo</h1></div>
          <img class="attachment-cartel" src="">
        </article>
        """
        movie = parse_movie(html, "vacia")
        assert movie.poster_url is None

    def test_the_path_is_not_set_by_parsing(self, buen_patron):
        # Parsing says what the site claims; downloading is a separate step.
        # Keeping them apart is what lets poster_url and poster_path answer two
        # different "why is this missing" questions.
        movie = parse_movie(buen_patron, "el-buen-patron")
        assert movie.poster_url is not None
        assert movie.poster_path is None

    def test_every_fixture_poster_comes_from_the_site(self, load):
        for name in ("el-buen-patron", "maixabel", "otra-ronda", "yalla"):
            movie = parse_movie(load(f"pelicula_{name}.html"), name)
            assert movie.poster_url.startswith("https://www.premiosgoya.com/")


class TestTheSelectorCoversEveryContentImage:
    """The guard against losing a group of films to a CSS class.

    The first version of the selector matched only `attachment-cartel` and
    silently dropped the 219 films the theme tags `attachment-galeria`. The
    check that catches that is not "does it find the one I know about" but
    "does it find every image the site published".
    """

    CONTENT_IMAGE = re.compile(r'<img[^>]*src="(/wp-content/uploads/[^"]+)"')

    def _cache_files(self):
        root = pathlib.Path("cache")
        if not root.is_dir():
            pytest.skip("needs the downloaded cache")
        return sorted(root.glob("pelicula_*.html"))

    def test_no_content_image_is_left_out(self):
        missed = []
        for path in self._cache_files():
            html = path.read_text(encoding="utf-8", errors="replace")
            slug = path.stem.replace("pelicula_", "")
            movie = parse_movie(html, slug)
            found = {m for m in self.CONTENT_IMAGE.findall(html)}
            # One content image per film page, and the selector must find it.
            if len(found) != 1:
                missed.append(f"{slug}: {len(found)} imagenes de contenido")
                continue
            if movie.poster_url is None:
                missed.append(f"{slug}: sin poster_url")
            elif not movie.poster_url.endswith(found.pop()):
                missed.append(f"{slug}: se equivoco de imagen")
        assert not missed, missed[:5]

    def test_every_film_ends_up_with_a_poster(self):
        without = [
            path.stem.replace("pelicula_", "")
            for path in self._cache_files()
            if parse_movie(
                path.read_text(encoding="utf-8", errors="replace"),
                path.stem.replace("pelicula_", ""),
            ).poster_url
            is None
        ]
        assert not without, f"{len(without)} pelicula(s) sin cartel: {without[:5]}"

    def test_both_classes_are_known(self):
        """Pins the inconsistency, so a third class fails loudly."""
        classes = set()
        for path in self._cache_files():
            html = path.read_text(encoding="utf-8", errors="replace")
            for match in re.findall(r'<img[^>]*class="([^"]+)"[^>]*>', html):
                if "attachment" in match:
                    classes.add(match)
        assert classes == {"attachment-cartel size-cartel",
                           "attachment-galeria size-galeria"}


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