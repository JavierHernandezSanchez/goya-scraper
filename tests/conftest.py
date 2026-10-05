from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load():
    """Return a function that reads a saved real page from tests/fixtures/."""

    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read


@pytest.fixture
def home(load) -> str:
    """The home page index: the list of all 40 editions with their years."""
    return load("home.html")


@pytest.fixture
def edition_36(load) -> str:
    """Goya 36 (ceremony 2022): 28 categories, 114 rows, 51 films."""
    return load("edicion_36_nominaciones.html")


@pytest.fixture
def edition_1(load) -> str:
    """Goya 1 (ceremony 1987): the oldest edition, 15 categories, 22 films."""
    return load("edicion_1_nominaciones.html")


@pytest.fixture
def buen_patron(load) -> str:
    """20 nominations, 6 awards, "Española" as country, several actors in one category."""
    return load("pelicula_el-buen-patron.html")


@pytest.fixture
def maixabel(load) -> str:
    return load("pelicula_maixabel.html")


@pytest.fixture
def otra_ronda(load) -> str:
    """The most complete page: it does have a 'Título original' (Druk)."""
    return load("pelicula_otra-ronda.html")


@pytest.fixture
def yalla(load) -> str:
    """Won nothing, so the site omits the 'Goyas' counter entirely."""
    return load("pelicula_yalla.html")


@pytest.fixture
def not_found(load) -> str:
    return load("error_404.html")