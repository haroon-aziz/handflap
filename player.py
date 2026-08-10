"""The bird: physics, hand-following control and procedural animation."""

from __future__ import annotations

import math

import pygame

import settings as cfg


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Bird:
    """Player character.

    Control model: gravity is always present, but while the hand is guiding the
    bird most of it is cancelled and a proportional controller drives velocity
    towards the fingertip. The bird therefore *flies to* the finger with weight
    and momentum instead of teleporting to it, and it falls naturally the
    instant tracking is lost.
    """

    WING_FRAMES = 3

    def __init__(self, x: float = cfg.BIRD_X, y: float = cfg.BIRD_START_Y):
        self.x = x
        self.y = y
        self.start_y = y
        self.vy = 0.0
        self.tilt = 0.0
        self.alive = True
        self._wing_phase = 0.0
        self._bob = 0.0
        self._frames = [self._render_frame(i) for i in range(self.WING_FRAMES)]

    # -- geometry ----------------------------------------------------------
    @property
    def radius(self) -> float:
        return cfg.BIRD_RADIUS * cfg.BIRD_COLLIDER_SCALE

    @property
    def rect(self) -> pygame.Rect:
        r = int(self.radius)
        return pygame.Rect(int(self.x - r), int(self.y - r), r * 2, r * 2)

    def reset(self, y: float | None = None) -> None:
        self.y = self.start_y if y is None else y
        self.vy = 0.0
        self.tilt = 0.0
        self.alive = True
        self._wing_phase = 0.0

    # -- physics -----------------------------------------------------------
    def flap(self) -> None:
        if self.alive:
            self.vy = cfg.FLAP_IMPULSE
            self._wing_phase = 0.0

    def update(self, dt: float, target_y: float | None) -> None:
        if not self.alive:
            self._update_dead(dt)
            return

        if target_y is None:
            self.vy += cfg.GRAVITY * dt
        else:
            error = target_y - self.y
            desired = _clamp(error * cfg.FOLLOW_GAIN, cfg.MAX_RISE_SPEED, cfg.MAX_FALL_SPEED)
            # Critically-damped-ish approach to the desired velocity.
            self.vy += (desired - self.vy) * min(1.0, cfg.FOLLOW_RESPONSE * dt)
            self.vy += cfg.GRAVITY * cfg.HAND_GRAVITY_SCALE * dt

        self.vy = _clamp(self.vy, cfg.MAX_RISE_SPEED, cfg.MAX_FALL_SPEED)
        self.y += self.vy * dt

        if self.y < self.radius:  # soft ceiling
            self.y = self.radius
            self.vy = max(self.vy, 0.0)

        self._animate(dt)

    def _update_dead(self, dt: float) -> None:
        self.vy = min(self.vy + cfg.GRAVITY * 1.15 * dt, cfg.MAX_FALL_SPEED)
        self.y += self.vy * dt
        self.tilt = max(self.tilt - 320.0 * dt, -95.0)

    def _animate(self, dt: float) -> None:
        # Wings beat faster while climbing, idle-flutter while gliding.
        rate = 9.0 + max(0.0, -self.vy) * 0.02
        self._wing_phase = (self._wing_phase + rate * dt) % 1.0
        target_tilt = _clamp(-self.vy / 620.0 * cfg.BIRD_MAX_TILT,
                             -cfg.BIRD_MAX_TILT, cfg.BIRD_MAX_TILT * 0.6)
        self.tilt += (target_tilt - self.tilt) * min(1.0, 9.0 * dt)

    def idle(self, dt: float, t: float) -> None:
        """Menu hover: no gravity, gentle sine bob."""
        self._bob = math.sin(t * 2.6) * 14.0
        self.y = self.start_y + self._bob
        self.vy = 0.0
        self.tilt = math.sin(t * 2.6 + math.pi / 2) * 8.0
        self._animate(dt)

    # -- rendering ---------------------------------------------------------
    def _render_frame(self, index: int) -> pygame.Surface:
        """Pre-render one wing pose. Rotation at draw time is then a single
        cheap transform instead of redrawing the whole bird every frame."""
        r = cfg.BIRD_RADIUS
        size = r * 4
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        cx, cy = size // 2, size // 2

        # tail
        pygame.draw.polygon(surf, cfg.BIRD_BODY_DARK, [
            (cx - r * 0.7, cy), (cx - r * 1.9, cy - r * 0.55), (cx - r * 1.75, cy + r * 0.5)])

        # body with a darker underside for depth
        pygame.draw.ellipse(surf, cfg.BIRD_BODY_DARK,
                            (cx - r * 1.15, cy - r * 0.86, r * 2.3, r * 1.85))
        pygame.draw.ellipse(surf, cfg.BIRD_BODY,
                            (cx - r * 1.15, cy - r * 0.95, r * 2.3, r * 1.7))
        pygame.draw.ellipse(surf, (255, 232, 150),
                            (cx - r * 0.85, cy - r * 0.8, r * 1.4, r * 0.7))

        # wing: three poses sweeping down
        offset = (-0.55, 0.0, 0.55)[index]
        wing = [
            (cx - r * 0.55, cy - r * 0.05),
            (cx + r * 0.35, cy - r * 0.15),
            (cx - r * 0.1, cy + r * (0.95 + offset)),
        ]
        pygame.draw.polygon(surf, cfg.BIRD_WING, wing)
        pygame.draw.polygon(surf, cfg.BIRD_BODY_DARK, wing, 2)

        # beak
        pygame.draw.polygon(surf, cfg.BIRD_BEAK, [
            (cx + r * 1.0, cy - r * 0.22), (cx + r * 1.75, cy),
            (cx + r * 1.0, cy + r * 0.24)])

        # eye
        eye = (int(cx + r * 0.55), int(cy - r * 0.34))
        pygame.draw.circle(surf, (255, 255, 255), eye, int(r * 0.36))
        pygame.draw.circle(surf, cfg.BIRD_EYE, (eye[0] + int(r * 0.1), eye[1]), int(r * 0.18))
        return surf

    def draw(self, surface: pygame.Surface, scale: float = 1.0) -> None:
        frame = self._frames[int(self._wing_phase * self.WING_FRAMES) % self.WING_FRAMES]
        rotated = pygame.transform.rotozoom(frame, self.tilt, scale)
        surface.blit(rotated, rotated.get_rect(center=(int(self.x), int(self.y))))
