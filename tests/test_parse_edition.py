"""Parsing a nominations page, using a real page from edition 36 (2022)."""

from goya_scraper.parse_edition import parse_edition

EDITION = 36
YEAR = 2022


def parse(html):
    return parse_edition(html, EDITION, YEAR)


class TestEdition36:
    def test_finds_every_category(self, edition_36):
        categories = {n.category for v in parse(edition_36).values() for n in v}
        assert len(categories) == 28

    def test_finds_every_nomination_row(self, edition_36):
        by_movie = parse(edition_36)
        assert sum(len(v) for v in by_movie.values()) == 114

    def test_finds_every_movie(self, edition_36):
        assert len(parse(edition_36)) == 51

    def test_one_winner_per_category(self, edition_36):
        by_movie = parse(edition_36)
        winners_per_category = {}
        for nominations in by_movie.values():
            for nomination in nominations:
                if nomination.won:
                    key = (nomination.edition, nomination.category)
                    winners_per_category[key] = winners_per_category.get(key, 0) + 1
        assert len(winners_per_category) == 28
        assert all(count == 1 for count in winners_per_category.values())

    def test_every_row_carries_the_edition_and_year(self, edition_36):
        for nominations in parse(edition_36).values():
            for nomination in nominations:
                assert nomination.edition == EDITION
                assert nomination.ceremony_year == YEAR

    def test_results_are_keyed_by_slug(self, edition_36):
        assert "el-buen-patron" in parse(edition_36)

    def test_row_without_movie_link_is_skipped_not_fatal(self):
        html = """
        <div class="peliculas">
          <section class="categoria-de-peliculas">
            <h1 class="categoria-de-peliculas__titulo">Mejor dirección</h1>
            <ul class="lista-de-peliculas">
              <li class="lista-de-peliculas__pelicula"></li>
              <li class="lista-de-peliculas__pelicula">
                <div class="lista-de-peliculas__cartel"><a href="/pelicula/buena"></a></div>
                <h2 class="lista-de-peliculas__titulo"><a>Alguien</a></h2>
              </li>
            </ul>
          </section>
        </div>
        """
        by_movie = parse(html)
        assert list(by_movie) == ["buena"]

    def test_empty_page_gives_empty_dict(self):
        assert parse("<html><body>nada</body></html>") == {}


class TestWinnerDetection:
    def test_winner_row(self, edition_36):
        by_movie = parse(edition_36)
        won = [
            n for v in by_movie.values() for n in v
            if n.won and n.category == "Mejor película"
        ]
        assert len(won) == 1
        # For this category the credited value is the film itself, not a person.
        assert won[0].credited == ["El buen patrón"]
        # And the note holds the producers, which is why we never throw it away.
        assert won[0].note == "Fernando León de Aranoa, Jaume Roures, Javier Méndez"

    def test_non_winner_rows(self, edition_36):
        by_movie = parse(edition_36)
        lost = [
            n for v in by_movie.values() for n in v
            if not n.won and n.category == "Mejor película"
        ]
        assert len(lost) == 4
        assert {n.credited[0] for n in lost} == {
            "Madres paralelas",
            "Maixabel",
            "Mediterráneo",
            "Libertad",
        }

    def test_marker_from_another_row_does_not_leak(self):
        # The winner image is looked up inside the row on purpose. If it were
        # searched document-wide, every row would look like a winner.
        html = """
        <div class="peliculas">
          <section class="categoria-de-peliculas">
            <h1 class="categoria-de-peliculas__titulo">Mejor película</h1>
            <ul class="lista-de-peliculas">
              <li class="lista-de-peliculas__pelicula">
                <img title="Ganadora del premio Goya a mejor película">
                <div class="lista-de-peliculas__cartel"><a href="/pelicula/ganadora"></a></div>
                <h2 class="lista-de-peliculas__titulo"><a>Gana</a></h2>
              </li>
              <li class="lista-de-peliculas__pelicula">
                <div class="lista-de-peliculas__cartel"><a href="/pelicula/pierde"></a></div>
                <h2 class="lista-de-peliculas__titulo"><a>Piende</a></h2>
              </li>
            </ul>
          </section>
        </div>
        """
        by_movie = parse(html)
        assert by_movie["ganadora"][0].won is True
        assert by_movie["pierde"][0].won is False


class TestCreditedNames:
    def test_person_is_split(self, edition_36):
        by_movie = parse(edition_36)
        nominations = [
            n for n in by_movie["el-buen-patron"] if n.category == "Mejor dirección"
        ]
        assert nominations[0].credited == ["Fernando León de Aranoa"]

    def test_film_category_credits_the_film_itself(self, edition_36):
        by_movie = parse(edition_36)
        nominations = [
            n for n in by_movie["el-buen-patron"] if n.category == "Mejor película"
        ]
        # Not a person: the source shows the title for this category. We do not
        # reinterpret it.
        assert nominations[0].credited == ["El buen patrón"]

    def test_two_people_in_one_credit(self, edition_36):
        by_movie = parse(edition_36)
        nominations = [
            n for n in by_movie["mediterraneo"]
            if n.category == "Mejor dirección de producción"
        ]
        assert nominations[0].credited == ["Albert Espel", "Kostas Sfakianakis"]

    def test_awkward_source_value_is_kept_verbatim(self, edition_36):
        # The page really reads "Libertad, de Clara Roquet": the film is
        # "Libertad" and the comma introduces its director, whose surname is
        # "de Clara Roquet". We split what the source gives us without judging it.
        by_movie = parse(edition_36)
        nominations = [
            n for n in by_movie["libertad-de-clara-roquet"]
            if n.category == "Mejor película"
        ]
        assert nominations[0].credited == ["Libertad", "de Clara Roquet"]

    def test_song_category_keeps_its_odd_format(self, edition_36):
        # "Te espera el mar - Compositores: Maria José Llergo" — the source puts
        # the song title in the credited slot for this category. It also proves
        # the " y "/" e " splitter leaves ordinary Spanish words alone.
        by_movie = parse(edition_36)
        nominations = [
            n for n in by_movie["mediterraneo"] if n.category == "Mejor canción original"
        ]
        assert nominations[0].credited == ["Te espera el mar - Compositores: Maria José Llergo"]


class TestSeveralNomineesInTheSameCategory:
    def test_three_actors_in_one_category(self, edition_36):
        # El buen patrón had three actors nominated for supporting actor.
        # This is why total_nominations counts rows, not categories (ADR-007).
        by_movie = parse(edition_36)
        actors = [
            n for n in by_movie["el-buen-patron"]
            if n.category == "Mejor actor de reparto"
        ]
        assert len(actors) == 3
        assert [n.credited[0] for n in actors] == [
            "Celso Bugallo",
            "Fernando Albizu",
            "Manolo Solo",
        ]
        assert not any(n.won for n in actors)


class TestOlderEdition:
    def test_edition_1_has_its_own_categories(self, edition_1):
        by_movie = parse_edition(edition_1, 1, 1987)
        categories = {n.category for v in by_movie.values() for n in v}
        assert len(categories) == 15
        assert sum(len(v) for v in by_movie.values()) == 44
        assert len(by_movie) == 22

    def test_category_names_changed_over_the_years(self, edition_1, edition_36):
        """Renamed awards keep both names: canonical and raw (ADR-009)."""
        old = parse_edition(edition_1, 1, 1987)
        new = parse(edition_36)

        old_categories = {n.category for v in old.values() for n in v}
        new_categories = {n.category for v in new.values() for n in v}

        # "Mejor guion" is a historical award of its own: kept, not split into
        # original/adaptado, because the site never says which one it was.
        assert "Mejor guion" in old_categories
        assert "Mejor guion" not in new_categories
        assert "Mejor guion original" in new_categories
        assert old_categories != new_categories

    def test_renamed_award_is_canonicalised_keeping_the_raw_label(self, edition_1, edition_36):
        """The site said "Mejor dirección artística"; we store that name under
        the current one, and keep the original visible."""
        old = parse_edition(edition_1, 1, 1987)
        new = parse(edition_36)

        old_raws = {n.category_raw for v in old.values() for n in v}
        new_raws = {n.category_raw for v in new.values() for n in v}
        new_canonical = {n.category for v in new.values() for n in v}

        assert "Mejor dirección artística" in old_raws
        assert "Mejor dirección artística" in new_raws
        # Both editions resolve to the same canonical name.
        assert "Mejor dirección de arte" in new_canonical
        old_canonical = {n.category for v in old.values() for n in v}
        assert "Mejor dirección de arte" in old_canonical

    def test_award_that_was_never_renamed_keeps_both_equal(self, edition_36):
        for nominations in parse(edition_36).values():
            for nomination in nominations:
                if nomination.category_raw.startswith("Mejor cortometraje"):
                    assert nomination.category == nomination.category_raw