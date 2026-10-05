"""What a category's `credited` field actually holds.

The nominations page prints one text per row, in a column whose heading depends
on the award. Reading all 40 editions shows that column means **three different
things**, and the database has to know which one before it can store a credit:

* ``person`` — a person's name. 20 categories, 3922 credits.
  **Not one** of them is a film title.
* ``work`` — the film's own title. 10 categories, 1158 credits. The nominee *is*
  the movie we already have in ``nomination.movie_id``.
* ``song`` — "<song> - Compositores: <names>". 1 category, 197 credits. A third
  thing: neither a person nor a film.

This is a lookup table and not a rule, for the same reason as ``categories.py``:
guessing would be worse than saying we do not know. A category is an award, and
the Academy decides what it is. If it adds a new award, this module stays silent
and ``credited_kind`` reports ``None`` so the caller can refuse to guess.

Two facts that make the table trustworthy rather than decorative:

1. The three kinds are mutually exclusive and exhaustive over the 31 canonical
   categories, verified on all 4050 real nominations.
2. A category's kind never changes across editions. If it ever did, the import
   would be mixing two meanings in one table.
"""

from typing import Literal

CreditedKind = Literal["person", "work", "song"]

#: The 10 awards whose nominee is the work itself.
WORK_CATEGORIES: tuple[str, ...] = (
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
)

#: The 1 award whose nominee is a song, with its composers inside the same string.
SONG_CATEGORIES: tuple[str, ...] = ("Mejor canción original",)


def _person_categories() -> tuple[str, ...]:
    """The remaining awards: everything the Academy credits to a person.

    Spelled out rather than derived, on purpose. Deriving it as "whatever is
    left over" would mean this module silently reclassifies a new category the
    moment somebody adds one, which is exactly the guessing we are avoiding.
    """
    return (
        "Mejor actor de reparto",
        "Mejor actor protagonista",
        "Mejor actor revelación",
        "Mejor actriz de reparto",
        "Mejor actriz protagonista",
        "Mejor actriz revelación",
        "Mejor dirección",
        "Mejor dirección de arte",
        "Mejor dirección de fotografía",
        "Mejor dirección de producción",
        "Mejor dirección novel",
        "Mejor diseño de vestuario",
        "Mejor guion",
        "Mejor guion adaptado",
        "Mejor guion original",
        "Mejor maquillaje y peluquería",
        "Mejor montaje",
        "Mejor música original",
        "Mejor sonido",
        "Mejores efectos especiales",
    )


CREDITED_KINDS: dict[str, CreditedKind] = {
    **{name: "work" for name in WORK_CATEGORIES},
    **{name: "song" for name in SONG_CATEGORIES},
    **{name: "person" for name in _person_categories()},
}

#: The three meanings, with the reason each exists. Kept as data so the docs and
#: the validation report cannot drift away from the code.
KIND_WHY: dict[str, str] = {
    "person": "la columna nombra a la persona competitors; el rol se deduce de la categoría",
    "work": "la columna repite el título de la propia película; ya está en movie_id",
    "song": "la columna mezcla el título de la canción con sus compositores",
}


def credited_kind(category: str) -> CreditedKind | None:
    """Return what `credited` holds for this category, or None if we don't know.

    Returning None instead of a default matters: the importer must be able to
    refuse. A new award whose column we have never inspected has to stop the
    import with a question, not land in `person` because that is the fallback
    someone forgot to think about.
    """
    return CREDITED_KINDS.get(category)


def known_categories() -> frozenset[str]:
    return frozenset(CREDITED_KINDS)