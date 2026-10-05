"""Names the Academy spells more than one way, and which spelling is right.

The source has no person identifier. People exist only as free text, and over 40
editions the same human arrives spelled two or three ways: accents dropped,
capital letters changed, hyphens moved. Left alone, ``Paco De Lucía`` and
``Paco de Lucía`` become two people, and ``Luis Tosar`` stops being the actor
with the most films in the database.

So this module is a **human decision**, not a function of the text. Every entry
below was looked at and judged. There is no normaliser behind it, on purpose:

* Picking the *most frequent* spelling is wrong. Measured on the real dataset:
  ``Iciar Bollain`` appears 34 times and ``Icíar Bollaín`` only 5, yet the first
  is the misspelling. ``Tina Sáinz`` and ``José Luís Quirós`` (an ``l`` for an
  ``ll``) win on frequency too. And **25 of the 90 groups are exact ties on
  frequency**, so the data cannot decide them at all.
* Picking *any* spelling by a rule gets it wrong on both sides: folding case
  turns ``Paco de Lucía`` into ``Paco De Lucía``; folding accents turns
  ``Loles león`` into ``Loles León``.

What we merge is therefore narrow and checkable. Two spellings belong to the same
group only when they are **equal once** you (a) normalise Unicode, (b) drop
accents, (c) collapse whitespace and (d) ignore hyphens and apostrophes. That is
an equality, not a similarity, so grouping involves no judgement — only the
choice of which member of the group is spelled correctly does.

What we do **not** merge lives in `NEAR_DUPLICATES_ARE_NOT_MERGED` below, and
`near_duplicates()` surfaces the rest on demand so the validator can report them
instead of the importer guessing.
"""

import re
import unicodedata

from difflib import SequenceMatcher

#: Hyphens and apostrophes are not part of a name, so they are dropped before
#: grouping. Same regex swallows the stray spaces the site leaves around them,
#: as in ``José Luis López- Linares``.
_SEPARATORS = re.compile(r"[\s\-'’`´]+")

#: Threshold for *reporting* look-alikes. Never used to merge.
NEAR_DUPLICATE_RATIO = 0.90


def _fold(name: str) -> str:
    """Normalised form used for grouping: no accents, no separators, lowercase."""
    decomposed = unicodedata.normalize("NFD", name)
    without_accents = "".join(
        c for c in decomposed if unicodedata.category(c) != "Mn"
    )
    collapsed = re.sub(r"\s+", " ", without_accents).strip()
    return _SEPARATORS.sub("", collapsed).lower()


#: Correct spelling -> the other spellings the source also uses.
#:
#: Left side is "the correct name", right side is "what we found instead".
#: 90 groups covering 187 spellings; 97 of them stop being separate people.
#: Sorted by canonical name so a diff is readable and a gap stands out.
SAME_PERSON: dict[str, tuple[str, ...]] = {
    "Adrià Collado": ("Adriá Collado",),
    "Aitana Sánchez-Gijón": ("Aitana Sánchez- Gijón",),
    "Álex Brendemühl": ("Alex Brendemühl",),
    "Álex Casanovas": ("Àlex Casanovas",),
    "Álex Villagrasa": ("Alex Villagrasa", "Àlex Villagrasa"),
    "Ana López-Puigcerver": ("Ana López Puigcerver",),
    "Ángel E. Pariente": ("Angel E. Pariente",),
    "Ángel Illarramendi": ("Angel Illarramendi",),
    "Ángeles González-Sinde": ("Ángeles González- Sinde",),
    "Antxón Gómez": ("Antxon Gómez",),
    "Antonio del Real": ("Antonio Del Real",),
    "Antonio Giménez-Rico": ("Antonio Giménez Rico",),
    "Antonio Isasi-Isasmendi": ("Antonio Isasi- Isasmendi",),
    "Arturo Pérez-Reverte": ("Arturo Pérez Reverte",),
    "Asier Etxeandía": ("Asier Etxeandia",),
    "Aurelio Sánchez-Herrera": ("Aurelio Sánchez Herrera",),
    "Carlos Azpurúa": ("Carlos Azpúrua",),
    "Cristina Sola": ("Cristina Solá",),
    "Daniel Giménez-Cacho": ("Daniel Giménez Cacho",),
    "Demián Bichir": ("Demian Bichir",),
    "Édgar Vittorino": ("Edgar Vittorino",),
    "Eduardo Chapero-Jackson": ("Eduardo Chapero- Jackson",),
    "Emilio Martínez-Lázaro": ("Emilio Martínez- Lázaro",),
    "Emilio Ruiz del Río": ("Emilio Ruíz del Río",),
    "Eulàlia Ramon": ("Eulalia Ramón",),
    "Érica Rivas": ("Erica Rivas",),
    "Ferran Piquer": ("Ferrán Piquer",),
    "Fernando Fernán-Gómez": ("Fernando Fernán- Gómez",),
    "Fernando Guillén Cuervo": ("Fernándo Guillén Cuervo",),
    "Félix Bergés": ("Felix Bergés",),
    "Fermí Reixach": ("Fermi Reixach",),
    "Helena Sanchís": ("Helena Sanchis",),
    "Icíar Bollaín": ("Iciar Bollain",),
    "Iñaki Peñafiel": ("Iñaki Penafiel",),
    "J.A. Bayona": ("J. A. Bayona",),
    "Jaime Marques-Olarreaga": ("Jaime Marques Olarreaga",),
    "Jaime Marqués": ("Jaime Marques",),
    "Jaime Ordóñez": ("Jaime Ordoñez",),
    "Joaquín Jordá": ("Joaquín Jorda",),
    "Joaquín Oristrell": ("Joaquin Oristrell",),
    "Jordi Mollà": ("Jordi Mollá",),
    "Jorge Sánchez-Cabezudo": ("Jorge Sánchez Cabezudo",),
    "Jonás Trueba": ("Jonas Trueba",),
    "Juan Pérez Fajardo": ("Juan Pérez- Fajardo",),
    "José Ángel Esteban": ("José Angel Esteban",),
    "José Corbacho": ("Jose Corbacho",),
    "José Coronado": ("Jose Coronado",),
    "José Luis García-Pérez": ("José Luis García Pérez",),
    "José Luis López-Linares": (
        "José Luis López Linares",
        "Jose Luis López-Linares",
        "José Luis López- Linares",
    ),
    "José Luis Quirós": ("José Luís Quirós",),
    "José Mari Goenaga": ("Jose Mari Goenaga",),
    "José María Yazpik": ("José María Yázpik",),
    "José Quetglás": ("Jose  Quetglás", "Jose Quetglás", "José Quetglas"),
    "Julia Juániz": ("Julia Juaniz",),
    "Lluís Homar": ("LLuìs Homar",),
    "Lluís Rivera Jove": ("Lluis Rivera Jove",),
    "Loles León": ("Loles león",),
    "Manuel José Chávez": ("Manuel José Chavez",),
    "Mapi Galán": ("Mapi Galan",),
    "María de Medeiros": ("Maria de Medeiros",),
    "María Ripoll": ("Maria Ripoll",),
    "Marián Aguilera": ("Marian Aguilera",),
    "Marçal Cebrián": ("Marçal Cebrian",),
    "Mercè Llorens": ("Mercé Llorens",),
    "Mercè Paloma": ("Mercé Paloma",),
    "Mercè Pons": ("Mercé Pons",),
    "Miguel Ángel Solá": ("Miguel Angel Solá",),
    "Miriam Díaz-Aroca": ("Miriam Díaz Aroca",),
    "Nacho Royo-Villanova": ("Nacho Royo Villanova",),
    "Nereida Bonmatí": ("Nereida Bonmati",),
    "Nicolás de Poulpiquet": ("Nicolas de Poulpiquet",),
    "Núria Prims": ("Nuria Prims",),
    "Óscar de Julián": ("Oscar de Julián",),
    "Olivier Martínez": ("Olivier Martinez",),
    "Paco de Lucía": ("Paco De Lucía",),
    "Pancho Monleón": ("Pancho Monléon",),
    "Ramón Fontserè": ("Ramón Fontsere",),
    "Rafael Álvarez 'El Brujo'": ("Rafael Álvarez El Brujo",),
    "Regina Álvarez Lorenzo": ("Regina Alvarez Lorenzo",),
    "Ricardo Darín": ("Ricardo Darin",),
    "Roger Príncep": ("Roger Princep",),
    "Román Gubern": ("Roman Gubern",),
    "Rosa María Sardà": (
        "Rosa Maria Sardà",
        "Rosa María Sardá",
        "Rosa Maria Sarda",
    ),
    "Salvador García Ruiz": ("Salvador García Ruíz",),
    "Santiago Thevenet": ("Santiago Thévenet",),
    "Sergio Bürmann": ("Sergio Burmann",),
    "Sergio Peris-Mencheta": ("Sergio Peris Mencheta",),
    "Teresa de Pelegrí": ("Teresa De Pelegri",),
    "Teresa Pelegrí": ("Teresa Pelegri",),
    "Tina Sainz": ("Tina Sáinz",),
}


#: Look-alike pairs a human has already looked at and decided to keep apart.
#: The reason is here so nobody re-litigates them from scratch.
NEAR_DUPLICATES_ARE_NOT_MERGED: dict[tuple[str, str], str] = {
    ("Agustí Villaronga", "Agustín Villaronga"): (
        "el uno dirige y el otro escribe; son dos personas"
    ),
    ("Eduard Fernández", "Eduardo Fernández"): (
        "actor y director distintos; coincide el nombre y el origen"
    ),
    ("Carme Elías", "Carmen Elías"): "actriz y responsable de política cultural",
    ("Joaquim Jordà", "Joaquín Jordá"): "productor y director",
    ("Juan Luis Galiardo", "Juan Luis Gallardo"): (
        "posible errata de apellido, no confirmada; se dejan separados"
    ),
    ("Sergio Castellito", "Sergio Castellitto"): (
        "variantes del mismo apellido; sin confirmación se dejan separados"
    ),
    ("Teresa Pelegrí", "Teresa de Pelegrí"): (
        "el mismo nombre con y sin 'de'; sin más evidencia se dejan separadas"
    ),
}


# ---------------------------------------------------------------- lookup ----


def _build_lookup() -> dict[str, str]:
    """alias -> canonical, canonicals included so a canonical maps to itself."""
    lookup: dict[str, str] = {}
    for canonical, aliases in SAME_PERSON.items():
        lookup[canonical] = canonical
        for alias in aliases:
            lookup[alias] = canonical
    return lookup


_BY_ALIAS: dict[str, str] = _build_lookup()


def canonical_name(alias: str) -> str:
    """The spelling we store for this alias. Unreviewed names pass through.

    Never guesses. A name nobody has looked at comes back exactly as written,
    which is the only honest answer.
    """
    return _BY_ALIAS.get(alias, alias)


def merged_aliases() -> dict[str, str]:
    """alias -> canonical for the aliases only, canonicals excluded."""
    return {
        alias: canonical
        for canonical, aliases in SAME_PERSON.items()
        for alias in aliases
    }


def folded_groups(names) -> list[list[str]]:
    """Group names equal once separators and accents are ignored.

    The evidence behind `SAME_PERSON`, recomputed from the data so a test can
    check the curated table is complete instead of trusting it.
    """
    buckets: dict[str, list[str]] = {}
    for name in names:
        buckets.setdefault(_fold(name), []).append(name)
    return sorted(
        (sorted(group) for group in buckets.values() if len(group) > 1),
        key=lambda group: group[0],
    )


def near_duplicates(names, ratio: float = NEAR_DUPLICATE_RATIO):
    """Pairs that look like one person and are deliberately **not** merged.

    Anything closer than `ratio` once accents are gone is reported so a human
    can look at it. On the real dataset this finds ~300 pairs, almost all of them
    genuinely different people (``Pablo Gago`` and ``Pablo Rago``), which is
    why it is reported and never acted on.
    """
    unique = sorted({_fold(name): name for name in names}.values())

    buckets: dict[str, list[str]] = {}
    for name in unique:
        buckets.setdefault(name[:5], []).append(name)

    pairs: set[tuple[str, str]] = set()
    for block in buckets.values():
        if len(block) < 2:
            continue
        for index, left in enumerate(block):
            for right in block[index + 1 :]:
                if SequenceMatcher(None, _fold(left), _fold(right)).ratio() >= ratio:
                    pairs.add((left, right) if left < right else (right, left))

    return [
        (
            left,
            right,
            round(SequenceMatcher(None, _fold(left), _fold(right)).ratio(), 3),
        )
        for left, right in sorted(pairs)
    ]