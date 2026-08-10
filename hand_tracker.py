"""Webcam capture + MediaPipe hand tracking, running on its own thread.

The whole computer-vision pipeline lives here and never touches game state.
It runs in a background thread and publishes an immutable snapshot
(`HandState`) that the game loop reads whenever it likes; the game therefore
never blocks on camera I/O or inference, which is what keeps rendering at a
steady 60 FPS while the camera delivers ~30.

Two MediaPipe front-ends are supported behind one interface:
  * the current **Tasks API** (`HandLandmarker`), used by MediaPipe >= 0.10.30;
  * the **legacy `mp.solutions.hands`** graph, for older installations.
Landmark indices and normalised coordinates are identical either way, so
everything downstream is backend agnostic.
"""

from __future__ import annotations

import math
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np

import settings as cfg
from gestures import GestureRecognizer, INDEX_TIP, NONE

try:  # both are optional so the game can still start (keyboard mode) without them
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import mediapipe as mp
except ImportError:  # pragma: no cover
    mp = None

# The standard 21-bone hand skeleton, hardcoded so the preview overlay does not
# depend on which MediaPipe front-end is active.
HAND_CONNECTIONS = (
    (0, 1), (0, 5), (5, 9), (9, 13), (13, 17), (0, 17),
    (1, 2), (2, 3), (3, 4),
    (5, 6), (6, 7), (7, 8),
    (9, 10), (10, 11), (11, 12),
    (13, 14), (14, 15), (15, 16),
    (17, 18), (18, 19), (19, 20),
)


# --------------------------------------------------------------------------
# Model file
# --------------------------------------------------------------------------
def ensure_model(verbose: bool = True) -> bool:
    """Make sure the HandLandmarker model bundle is on disk.

    The Tasks API ships without weights, so the ~7.5 MB bundle is fetched once
    at setup time. Nothing contacts the network afterwards - the game itself is
    fully offline.
    """
    if cfg.MODEL_PATH.exists() and cfg.MODEL_PATH.stat().st_size > 1_000_000:
        return True
    cfg.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if verbose:
        print(f"[handflap] downloading hand landmark model -> {cfg.MODEL_PATH}")
    tmp = cfg.MODEL_PATH.with_suffix(".part")
    try:
        urllib.request.urlretrieve(cfg.MODEL_URL, tmp)
        tmp.replace(cfg.MODEL_PATH)
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "no model"
        if verbose:
            print(f"[handflap] model download failed: {exc}")
        tmp.unlink(missing_ok=True)
        return False


# --------------------------------------------------------------------------
# Smoothing
# --------------------------------------------------------------------------
class OneEuroFilter:
    """Adaptive low-pass filter (Casiez et al., 2012).

    A fixed low-pass filter forces a choice between jitter and lag. The One
    Euro filter widens its cutoff as the signal speeds up: still hands get
    heavy smoothing, fast flicks pass through nearly untouched.
    """

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev: float | None = None
        self._dx_prev: float = 0.0
        self._t_prev: float = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = 0.0

    def __call__(self, x: float, t: float) -> float:
        if self._x_prev is None:
            self._x_prev, self._t_prev = x, t
            return x

        dt = t - self._t_prev
        if dt <= 0.0 or dt > 0.5:  # first frame after a stall: restart cleanly
            dt = 1.0 / max(cfg.CAPTURE_FPS, 1)
        self._t_prev = t

        dx = (x - self._x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev
        self._dx_prev = dx_hat

        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1.0 - a) * self._x_prev
        self._x_prev = x_hat
        return x_hat


# --------------------------------------------------------------------------
# MediaPipe back-ends
# --------------------------------------------------------------------------
class _TasksDetector:
    """MediaPipe Tasks `HandLandmarker` in VIDEO mode."""

    name = "tasks"

    def __init__(self) -> None:
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(cfg.MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=cfg.MAX_NUM_HANDS,
            min_hand_detection_confidence=cfg.MIN_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=cfg.MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=cfg.MIN_TRACKING_CONFIDENCE,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = -1

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> list:
        # VIDEO mode demands strictly increasing timestamps.
        if timestamp_ms <= self._last_ts:
            timestamp_ms = self._last_ts + 1
        self._last_ts = timestamp_ms

        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)

        hands = []
        for i, landmarks in enumerate(result.hand_landmarks):
            arr = np.empty((21, 3), dtype=np.float32)
            for j, p in enumerate(landmarks):
                arr[j] = (p.x, p.y, p.z)
            score = 0.5
            if result.handedness and i < len(result.handedness):
                score = float(result.handedness[i][0].score)
            hands.append((arr, score))
        return hands

    def close(self) -> None:
        self._landmarker.close()


class _LegacyDetector:
    """Old `mp.solutions.hands` graph (MediaPipe <= 0.10.21)."""

    name = "solutions"

    def __init__(self) -> None:
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=cfg.MAX_NUM_HANDS,
            model_complexity=cfg.MODEL_COMPLEXITY,
            min_detection_confidence=cfg.MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=cfg.MIN_TRACKING_CONFIDENCE,
        )

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> list:
        rgb.flags.writeable = False  # lets MediaPipe skip an internal copy
        result = self._hands.process(rgb)
        rgb.flags.writeable = True
        if not result.multi_hand_landmarks:
            return []

        hands = []
        for i, landmarks in enumerate(result.multi_hand_landmarks):
            arr = np.empty((21, 3), dtype=np.float32)
            for j, p in enumerate(landmarks.landmark):
                arr[j] = (p.x, p.y, p.z)
            score = 0.5
            if result.multi_handedness and i < len(result.multi_handedness):
                score = float(result.multi_handedness[i].classification[0].score)
            hands.append((arr, score))
        return hands

    def close(self) -> None:
        self._hands.close()


def create_detector() -> tuple:
    """(detector, error_message). Prefers the modern Tasks API."""
    if mp is None:
        return None, "MediaPipe is not installed"

    if hasattr(mp, "tasks"):
        if not ensure_model():
            return None, "hand_landmarker.task missing - run: python download_model.py"
        try:
            return _TasksDetector(), ""
        except Exception as exc:  # noqa: BLE001
            legacy_error = f"HandLandmarker failed: {exc}"
    else:
        legacy_error = ""

    if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
        try:
            return _LegacyDetector(), ""
        except Exception as exc:  # noqa: BLE001
            return None, f"MediaPipe Hands failed: {exc}"
    return None, legacy_error or "No usable MediaPipe hand backend found"


# --------------------------------------------------------------------------
# Snapshot published to the game
# --------------------------------------------------------------------------
@dataclass
class HandState:
    detected: bool = False          # a hand is visible right now
    usable: bool = False            # visible, or lost less than the grace period ago
    x: float = 0.5                  # smoothed fingertip, normalised 0..1
    y: float = 0.5
    raw_y: float = 0.5              # unsmoothed, for the debug overlay
    control: float = 0.5            # y remapped through the active control band
    gesture: str = NONE
    pinch_ratio: float = 1.0
    extended: tuple = field(default_factory=lambda: (False,) * 5)
    cv_fps: float = 0.0
    frame: np.ndarray | None = None  # RGB preview, already panel sized
    events: tuple = ()               # discrete gesture edges since the last read
    error: str = ""


class HandTracker:
    """Owns the camera, the MediaPipe graph and the smoothing filters."""

    def __init__(self, camera_index: int = cfg.CAMERA_INDEX):
        self.camera_index = camera_index
        self.available = cv2 is not None and mp is not None
        self.error = "" if self.available else (
            "OpenCV/MediaPipe not installed - keyboard mode only"
        )
        self.backend = ""

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._events: deque = deque(maxlen=16)

        self._recognizer = GestureRecognizer()
        self._fx = OneEuroFilter(cfg.EURO_MIN_CUTOFF, cfg.EURO_BETA, cfg.EURO_DERIV_CUTOFF)
        self._fy = OneEuroFilter(cfg.EURO_MIN_CUTOFF, cfg.EURO_BETA, cfg.EURO_DERIV_CUTOFF)

        # shared state, guarded by _lock
        self._state = HandState(error=self.error)
        self._last_seen = 0.0
        self._cv_fps = 0.0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hand-tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- consumer API ------------------------------------------------------
    def get_state(self) -> HandState:
        """Latest snapshot. Draining events here guarantees each gesture edge
        is consumed exactly once by the game loop."""
        with self._lock:
            state = self._state
            events = tuple(self._events)
            self._events.clear()
        return replace(state, events=events)

    # -- worker thread -----------------------------------------------------
    def _open_camera(self):
        backends = []
        if hasattr(cv2, "CAP_V4L2"):
            backends.append(cv2.CAP_V4L2)
        backends.append(cv2.CAP_ANY)

        for backend in backends:
            cap = cv2.VideoCapture(self.camera_index, backend)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.CAPTURE_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.CAPTURE_HEIGHT)
                cap.set(cv2.CAP_PROP_FPS, cfg.CAPTURE_FPS)
                # A 1-frame buffer keeps us on the newest frame instead of
                # replaying a queue of stale ones (visible as control lag).
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:  # noqa: BLE001 - unsupported on some backends
                    pass
                return cap
            cap.release()
        return None

    def _run(self) -> None:
        detector, error = create_detector()
        if detector is None:
            self._publish_error(f"{error} - keyboard mode only")
            return
        self.backend = detector.name

        cap = self._open_camera()
        if cap is None:
            detector.close()
            self._publish_error(
                f"camera {self.camera_index} could not be opened - keyboard mode only"
            )
            return

        prev_t = time.perf_counter()
        start_t = prev_t
        failures = 0

        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    failures += 1
                    if failures > 60:
                        self._publish_error("lost the camera stream - keyboard mode only")
                        break
                    time.sleep(0.02)
                    continue
                failures = 0

                now = time.perf_counter()
                dt = now - prev_t
                prev_t = now
                if dt > 0:
                    inst = 1.0 / dt
                    self._cv_fps = inst if self._cv_fps == 0 else self._cv_fps * 0.9 + inst * 0.1

                if cfg.MIRROR_CAMERA:
                    cv2.flip(frame, 1, dst=frame)  # in place, no extra allocation

                # Inference runs on a small copy; the preview keeps its own size.
                scale = cfg.DETECT_WIDTH / frame.shape[1]
                small = cv2.resize(
                    frame, (cfg.DETECT_WIDTH, max(1, int(frame.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA,
                )
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                hands = detector.detect(rgb, int((now - start_t) * 1000))

                preview = cv2.resize(
                    frame, (cfg.PANEL_WIDTH, cfg.PANEL_HEIGHT), interpolation=cv2.INTER_AREA
                )
                # Aspect must come from the frame the landmarks were measured
                # in, not from the fixed-size preview panel.
                self._process(hands, preview, now, frame.shape[1] / frame.shape[0])
        except Exception as exc:  # noqa: BLE001 - a CV crash must not kill the game
            self._publish_error(f"hand tracking stopped: {exc}")
        finally:
            detector.close()
            cap.release()

    # -- per-frame handling -------------------------------------------------
    @staticmethod
    def _select_hand(hands: list, previous: HandState):
        """Pick exactly one hand when several are in frame.

        Continuity comes first: whichever hand is nearest to the fingertip we
        were already tracking keeps control, so a second hand wandering into
        view cannot steal the bird mid-flight. MediaPipe's handedness score is
        deliberately ignored here - it rates left-vs-right classification, not
        tracking quality, and sits near 1.0 for every hand.

        With nothing to continue from, the largest hand wins: the player
        reaching towards the camera is the one asking to play.
        """
        if len(hands) == 1:
            return hands[0][0]

        if previous.detected:
            best, best_d = None, 1e9
            for arr, _ in hands:
                d = math.hypot(float(arr[INDEX_TIP][0]) - previous.x,
                               float(arr[INDEX_TIP][1]) - previous.y)
                if d < best_d:
                    best, best_d = arr, d
            if best_d < cfg.CONTINUITY_RADIUS:
                return best

        def size(item):
            arr = item[0]
            return math.hypot(float(arr[9][0] - arr[0][0]), float(arr[9][1] - arr[0][1]))

        return max(hands, key=size)[0]

    def _process(self, hands: list, preview: np.ndarray, now: float,
                 aspect: float) -> None:
        with self._lock:
            previous = self._state

        arr = self._select_hand(hands, previous) if hands else None

        if arr is None:
            self._recognizer.update(None, now)
            usable = (now - self._last_seen) < cfg.HAND_LOST_GRACE
            if not usable:
                self._fx.reset()
                self._fy.reset()
            self._draw_band(preview)
            self._publish(HandState(
                detected=False, usable=usable,
                x=previous.x, y=previous.y, raw_y=previous.raw_y,
                control=previous.control,
                gesture=NONE, cv_fps=self._cv_fps,
                frame=self._to_rgb(preview), error=self.error,
            ))
            return

        h, w = preview.shape[:2]
        # Distances are only meaningful once x is rescaled by the aspect ratio;
        # normalised coordinates squash a 4:3 frame into a unit square.
        metric = arr.copy()
        metric[:, 0] *= aspect

        raw_x, raw_y = float(arr[INDEX_TIP][0]), float(arr[INDEX_TIP][1])
        sx = min(max(self._fx(raw_x, now), 0.0), 1.0)
        sy = min(max(self._fy(raw_y, now), 0.0), 1.0)

        gesture = self._recognizer.update(metric, now)
        reading = self._recognizer.reading
        for name in ("pinch", "fist", "palm"):
            if self._recognizer.triggered(name, now):
                with self._lock:
                    self._events.append(name)
        self._recognizer.clear_edges()

        span = max(cfg.CONTROL_BOTTOM - cfg.CONTROL_TOP, 1e-6)
        control = min(max((sy - cfg.CONTROL_TOP) / span, 0.0), 1.0)

        self._draw_landmarks(preview, arr)
        self._draw_band(preview)
        tip = (int(sx * w), int(sy * h))
        cv2.circle(preview, tip, 10, (0, 235, 255), 2)
        cv2.circle(preview, tip, 3, (0, 235, 255), -1)

        self._last_seen = now
        self._publish(HandState(
            detected=True, usable=True,
            x=sx, y=sy, raw_y=raw_y, control=control,
            gesture=gesture,
            pinch_ratio=reading.pinch_ratio,
            extended=reading.extended,
            cv_fps=self._cv_fps,
            frame=self._to_rgb(preview),
            error=self.error,
        ))

    # -- preview overlay ----------------------------------------------------
    @staticmethod
    def _draw_landmarks(preview: np.ndarray, arr: np.ndarray) -> None:
        h, w = preview.shape[:2]
        pts = [(int(p[0] * w), int(p[1] * h)) for p in arr]
        for a, b in HAND_CONNECTIONS:
            cv2.line(preview, pts[a], pts[b], (240, 240, 240), 2, cv2.LINE_AA)
        for i, p in enumerate(pts):
            # tips highlighted, knuckles dim
            color = (90, 220, 120) if i in (4, 8, 12, 16, 20) else (60, 120, 240)
            cv2.circle(preview, p, 3, color, -1, cv2.LINE_AA)

    @staticmethod
    def _draw_band(preview: np.ndarray) -> None:
        """Show the slice of the frame that maps onto the playfield."""
        h, w = preview.shape[:2]
        for edge in (cfg.CONTROL_TOP, cfg.CONTROL_BOTTOM):
            y = int(edge * h)
            cv2.line(preview, (0, y), (w, y), (90, 220, 120), 1)

    @staticmethod
    def _to_rgb(bgr: np.ndarray) -> np.ndarray:
        # Contiguous RGB so pygame.image.frombuffer can wrap it without a copy.
        return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    def _publish(self, state: HandState) -> None:
        with self._lock:
            self._state = state

    def _publish_error(self, message: str) -> None:
        self.error = message
        self.available = False
        with self._lock:
            self._state = HandState(error=message)
