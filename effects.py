"""Lightweight particle and floating-text effects."""

from __future__ import annotations

import math
import random

import pygame


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "color", "gravity", "fade")

    def __init__(self, x, y, vx, vy, life, size, color, gravity=0.0, fade=True):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = self.max_life = life
        self.size = size
        self.color = color
        self.gravity = gravity
        self.fade = fade

    def update(self, dt: float) -> bool:
        self.life -= dt
        if self.life <= 0:
            return False
        self.vy += self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        return True

    def draw(self, surface: pygame.Surface) -> None:
        t = max(self.life / self.max_life, 0.0)
        radius = max(1, int(self.size * (0.35 + 0.65 * t)))
        if self.fade:
            # Per-particle alpha needs its own surface; blitting a small one is
            # still cheaper than any full-screen alpha pass.
            diameter = radius * 2
            surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
            pygame.draw.circle(surf, (*self.color, int(255 * t)), (radius, radius), radius)
            surface.blit(surf, (self.x - radius, self.y - radius))
        else:
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), radius)


class FloatingText:
    __slots__ = ("text", "x", "y", "vy", "life", "max_life", "color", "font")

    def __init__(self, text, x, y, font, color, life=0.9, vy=-70.0):
        self.text, self.x, self.y = text, x, y
        self.font = font
        self.color = color
        self.life = self.max_life = life
        self.vy = vy

    def update(self, dt: float) -> bool:
        self.life -= dt
        if self.life <= 0:
            return False
        self.y += self.vy * dt
        self.vy *= 0.94
        return True

    def draw(self, surface: pygame.Surface) -> None:
        t = max(self.life / self.max_life, 0.0)
        img = self.font.render(self.text, True, self.color)
        img.set_alpha(int(255 * min(1.0, t * 1.6)))
        surface.blit(img, img.get_rect(center=(int(self.x), int(self.y))))


class EffectSystem:
    """One update/draw call for every transient visual in the game."""

    def __init__(self) -> None:
        self.particles: list[Particle] = []
        self.texts: list[FloatingText] = []
        self.shake = 0.0
        self.flash = 0.0

    def clear(self) -> None:
        self.particles.clear()
        self.texts.clear()
        self.shake = 0.0
        self.flash = 0.0

    def update(self, dt: float) -> None:
        self.particles = [p for p in self.particles if p.update(dt)]
        self.texts = [t for t in self.texts if t.update(dt)]
        self.shake = max(0.0, self.shake - dt * 34.0)
        self.flash = max(0.0, self.flash - dt * 2.6)

    def draw(self, surface: pygame.Surface) -> None:
        for p in self.particles:
            p.draw(surface)
        for t in self.texts:
            t.draw(surface)

    @property
    def shake_offset(self) -> tuple:
        if self.shake <= 0.05:
            return (0, 0)
        return (random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake))

    # -- emitters ----------------------------------------------------------
    def trail(self, x, y, color) -> None:
        self.particles.append(Particle(
            x + random.uniform(-3, 3), y + random.uniform(-3, 3),
            random.uniform(-38, -12), random.uniform(-16, 16),
            random.uniform(0.25, 0.5), random.uniform(2.0, 4.0), color,
        ))

    def flap_burst(self, x, y, color) -> None:
        for _ in range(12):
            angle = random.uniform(math.pi * 0.25, math.pi * 0.75)
            speed = random.uniform(70, 190)
            self.particles.append(Particle(
                x, y, -math.cos(angle) * speed * 0.6, math.sin(angle) * speed,
                random.uniform(0.3, 0.6), random.uniform(2.0, 4.5), color, gravity=120,
            ))

    def score_burst(self, x, y, color) -> None:
        for _ in range(22):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(60, 230)
            self.particles.append(Particle(
                x, y, math.cos(angle) * speed, math.sin(angle) * speed,
                random.uniform(0.4, 0.9), random.uniform(2.0, 5.0), color, gravity=190,
            ))

    def crash_burst(self, x, y) -> None:
        palette = [(255, 206, 74), (255, 150, 60), (238, 92, 84), (255, 255, 255)]
        for _ in range(46):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(80, 380)
            self.particles.append(Particle(
                x, y, math.cos(angle) * speed, math.sin(angle) * speed,
                random.uniform(0.5, 1.2), random.uniform(2.5, 6.0),
                random.choice(palette), gravity=560,
            ))
        self.shake = 16.0
        self.flash = 0.85

    def popup(self, text, x, y, font, color) -> None:
        self.texts.append(FloatingText(text, x, y, font, color))
