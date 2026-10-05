"""Punto de entrada: `python -m goya_scraper`."""

import logging

from .run import main

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()