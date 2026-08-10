"""HandFlap - entry point.

    python main.py                 play with the default camera
    python main.py --camera 1      pick another webcam
    python main.py --no-camera     keyboard-only mode (useful for testing)
"""

from __future__ import annotations

import argparse
import os
import sys

# Silence MediaPipe/TensorFlow-Lite startup chatter before those imports happen.
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

import settings as cfg  # noqa: E402
from game import Game  # noqa: E402
from hand_tracker import HandTracker  # noqa: E402


def build_icon() -> pygame.Surface:
    icon = pygame.Surface((32, 32), pygame.SRCALPHA)
    pygame.draw.circle(icon, cfg.BIRD_BODY, (15, 16), 12)
    pygame.draw.polygon(icon, cfg.BIRD_BEAK, [(25, 13), (32, 16), (25, 20)])
    pygame.draw.circle(icon, (255, 255, 255), (19, 12), 5)
    pygame.draw.circle(icon, cfg.BIRD_EYE, (20, 12), 2)
    return icon


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hand-controlled Flappy Bird")
    parser.add_argument("--camera", type=int, default=cfg.CAMERA_INDEX,
                        help="webcam device index (default: 0)")
    parser.add_argument("--no-camera", action="store_true",
                        help="skip hand tracking and play with the keyboard")
    parser.add_argument("--no-panel", action="store_true",
                        help="hide the webcam preview panel at startup")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pygame.init()
    pygame.display.set_caption(cfg.WINDOW_TITLE)
    screen = pygame.display.set_mode((cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT))
    pygame.display.set_icon(build_icon())

    tracker = HandTracker(camera_index=args.camera)
    if args.no_camera:
        tracker.available = False
        tracker.error = "camera disabled (--no-camera)"
    else:
        # The camera opens and MediaPipe loads on a background thread, so the
        # start screen is interactive immediately.
        tracker.start()

    if tracker.error:
        print(f"[handflap] {tracker.error}", file=sys.stderr)

    game = Game(screen, tracker)
    game.show_panel = not args.no_panel
    try:
        game.run()
    finally:
        tracker.stop()
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
