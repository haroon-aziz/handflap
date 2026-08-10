"""One-time setup: fetch the MediaPipe hand landmark model bundle.

Run once after installing the requirements:

    python download_model.py

`main.py` calls the same routine automatically if the file is missing, so this
script only exists for offline/air-gapped setups where you want to pre-fetch
the model (or copy it in by hand from another machine).
"""

from __future__ import annotations

import sys

import settings as cfg
from hand_tracker import ensure_model


def main() -> int:
    if ensure_model():
        size = cfg.MODEL_PATH.stat().st_size / 1_048_576
        print(f"[handflap] model ready: {cfg.MODEL_PATH} ({size:.1f} MB)")
        return 0
    print(f"[handflap] could not obtain the model.\n"
          f"           download it manually from:\n           {cfg.MODEL_URL}\n"
          f"           and save it as: {cfg.MODEL_PATH}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
