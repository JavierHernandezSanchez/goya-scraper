"""Curated category names.

The Academy renamed a few awards over 40 years, so the site reports whatever
label was in force that year and the raw data ends up with more names than real
awards. This module maps them onto a canonical catalogue.

Two rules, and both matter more than the mapping itself:

1. **We only merge names we can justify.** No fuzzy similarity, no guessing. Each
   merge below is a rename the data confirms: the two labels never appear in the
   same edition and they cover contiguous editions.
2. **What we cannot justify stays as it is.** "Mejor guion" and "Mejor cortometraje"
   are historical labels of their own. The site never says whether a 1987
   "Mejor guion" was original or adapted, nor whether a 1990 "Mejor cortometraje"
   was fiction, animation or documentary. Splitting them would be inventing data,
   so they become canonical names in their own right.

The original label is always kept: every nomination carries both `category`
(canonical) and `category_raw` (what the site said), which makes the mapping fully
reversible and auditable (ADR-009).
"""

# Canonical names for the historical labels we deliberately keep distinct.
KEEP_LEGACY_SCREENPLAY = "Mejor guion"
KEEP_LEGACY_SHORT = "Mejor cortometraje"


#: raw label -> canonical label. Only entries that change something; anything not
#: listed is already canonical.
CANONICAL_BY_RAW: dict[str, str] = {
    # 1987-2022 then 2023-2026. Contiguous, never both in one edition.
    "Mejor dirección artística": "Mejor dirección de arte",
    "Mejor dirección de arte": "Mejor dirección de arte",
    # 2009-2010 then 2011-2026. Same pattern.
    "Mejor película hispanoamericana": "Mejor película iberoamericana",
    "Mejor película iberoamericana": "Mejor película iberoamericana",
    # Kept, not merged: historical awards of their own.
    KEEP_LEGACY_SCREENPLAY: KEEP_LEGACY_SCREENPLAY,
    KEEP_LEGACY_SHORT: KEEP_LEGACY_SHORT,
}

# Edits that reduced the number of distinct names. Kept as data so the docs and
# the validation report cannot drift apart from the code.
MERGES = (
    {
        "canonical": "Mejor dirección de arte",
        "raws": ("Mejor dirección artística", "Mejor dirección de arte"),
        "editions": ("1-36", "37-40"),
        "why": "la Academia renombró el premio; ediciones contiguas y sin solape",
    },
    {
        "canonical": "Mejor película iberoamericana",
        "raws": ("Mejor película hispanoamericana", "Mejor película iberoamericana"),
        "editions": ("23-24", "25-40"),
        "why": "la Academia renombró el premio; ediciones contiguas y sin solape",
    },
)

# Labels that stay exactly as the site wrote them, with the reason.
KEPT_AS_IS = (
    {
        "label": KEEP_LEGACY_SCREENPLAY,
        "editions": "1-2",
        "why": "la fuente no dice si era original o adaptado, así que no se reparte",
    },
    {
        "label": KEEP_LEGACY_SHORT,
        "editions": "4-6, 12, 15",
        "why": "la fuente no dice si era ficción, animación o documental",
    },
)


def canonical_category(raw: str) -> str:
    """Return the canonical name for a raw label.

    Unknown labels pass through unchanged, on purpose: if the Academy adds an
    award, the scraper keeps working and the new name simply is itself until
    someone decides what it should be called.
    """
    return CANONICAL_BY_RAW.get(raw, raw)


def renamed_labels() -> dict[str, str]:
    """Raw labels whose canonical name differs, for the validation report."""
    return {
        raw: canonical
        for raw, canonical in CANONICAL_BY_RAW.items()
        if raw != canonical
    }