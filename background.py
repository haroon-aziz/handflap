"""Procedural parallax scenery: sky, sun, hills, clouds and scrolling ground.

Every layer is rendered once into a surface at startup and merely blitted
afterwards, so the backdrop costs a handful of blits per frame.
"""

from __future__ import annotations

import math
import random

import pygame

import settings as cfg

W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT


def _lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _build_sky() -> pygame.Surface:
    surf = pygame.Surface((1, H))
    for y in range(H):
        surf.set_at((0, y), _lerp_color(cfg.SKY_TOP, cfg.SKY_BOTTOM, y / max(H - 1, 1)))
    return pygame.transform.scale(surf, (W, H))  # 1px column stretched: instant gradient


def _build_hills(color, amplitude, base_y, harmonics) -> pygame.Surface:
    """Periodic silhouette so the layer tiles seamlessly when scrolled."""
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    points = [(0, H)]
    for x in range(0, W + 1, 4):
        t = x / W
        y = base_y
        for k, amp, phase in harmonics:
            y -= math.sin(t * math.tau * k + phase) * amplitude * amp
        points.append((x, y))
    points.append((W, H))
    pygame.draw.polygon(surf, color, points)
    return surf


def _build_cloud(width: int) -> pygame.Surface:
    height = int(width * 0.62)
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    blobs = [
        (width * 0.30, height * 0.62, width * 0.30),
        (width * 0.52, height * 0.48, width * 0.36),
        (width * 0.72, height * 0.62, width * 0.26),
        (width * 0.44, height * 0.70, width * 0.30),
    ]
    for cx, cy, r in blobs:
        pygame.draw.circle(surf, (*cfg.CLOUD, 230), (int(cx), int(cy)), int(r))
    return surf


def _build_ground_tile() -> pygame.Surface:
    tile_w = 72
    surf = pygame.Surface((tile_w, cfg.GROUND_HEIGHT))
    surf.fill(cfg.GROUND_BODY)
    pygame.draw.rect(surf, cfg.GRASS_TOP, (0, 0, tile_w, 16))
    pygame.draw.rect(surf, cfg.GRASS_DARK, (0, 14, tile_w, 6))
    pygame.draw.rect(surf, cfg.GROUND_TOP, (0, 20, tile_w, 10))
    rng = random.Random(7)  # fixed seed: the tile must be identical every run
    for _ in range(14):
        x = rng.randrange(2, tile_w - 6)
        y = rng.randrange(34, cfg.GROUND_HEIGHT - 6)
        r = rng.randrange(2, 5)
        pygame.draw.circle(surf, cfg.GROUND_TOP, (x, y), r)
    for x in range(0, tile_w, 9):
        pygame.draw.line(surf, cfg.GRASS_DARK, (x, 0), (x + 3, 5), 2)
    return surf


class Background:
    def __init__(self) -> None:
        self.sky = _build_sky()
        self.hills_far = _build_hills(
            cfg.HILL_FAR, 46, cfg.PLAY_BOTTOM - 30,
            [(2, 1.0, 0.0), (5, 0.35, 1.2)])
        self.hills_near = _build_hills(
            cfg.HILL_NEAR, 62, cfg.PLAY_BOTTOM - 4,
            [(3, 1.0, 2.1), (7, 0.28, 0.4)])
        self.ground_tile = _build_ground_tile()
        self.clouds = [_build_cloud(w) for w in (150, 200, 118)]

        rng = random.Random(11)
        self._cloud_items = [
            {"img": self.clouds[i % len(self.clouds)],
             "x": rng.uniform(0, W), "y": rng.uniform(30, cfg.PLAY_BOTTOM * 0.5),
             "speed": rng.uniform(8, 26)}
            for i in range(6)
        ]

        self._off_far = 0.0
        self._off_near = 0.0
        self._off_ground = 0.0
        self._sun_pulse = 0.0

    def update(self, dt: float, speed: float) -> None:
        self._off_far = (self._off_far + speed * 0.12 * dt) % W
        self._off_near = (self._off_near + speed * 0.30 * dt) % W
        self._off_ground = (self._off_ground + speed * dt) % self.ground_tile.get_width()
        self._sun_pulse += dt
        for c in self._cloud_items:
            c["x"] -= (c["speed"] + speed * 0.05) * dt
            if c["x"] + c["img"].get_width() < 0:
                c["x"] = W + random.uniform(0, 160)
                c["y"] = random.uniform(30, cfg.PLAY_BOTTOM * 0.5)

    def draw(self, surface: pygame.Surface) -> None:
        surface.blit(self.sky, (0, 0))

        glow = 1.0 + 0.05 * math.sin(self._sun_pulse * 1.4)
        # Kept on the left: the webcam panel occupies the top-right corner.
        sun_pos = (int(W * 0.13), 104)
        for radius, alpha in ((int(96 * glow), 40), (int(70 * glow), 70), (52, 255)):
            layer = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(layer, (*cfg.SUN, alpha), (radius, radius), radius)
            surface.blit(layer, (sun_pos[0] - radius, sun_pos[1] - radius))

        for c in self._cloud_items:
            surface.blit(c["img"], (int(c["x"]), int(c["y"])))

        for layer, off in ((self.hills_far, self._off_far), (self.hills_near, self._off_near)):
            x = -int(off)
            surface.blit(layer, (x, 0))
            surface.blit(layer, (x + W, 0))

    def draw_ground(self, surface: pygame.Surface) -> None:
        tile_w = self.ground_tile.get_width()
        x = -int(self._off_ground)
        while x < W:
            surface.blit(self.ground_tile, (x, cfg.PLAY_BOTTOM))
            x += tile_w
        pygame.draw.line(surface, cfg.GRASS_DARK,
                         (0, cfg.PLAY_BOTTOM), (W, cfg.PLAY_BOTTOM), 3)
