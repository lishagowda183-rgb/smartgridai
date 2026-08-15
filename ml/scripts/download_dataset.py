"""Download the electricity-consumption dataset from Kaggle into ml/data/raw/.

The dataset is configurable via environment variables (see config.py and
.env.example). The script is idempotent: if the raw folder for the configured
dataset already exists, the download is skipped and the existing path is used.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import kagglehub

from config import KAGGLE_DATASET, RAW_DIR, ensure_dirs

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("download_dataset")

# Marker file written once a dataset has been successfully downloaded. This
# makes re-running the script cheap and safe even when the source folder name
# or Kaggle layout changes between versions.
MARKER = RAW_DIR / ".download_complete"


def dataset_folder() -> Path | None:
    """Return the raw sub-folder holding a previously downloaded dataset."""
    if not MARKER.exists():
        return None
    entries = [p for p in RAW_DIR.iterdir() if p.is_dir()]
    if not entries:
        return None
    return entries[0]


def main() -> int:
    ensure_dirs()

    existing = dataset_folder()
    if existing is not None:
        log.info("Dataset already downloaded in %s; skipping.", existing)
        return 0

    log.info("Downloading dataset %r via kagglehub...", KAGGLE_DATASET)
    try:
        path = kagglehub.dataset_download(KAGGLE_DATASET)
    except Exception as exc:  # kagglehub raises several error types
        log.error("Kaggle download failed: %s", exc)
        log.error(
            "If this is an authentication error, set KAGGLE_USERNAME / KAGGLE_KEY "
            "in .env (see .env.example) or create ~/.kaggle/kaggle.json."
        )
        return 1

    log.info("kagglehub resolved dataset to: %s", path)

    # Copy the resolved folder (or its contents) into the project raw dir so the
    # pipeline does not depend on kagglehub's cache location.
    import shutil

    source = Path(path)
    target = RAW_DIR / source.name
    if target.exists():
        log.info("Dataset already present at %s; skipping copy.", target)
    else:
        log.info("Copying dataset into %s ...", target)
        shutil.copytree(source, target)

    MARKER.write_text(f"dataset={KAGGLE_DATASET}\n", encoding="utf-8")
    log.info("Done. Dataset available at %s", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
