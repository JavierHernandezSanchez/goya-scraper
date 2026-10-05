"""Conexion y creacion de la base de datos SQLite.

Este modulo sabe de tablas. No sabe de Goya ni de JSON: importar un documento es
trabajo de `import_db`, y escribirlo en disco, de `storage`. Esa separacion es lo
que permite que el scraper crezca sin importar nunca `sqlite3`.

Una decision hay que conocer antes de usar nada: SQLite deja
`PRAGMA foreign_keys` **apagada** por defecto y la pragma es por conexion. Una BD
escrita sin ella puede contener filas huerfanas que parecen correctas hasta que
alguien pregunta. Por eso `connect()` la activa siempre.
"""

import sqlite3

from pathlib import Path

#: Numero de linea del proyecto en la que nacio el esquema actual. Cambia solo si
#: cambian las tablas; el `SCHEMA_VERSION` de storage.py cuenta otra historia
#: (la del documento JSON) y puede moverse por separado.
DB_SCHEMA_VERSION = 1

#: SQLite 3.37 introduced STRICT. Sin ella no hay garantias de tipo.
MIN_SQLITE_VERSION = (3, 37, 0)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_PATH = Path("data/goya.db")


class DatabaseError(RuntimeError):
    """La base de datos existe pero no es utilizable."""


def read_schema(path: Path = SCHEMA_PATH) -> str:
    """El esquema, leido del fichero .sql de al lado.

    Vive en un fichero y no en una constante porque asi se puede inspeccionar y
    ejecutar con `sqlite3` sin pasar por Python, que es justo lo que uno quiere
    cuando esta leyendo el modelo por primera vez.
    """
    return Path(path).read_text(encoding="utf-8")


def connect(path: Path = DEFAULT_PATH, *, create: bool = False) -> sqlite3.Connection:
    """Abrir una conexion con los ajustes de los que este proyecto depende.

    `check_same_thread=False` permite compartirla entre hilos. Las escrituras
    siguen siendo cosa de uno solo; el contexto de este proyecto es de un solo
    proceso y un solo hilo.
    """
    path = Path(path)
    if not create and not path.exists():
        raise DatabaseError(f"{path} no existe. Ejecuta antes la importacion.")

    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    # Sin esta linea las claves foraneas no se comprueban. Es el fallo numero uno
    # con sqlite3 y no da ningun aviso.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_database(path: Path = DEFAULT_PATH, *, overwrite: bool = True) -> Path:
    """Escribir una base de datos vacia con todas las tablas, indices y vistas.

    Falla si el fichero ya existe salvo que se pase `overwrite`: borrar una base
    en la que alguien ha trabajado deberia ser una decision, no un efecto.
    """
    path = Path(path)
    if path.exists() and not overwrite:
        raise DatabaseError(
            f"{path} ya existe; pasa overwrite=True para reemplazarla."
        )
    _require_strict_support()

    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and path.exists():
        # El esquema usa CREATE TABLE, que falla si la tabla ya existe. Borrar el
        # fichero es lo unico que hace que "reemplazar" signifique reemplazar.
        # SQLite lo mantiene en su WAL si habia una transaccion abierta.
        path.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()

    connection = sqlite3.connect(path)
    try:
        connection.executescript(read_schema())
        connection.commit()
    finally:
        connection.close()
    return path


def _require_strict_support() -> None:
    version = sqlite3_version()
    if version < MIN_SQLITE_VERSION:
        wanted = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        raise DatabaseError(
            f"Las tablas STRICT necesitan SQLite {wanted} o posterior; esta es "
            f"{sqlite3.sqlite_version}. STRICT es lo que impide que una duracion "
            "de '105 anos' se guarde como texto."
        )


def sqlite3_version() -> tuple[int, ...]:
    """Version de la libreria SQLite, como tupla para poder compararla."""
    parts = []
    for chunk in sqlite3.sqlite_version.split("."):
        digits = ""
        for character in chunk:
            if not character.isdigit():
                break
            digits += character
        parts.append(int(digits) if digits else 0)
    return tuple(parts)