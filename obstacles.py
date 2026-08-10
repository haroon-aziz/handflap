"""Scrolling pipes: spawning, difficulty curve, collision and scoring."""

from __future__ import annotations

import random

import pygame

import settings as cfg


def circle_rect_collision(cx: float, cy: float, r: float, rect: pygame.Rect) -> bool:
    """Closest-point test. Cheaper and far more forgiving than rect-vs-rect on
    a round bird - clipping a pipe corner no longer counts as a hit."""
    nearest_x = max(rect.left, min(cx, rect.right))
    nearest_y = max(rect.top, min(cy, rect.bottom))
    dx, dy = cx - nearest_x, cy - nearest_y
    return dx * dx + dy * dy < r * r


class Pipe:
    __slots__ = ("x", "gap_center", "gap_size", "scored")

    def __init__(self, x: float, gap_center: float, gap_size: float):
        self.x = x
        self.gap_center = gap_center
        self.gap_size = gap_size
        self.scored = False

    @property
    def gap_top(self) -> float:
        return self.gap_center - self.gap_size / 2

    @property
    def gap_bottom(self) -> float:
        return self.gap_center + self.gap_size / 2

    @property
    def top_rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), 0, cfg.PIPE_WIDTH, int(self.gap_top))

    @property
    def bottom_rect(self) -> pygame.Rect:
        top = int(self.gap_bottom)
        return pygame.Rect(int(self.x), top, cfg.PIPE_WIDTH, int(cfg.PLAY_BOTTOM - top))


class PipeManager:
    """Owns every pipe plus the difficulty curve."""

    def __init__(self) -> None:
        self.pipes: list[Pipe] = []
        self._last_center = cfg.PLAY_BOTTOM * 0.5
        self._body, self._cap = self._build_textures()
        self.reset()

    # -- difficulty --------------------------------------------------------
    @staticmethod
    def speed_for(score: int) -> float:
        return min(cfg.PIPE_SPEED + score * cfg.PIPE_SPEED_PER_POINT, cfg.PIPE_SPEED_MAX)

    @staticmethod
    def gap_for(score: int) -> float:
        return max(cfg.PIPE_GAP - score * cfg.PIPE_GAP_PER_POINT, cfg.PIPE_GAP_MIN)

    @staticmethod
    def spacing_for(score: int) -> float:
        return max(cfg.PIPE_SPACING - score * 2.0, cfg.PIPE_SPACING_MIN)

    def reset(self) -> None:
        self.pipes.clear()
        self._last_center = cfg.PLAY_BOTTOM * 0.5
        # Give the player a calm first screen before the first pipe arrives.
        self.pipes.append(self._make(cfg.WINDOW_WIDTH + 140, 0))
        self.pipes.append(self._make(cfg.WINDOW_WIDTH + 140 + cfg.PIPE_SPACING, 0))

    def _make(self, x: float, score: int) -> Pipe:
        gap = self.gap_for(score)
        lo = cfg.PIPE_EDGE_MARGIN + gap / 2
        hi = cfg.PLAY_BOTTOM - cfg.PIPE_EDGE_MARGIN - gap / 2
        if lo > hi:
            lo = hi = cfg.PLAY_BOTTOM / 2
        # Random, but never a jump so large it is unreachable from the last gap.
        lo = max(lo, self._last_center - cfg.PIPE_MAX_GAP_DELTA)
        hi = min(hi, self._last_center + cfg.PIPE_MAX_GAP_DELTA)
        center = random.uniform(lo, hi) if hi > lo else lo
        self._last_center = center
        return Pipe(x, center, gap)

    # -- simulation --------------------------------------------------------
    def update(self, dt: float, score: int) -> None:
        speed = self.speed_for(score)
        for pipe in self.pipes:
            pipe.x -= speed * dt

        while self.pipes and self.pipes[0].x + cfg.PIPE_WIDTH < -20:
            self.pipes.pop(0)

        spacing = self.spacing_for(score)
        rightmost = max((p.x for p in self.pipes), default=-1e9)
        if rightmost < cfg.WINDOW_WIDTH - spacing:
            self.pipes.append(self._make(rightmost + spacing, score))

    def collect_score(self, bird_x: float) -> int:
        """Count pipes whose gap the bird just passed."""
        gained = 0
        for pipe in self.pipes:
            if not pipe.scored and pipe.x + cfg.PIPE_WIDTH < bird_x:
                pipe.scored = True
                gained += 1
        return gained

    def collides(self, cx: float, cy: float, r: float) -> bool:
        for pipe in self.pipes:
            if pipe.x - r > cx or pipe.x + cfg.PIPE_WIDTH + r < cx:
                continue  # cheap horizontal reject before the real test
            if circle_rect_collision(cx, cy, r, pipe.top_rect):
                return True
            if circle_rect_collision(cx, cy, r, pipe.bottom_rect):
                return True
        return False

    def nearest_gap(self, bird_x: float) -> Pipe | None:
        for pipe in self.pipes:
            if pipe.x + cfg.PIPE_WIDTH >= bird_x:
                return pipe
        return None

    # -- rendering ---------------------------------------------------------
    @staticmethod
    def _build_textures() -> tuple:
        """Pipes are shaded once at startup and blitted as slices afterwards,
        so per-frame drawing cost stays flat no matter how many are on screen."""
        w, h = cfg.PIPE_WIDTH, cfg.WINDOW_HEIGHT
        body = pygame.Surface((w, h), pygame.SRCALPHA)
        for x in range(w):
            t = x / max(w - 1, 1)
            if t < 0.18:
                c = cfg.PIPE_DARK
            elif t < 0.42:
                k = (t - 0.18) / 0.24
                c = [int(cfg.PIPE_BODY[i] + (cfg.PIPE_LIGHT[i] - cfg.PIPE_BODY[i]) * k)
                     for i in range(3)]
            else:
                k = (t - 0.42) / 0.58
                c = [int(cfg.PIPE_LIGHT[i] + (cfg.PIPE_DARK[i] - cfg.PIPE_LIGHT[i]) * k)
                     for i in range(3)]
            pygame.draw.line(body, c, (x, 0), (x, h))

        cap_w, cap_h = w + 18, 34
        cap = pygame.Surface((cap_w, cap_h), pygame.SRCALPHA)
        for x in range(cap_w):
            t = x / max(cap_w - 1, 1)
            k = abs(t - 0.34) * 1.7
            c = [int(cfg.PIPE_LIGHT[i] + (cfg.PIPE_DARK[i] - cfg.PIPE_LIGHT[i]) * min(k, 1.0))
                 for i in range(3)]
            pygame.draw.line(cap, c, (x, 0), (x, cap_h))
        pygame.draw.rect(cap, cfg.PIPE_EDGE, cap.get_rect(), 3, border_radius=6)
        return body, cap

    def draw(self, surface: pygame.Surface) -> None:
        cap_w, cap_h = self._cap.get_size()
        cap_dx = (cfg.PIPE_WIDTH - cap_w) // 2
        for pipe in self.pipes:
            if pipe.x > cfg.WINDOW_WIDTH or pipe.x + cfg.PIPE_WIDTH < 0:
                continue
            x = int(pipe.x)
            top_h = int(pipe.gap_top)
            bottom_y = int(pipe.gap_bottom)
            bottom_h = int(cfg.PLAY_BOTTOM - pipe.gap_bottom)

            if top_h > 0:
                surface.blit(self._body, (x, 0), pygame.Rect(0, 0, cfg.PIPE_WIDTH, top_h))
                surface.blit(self._cap, (x + cap_dx, top_h - cap_h))
            if bottom_h > 0:
                surface.blit(self._body, (x, bottom_y),
                             pygame.Rect(0, 0, cfg.PIPE_WIDTH, bottom_h))
                surface.blit(self._cap, (x + cap_dx, bottom_y))
