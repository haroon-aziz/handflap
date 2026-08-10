"""Gesture recognition from MediaPipe hand landmarks.

Pure geometry: this module never touches OpenCV, MediaPipe or Pygame, which
makes it trivial to unit-test and keeps the CV layer thin.

Input is always a (21, 3) float array of landmarks in *aspect-corrected*
normalised coordinates (x already multiplied by frame_width/frame_height) so
that Euclidean distances are undistorted.

MediaPipe hand landmark indices
    0  wrist
    1-4    thumb   (cmc, mcp, ip, tip)
    5-8    index   (mcp, pip, dip, tip)
    9-12   middle  (mcp, pip, dip, tip)
    13-16  ring    (mcp, pip, dip, tip)
    17-20  pinky   (mcp, pip, dip, tip)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import settings as cfg

WRIST = 0
THUMB_MCP, THUMB_IP, THUMB_TIP = 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

FINGER_PIPS = (INDEX_PIP, MIDDLE_PIP, RING_PIP, PINKY_PIP)
FINGER_TIPS = (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)

# Gesture names
NONE = "none"
POINT = "point"
PINCH = "pinch"
FIST = "fist"
PALM = "palm"


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a[:2] - b[:2]))


@dataclass
class GestureReading:
    """Per-frame gesture analysis of a single hand."""

    name: str = NONE
    pinch_ratio: float = 1.0
    extended: tuple = field(default_factory=lambda: (False,) * 5)
    hand_scale: float = 0.0

    @property
    def extended_count(self) -> int:
        return sum(self.extended)


def hand_scale(lm: np.ndarray) -> float:
    """Palm length: the reference unit every other measure is divided by.

    Using a bone length instead of pixels makes thresholds independent of how
    far the player sits from the camera.
    """
    scale = _dist(lm[WRIST], lm[MIDDLE_MCP])
    return max(scale, 1e-6)


def finger_states(lm: np.ndarray, scale: float) -> tuple:
    """(thumb, index, middle, ring, pinky) extension flags.

    A finger counts as extended when its tip is meaningfully further from the
    wrist than its PIP joint. This ratio test is rotation invariant, unlike the
    common "tip.y < pip.y" shortcut which breaks the moment the hand tilts.
    """
    states = []

    # Thumb bends sideways, so the wrist-distance test does not work for it.
    # Its abduction from the pinky knuckle separates spread from tucked.
    states.append(_dist(lm[THUMB_TIP], lm[PINKY_MCP]) / scale > 1.0)

    for pip, tip in zip(FINGER_PIPS, FINGER_TIPS):
        d_tip = _dist(lm[WRIST], lm[tip])
        d_pip = _dist(lm[WRIST], lm[pip])
        states.append(d_tip > d_pip * cfg.FINGER_EXTEND_RATIO)

    return tuple(states)


def analyse(lm: np.ndarray, pinch_was_closed: bool = False) -> GestureReading:
    """Classify one frame of landmarks into a gesture.

    `pinch_was_closed` feeds Schmitt-trigger hysteresis: once closed, the pinch
    has to open noticeably wider before it is considered released, which stops
    the classification flickering at the threshold.
    """
    scale = hand_scale(lm)
    pinch_ratio = _dist(lm[THUMB_TIP], lm[INDEX_TIP]) / scale
    extended = finger_states(lm, scale)

    threshold = cfg.PINCH_OFF if pinch_was_closed else cfg.PINCH_ON
    # In a fist the thumb tip also sits near the index tip. Requiring the index
    # to reach away from the wrist separates a real pinch from a closed fist.
    index_reach = _dist(lm[WRIST], lm[INDEX_TIP]) / scale
    is_pinch = pinch_ratio < threshold and index_reach > 1.25

    count = sum(extended)
    if is_pinch:
        name = PINCH
    elif count >= cfg.PALM_EXTENDED_MIN:
        name = PALM
    elif count <= cfg.FIST_EXTENDED_MAX and index_reach < 1.3:
        name = FIST
    elif extended[1]:
        name = POINT
    else:
        name = NONE

    return GestureReading(name, pinch_ratio, extended, scale)


class GestureRecognizer:
    """Turns noisy per-frame readings into stable states and clean events.

    Two layers of debouncing:
      * a gesture must repeat for GESTURE_STABLE_FRAMES before it is committed;
      * discrete triggers (flap, pause, restart) are edge-detected and rate
        limited, so holding a gesture fires once, not sixty times a second.
    """

    def __init__(self) -> None:
        self.stable: str = NONE
        self._candidate: str = NONE
        self._streak: int = 0
        self._pinch_closed: bool = False
        self._last_trigger: dict = {}
        self.reading = GestureReading()

    def reset(self) -> None:
        self.stable = NONE
        self._candidate = NONE
        self._streak = 0
        self._pinch_closed = False
        self._last_trigger.clear()
        self.reading = GestureReading()

    def update(self, lm: np.ndarray | None, now: float) -> str:
        """Feed landmarks (or None when no hand is visible). Returns the
        stable gesture and records rising edges for `triggered()`."""
        if lm is None:
            self.reading = GestureReading()
            self._pinch_closed = False
            self._push(NONE, now)
            return self.stable

        reading = analyse(lm, self._pinch_closed)
        self.reading = reading
        self._pinch_closed = reading.name == PINCH
        self._push(reading.name, now)
        return self.stable

    def _push(self, name: str, now: float) -> None:
        if name == self._candidate:
            self._streak += 1
        else:
            self._candidate = name
            self._streak = 1

        if self._streak >= cfg.GESTURE_STABLE_FRAMES and name != self.stable:
            previous = self.stable
            self.stable = name
            if name != NONE and previous != name:
                self._edges = getattr(self, "_edges", set())
                self._edges.add(name)
                self._edge_time = now

    def triggered(self, name: str, now: float, cooldown: float | None = None) -> bool:
        """True exactly once per rising edge of `name`, rate limited."""
        edges = getattr(self, "_edges", set())
        if name not in edges:
            return False
        cd = cfg.GESTURE_COOLDOWN if cooldown is None else cooldown
        if now - self._last_trigger.get(name, -1e9) < cd:
            edges.discard(name)
            return False
        edges.discard(name)
        self._last_trigger[name] = now
        return True

    def clear_edges(self) -> None:
        getattr(self, "_edges", set()).clear()
