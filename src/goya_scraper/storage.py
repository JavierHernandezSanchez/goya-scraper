"""Read and write data/movies.json.

This module knows about JSON and nothing about Goya. Building the document is
run.py's job; here we only load, shape and store it.
"""

import json
import logging
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .model import SITE_URL, Movie

log = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/movies.json")

# Bump when the structure of the document changes, so a file written by an
# older run is recognisable.
#   1: first version
#   2: data_quality.reported_by_source gained "award_categories"
#   3: nominations gained "category_raw" alongside the canonical "category"
SCHEMA_VERSION = 3


class CorruptDocumentError(RuntimeError):
    """The file exists but cannot be parsed."""


def empty_document() -> dict:
    """The document used when there is nothing to load."""
    return {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "source": SITE_URL,
            "generated_at": None,
            "editions_scraped": [],
            "counts": compute_counts([]),
        },
        "movies": [],
    }


def compute_counts(movies: list[dict]) -> dict:
    """Totals derived from the movies themselves. Never stored by hand."""
    nominations = [n for m in movies for n in m["goya"]["nominations"]]
    return {
        "editions": len({e for m in movies for e in m["goya"]["editions"]}),
        "movies": len(movies),
        "nominations": len(nominations),
        "awards": sum(1 for n in nominations if n["won"]),
        "distinct_categories": len({n["category"] for n in nominations}),
    }


def _sort_key(movie: dict) -> tuple[int, str, str]:
    """Sort by title, ignoring accents and case.

    Comparing raw strings would sort "Zambrano" before "Ámbar". We normalise
    instead of using locale.strxfrm, because that gives different results
    depending on the machine, and a dataset that reorders itself between runs is
    impossible to diff.

    Films without a title go last, so anything broken is easy to spot at the
    bottom of the file.
    """
    title = movie.get("title")
    if not title:
        return (1, "", "")
    folded = unicodedata.normalize("NFKD", title)
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return (0, stripped.casefold(), title)


def build_document(movies: list[Movie], editions: list[int]) -> dict:
    """Turn Movie objects into the full document, ready to be saved."""
    payload = sorted((m.to_dict() for m in movies), key=_sort_key)
    return {
        "_meta": {
            "schema_version": SCHEMA_VERSION,
            "source": SITE_URL,
            "generated_at": None,  # filled in by save()
            "editions_scraped": sorted(set(editions)),
            "counts": compute_counts(payload),
        },
        "movies": payload,
    }


def save(document: dict, path: Path = DEFAULT_PATH) -> Path:
    """Write the document atomically, refreshing timestamp and counts.

    Atomic means: write to a temporary file and rename. If the process dies
    halfway, the previous good file is still there.
    """
    document["_meta"]["counts"] = compute_counts(document["movies"])
    document["_meta"]["generated_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    log.info("wrote %s (%s movies)", path, len(document["movies"]))
    return path


def load(path: Path = DEFAULT_PATH) -> dict:
    """Read the document, or return an empty one when there is no file.

    A malformed file raises instead of returning empty: silently starting from
    scratch would overwrite data that a person may have edited by hand.
    """
    path = Path(path)
    if not path.exists():
        log.info("no existing %s, starting from scratch", path)
        return empty_document()

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorruptDocumentError(
            f"{path} is not valid JSON ({exc}). "
            "Fix it or delete it; it will not be overwritten silently."
        ) from exc

    # Tolerate a document written by an older run: fill in what is missing.
    document.setdefault("_meta", {}).setdefault("editions_scraped", [])
    document.setdefault("movies", [])
    document["_meta"].setdefault("schema_version", SCHEMA_VERSION)
    return document