"""Verify a HandFlap installation without needing a display or a waving hand.

    python selftest.py              full check, including the camera
    python selftest.py --no-camera  skip the camera probe

Checks dependencies, the model file, gesture geometry, the smoothing filter,
a complete headless game round, and the render frame budget. Useful both after
installing and when something feels wrong.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # no window needed
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("GLOG_minloglevel", "2")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

PASS, FAIL = "  [ok]  ", "  [FAIL]"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{PASS if ok else FAIL} {label}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(label)
    return ok


def section(name: str) -> None:
    print(f"\n{name}")


# --------------------------------------------------------------------------
def check_dependencies() -> bool:
    section("dependencies")
    ok = True
    try:
        import numpy
        check("numpy", True, numpy.__version__)
    except ImportError as exc:
        ok = check("numpy", False, str(exc))
    try:
        import pygame
        check("pygame", True, pygame.version.ver)
    except ImportError as exc:
        ok = check("pygame", False, str(exc))
    try:
        import cv2
        check("opencv (cv2)", True, cv2.__version__)
    except ImportError as exc:
        ok = check("opencv (cv2)", False, f"{exc} - pip install opencv-contrib-python")
    try:
        import mediapipe as mp
        backend = "tasks API" if hasattr(mp, "tasks") else "legacy solutions"
        check("mediapipe", True, f"{mp.__version__} ({backend})")
    except ImportError as exc:
        ok = check("mediapipe", False, str(exc))
    return ok


def check_model() -> None:
    section("hand landmark model")
    import settings as cfg
    exists = cfg.MODEL_PATH.exists() and cfg.MODEL_PATH.stat().st_size > 1_000_000
    check("model file present", exists,
          f"{cfg.MODEL_PATH.stat().st_size / 1_048_576:.1f} MB" if exists
          else "run: python download_model.py")

    from hand_tracker import create_detector
    detector, error = create_detector()
    check("detector builds", detector is not None, error or f"backend={detector.name}")
    if detector:
        detector.close()


def check_gestures() -> None:
    section("gesture geometry")
    import numpy as np
    from gestures import GestureRecognizer, analyse

    def hand(pose):
        lm = np.zeros((21, 3), dtype=np.float32)
        lm[0] = (0.5, 0.9, 0)
        lm[9] = (0.5, 0.7, 0)
        lm[5], lm[13], lm[17] = (0.44, 0.71, 0), (0.56, 0.71, 0), (0.60, 0.73, 0)

        def finger(mcp, pip, tip, out, bx):
            lm[mcp] = (bx, 0.71, 0)
            lm[pip] = (bx, 0.62 if out else 0.64, 0)
            lm[tip] = (bx, 0.46 if out else 0.74, 0)

        groups = [(5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20)]
        xs = [0.44, 0.50, 0.56, 0.60]
        if pose == "palm":
            for g, bx in zip(groups, xs):
                finger(*g, True, bx)
            lm[2], lm[3], lm[4] = (0.40, 0.80, 0), (0.34, 0.76, 0), (0.26, 0.72, 0)
        elif pose == "fist":
            for g, bx in zip(groups, xs):
                finger(*g, False, bx)
            lm[2], lm[3], lm[4] = (0.44, 0.80, 0), (0.46, 0.76, 0), (0.48, 0.74, 0)
        elif pose == "pinch":
            finger(5, 6, 8, True, 0.44)
            lm[8] = (0.42, 0.52, 0)
            for g, bx in zip(groups[1:], xs[1:]):
                finger(*g, False, bx)
            lm[2], lm[3], lm[4] = (0.40, 0.80, 0), (0.40, 0.66, 0), (0.425, 0.535, 0)
        else:  # point
            finger(5, 6, 8, True, 0.44)
            for g, bx in zip(groups[1:], xs[1:]):
                finger(*g, False, bx)
            lm[2], lm[3], lm[4] = (0.44, 0.80, 0), (0.46, 0.76, 0), (0.48, 0.74, 0)
        return lm

    for pose in ("palm", "fist", "pinch", "point"):
        got = analyse(hand(pose)).name
        check(f"{pose} classified", got == pose, f"got '{got}'")

    rec = GestureRecognizer()
    fired, t = 0, 0.0
    for i in range(30):
        t += 1 / 30
        rec.update(hand("pinch" if i % 10 < 5 else "point"), t)
        fired += rec.triggered("pinch", t)
        rec.clear_edges()
    check("pinch edge-triggers once per gesture", 1 <= fired <= 3, f"{fired} events / 2 pinches")


def check_smoothing() -> None:
    section("fingertip smoothing")
    import random
    import numpy as np
    import settings as cfg
    from hand_tracker import OneEuroFilter

    f = OneEuroFilter(cfg.EURO_MIN_CUTOFF, cfg.EURO_BETA, cfg.EURO_DERIV_CUTOFF)
    random.seed(1)
    noisy = [0.5 + random.uniform(-0.03, 0.03) for _ in range(120)]
    out = [f(v, i / 30) for i, v in enumerate(noisy)]
    j_in = float(np.std(np.diff(noisy)))
    j_out = float(np.std(np.diff(out[10:])))
    check("One Euro filter reduces jitter", j_out < j_in / 2,
          f"{j_in:.4f} -> {j_out:.4f} ({j_in / max(j_out, 1e-9):.1f}x)")


def check_game() -> int:
    section("game loop (headless)")
    import numpy as np
    import pygame
    import settings as cfg
    from game import COUNTDOWN, GAME_OVER, PAUSED, PLAYING, Game
    from hand_tracker import HandState, HandTracker

    frame = np.zeros((cfg.PANEL_HEIGHT, cfg.PANEL_WIDTH, 3), np.uint8)

    class Fake(HandTracker):
        def __init__(self):
            super().__init__()
            self.available, self.error = True, ""
            self.script = HandState(True, True, 0.5, 0.5, 0.5, 0.5, "point",
                                    1.4, (False, True, False, False, False), 30.0, frame)

        def start(self): pass

        def stop(self): pass

        def get_state(self):
            state, self.script = self.script, HandState(
                **{**self.script.__dict__, "events": ()})
            return state

    pygame.init()
    screen = pygame.display.set_mode((cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT))
    tracker = Fake()
    game = Game(screen, tracker)
    saved_best, dt = game.best, 1 / 60

    for _ in range(40):
        game.update(dt); game.draw()
    check("hand detected -> game starts", game.state == COUNTDOWN, game.state)

    for _ in range(200):
        game.update(dt); game.draw()
    check("countdown -> playing", game.state == PLAYING, game.state)

    # fly the gaps
    frames = 0
    while game.state == PLAYING and frames < 2000:
        pipe = game.pipes.nearest_gap(game.bird.x)
        lo, hi = cfg.BIRD_RADIUS + 12, cfg.PLAY_BOTTOM - cfg.BIRD_RADIUS - 12
        ctrl = (pipe.gap_center - lo) / (hi - lo) if pipe else 0.5
        tracker.script = HandState(True, True, 0.5, 0.5, 0.5, min(max(ctrl, 0.0), 1.0),
                                   "point", 1.4, (False, True, False, False, False),
                                   30.0, frame)
        game.update(dt); game.draw()
        frames += 1
    check("bird flies through pipes and scores", game.score > 5, f"score {game.score}")
    check("difficulty increases with score",
          game.pipes.speed_for(20) > game.pipes.speed_for(0)
          and game.pipes.gap_for(20) < game.pipes.gap_for(0),
          f"speed {game.pipes.speed_for(0):.0f}->{game.pipes.speed_for(30):.0f} px/s, "
          f"gap {game.pipes.gap_for(0):.0f}->{game.pipes.gap_for(30):.0f} px")

    # hand disappears -> gravity -> crash
    for _ in range(600):
        tracker.script = HandState(False, False, 0.5, 0.5, 0.5, 0.5, "none",
                                   1.0, (False,) * 5, 30.0, frame)
        game.update(dt); game.draw()
        if game.state == GAME_OVER:
            break
    check("losing the hand drops the bird", game.state == GAME_OVER)
    check("high score saved", cfg.HIGHSCORE_FILE.exists() or game.score <= saved_best)

    # palm restarts, fist pauses
    for _ in range(70):
        tracker.script = HandState(True, True, 0.5, 0.5, 0.5, 0.5, "palm",
                                   1.0, (True,) * 5, 30.0, frame)
        game.update(dt); game.draw()
    tracker.script = HandState(True, True, 0.5, 0.5, 0.5, 0.5, "palm", 1.0,
                               (True,) * 5, 30.0, frame, events=("palm",))
    game.update(dt); game.draw()
    check("open palm restarts", game.state == COUNTDOWN, game.state)

    for _ in range(200):
        game.update(dt); game.draw()
    tracker.script = HandState(True, True, 0.5, 0.5, 0.5, 0.5, "fist", 0.3,
                               (False,) * 5, 30.0, frame, events=("fist",))
    game.update(dt); game.draw()
    check("fist pauses", game.state == PAUSED, game.state)

    # render budget
    for _ in range(60):
        game.update(dt); game.draw()
    t0 = time.perf_counter()
    n = 200
    for _ in range(n):
        game.update(dt); game.draw()
    per = (time.perf_counter() - t0) / n
    check("frame budget under 16.7 ms", per < 1 / 60,
          f"{per * 1000:.2f} ms/frame (~{1 / per:.0f} FPS headroom)")

    pygame.quit()
    return 0


def check_camera() -> None:
    section("camera")
    from hand_tracker import HandTracker
    tracker = HandTracker()
    if not tracker.available:
        check("camera", False, tracker.error)
        return
    tracker.start()
    time.sleep(4.0)
    state = tracker.get_state()
    ok = state.frame is not None and state.cv_fps > 0
    check("camera opens and delivers frames", ok,
          f"{state.cv_fps:.1f} FPS, backend={tracker.backend}" if ok
          else (state.error or "no frames - is another app using the camera?"))
    if ok and state.cv_fps < 10:
        print(f"         note: {state.cv_fps:.0f} FPS is low; more light usually helps")
    print("         (wave your hand at the camera during this check to test detection:"
          f" detected={state.detected})")
    tracker.stop()


def main() -> int:
    print("HandFlap self-test")
    if not check_dependencies():
        print("\nMissing dependencies - run: pip install -r requirements.txt")
        return 1

    check_model()
    check_gestures()
    check_smoothing()
    check_game()
    if "--no-camera" not in sys.argv:
        check_camera()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        print("See the Troubleshooting section of README.md")
        return 1
    print("All checks passed - run 'python main.py' to play.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
