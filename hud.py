"""All 2D user-interface drawing: score, webcam panel, and the full-screen
start / pause / game-over overlays.

Kept separate from `game.py` so game logic never mixes with layout code.
"""

from __future__ import annotations

import math

import pygame

import settings as cfg
from gestures import FIST, PALM, PINCH, POINT

_FONT_CANDIDATES = [
    "Poppins", "Montserrat", "Nunito", "Ubuntu", "DejaVu Sans", "Verdana",
    "Arial", "Liberation Sans",
]

GESTURE_LABEL = {
    PINCH: ("PINCH - flap", cfg.ACCENT),
    FIST: ("FIST - pause", (255, 150, 90)),
    PALM: ("OPEN PALM - restart", cfg.OK_GREEN),
    POINT: ("POINTING - steering", (120, 210, 255)),
    "none": ("--", cfg.TEXT_MUTED),
}


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in _FONT_CANDIDATES:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, int(size * 1.1))


def rounded_panel(size, color, alpha=210, radius=16, border=None) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(surf, (*color, alpha), surf.get_rect(), border_radius=radius)
    if border:
        pygame.draw.rect(surf, border, surf.get_rect(), 2, border_radius=radius)
    return surf


def text_with_shadow(surface, font, text, color, center=None, topleft=None, shadow=(0, 0, 0, 120)):
    shadow_img = font.render(text, True, shadow[:3])
    shadow_img.set_alpha(shadow[3] if len(shadow) > 3 else 120)
    img = font.render(text, True, color)
    if center is not None:
        rect = img.get_rect(center=center)
    else:
        rect = img.get_rect(topleft=topleft)
    surface.blit(shadow_img, (rect.x + 2, rect.y + 3))
    surface.blit(img, rect)
    return rect


class Hud:
    def __init__(self) -> None:
        self.f_huge = load_font(74, bold=True)
        self.f_big = load_font(44, bold=True)
        self.f_mid = load_font(26, bold=True)
        self.f_body = load_font(20)
        self.f_small = load_font(15)
        self.f_tiny = load_font(13)
        self._panel_surf: pygame.Surface | None = None

    # -- in-game -----------------------------------------------------------
    def draw_score(self, surface, score: int, pop: float) -> None:
        scale = 1.0 + 0.35 * pop
        img = self.f_huge.render(str(score), True, cfg.TEXT_LIGHT)
        if scale != 1.0:
            img = pygame.transform.rotozoom(img, 0, scale)
        rect = img.get_rect(center=(cfg.WINDOW_WIDTH // 2, 74))
        shadow = self.f_huge.render(str(score), True, (20, 30, 45))
        if scale != 1.0:
            shadow = pygame.transform.rotozoom(shadow, 0, scale)
        shadow.set_alpha(120)
        surface.blit(shadow, (rect.x + 3, rect.y + 4))
        surface.blit(img, rect)

    def draw_camera_panel(self, surface, state, status: str, render_fps: float,
                          keyboard_mode: bool) -> None:
        """Webcam preview plus live telemetry: landmarks, fingertip, gesture,
        both frame rates and the game status."""
        pw, ph = cfg.PANEL_WIDTH, cfg.PANEL_HEIGHT
        pad = 8
        header = 22
        footer = 84
        box_w = pw + pad * 2
        box_h = ph + header + footer + pad
        x = cfg.WINDOW_WIDTH - box_w - cfg.PANEL_MARGIN
        y = cfg.PANEL_MARGIN

        if self._panel_surf is None or self._panel_surf.get_size() != (box_w, box_h):
            self._panel_surf = rounded_panel((box_w, box_h), cfg.PANEL_BG, 225, 14,
                                             border=(58, 70, 92))
        surface.blit(self._panel_surf, (x, y))

        text_with_shadow(surface, self.f_tiny, "HAND CAMERA", cfg.TEXT_MUTED,
                         topleft=(x + pad + 2, y + 6))

        frame = state.frame
        fx, fy = x + pad, y + header
        if frame is not None:
            cam = pygame.image.frombuffer(frame.tobytes(), (pw, ph), "RGB")
            surface.blit(cam, (fx, fy))
        else:
            pygame.draw.rect(surface, (30, 36, 48), (fx, fy, pw, ph))
            msg = "keyboard mode" if keyboard_mode else "starting camera..."
            text_with_shadow(surface, self.f_small, msg, cfg.TEXT_MUTED,
                             center=(fx + pw // 2, fy + ph // 2))

        border = cfg.OK_GREEN if state.detected else (
            cfg.ACCENT if state.usable else cfg.DANGER)
        pygame.draw.rect(surface, border, (fx - 1, fy - 1, pw + 2, ph + 2), 2)

        # telemetry rows
        label, color = GESTURE_LABEL.get(state.gesture, (state.gesture, cfg.TEXT_MUTED))
        rows = [
            ("gesture", label, color),
            ("fingertip", f"x {state.x:.2f}   y {state.y:.2f}"
                          f"   {'LOCKED' if state.detected else 'NO HAND'}",
             cfg.TEXT_LIGHT if state.detected else cfg.DANGER),
            ("fps", f"game {render_fps:4.0f}   cv {state.cv_fps:4.0f}", cfg.TEXT_MUTED),
            ("status", status, cfg.ACCENT),
        ]
        ty = fy + ph + 8
        for key, value, color in rows:
            k = self.f_tiny.render(key, True, (128, 140, 160))
            surface.blit(k, (x + pad + 2, ty))
            v = self.f_tiny.render(value, True, color)
            surface.blit(v, (x + pad + 58, ty))
            ty += 17

        if state.error:
            text_with_shadow(surface, self.f_tiny, state.error[:44], cfg.DANGER,
                             topleft=(x + pad + 2, y + box_h + 4))

    def draw_hand_guide(self, surface, target_y: float | None) -> None:
        """Thin marker showing where the fingertip currently maps to."""
        if target_y is None:
            return
        y = int(target_y)
        pygame.draw.line(surface, (255, 255, 255, 60), (cfg.BIRD_X - 70, y),
                         (cfg.BIRD_X - 30, y), 2)
        pygame.draw.polygon(surface, cfg.ACCENT,
                            [(cfg.BIRD_X - 28, y), (cfg.BIRD_X - 40, y - 6),
                             (cfg.BIRD_X - 40, y + 6)])

    # -- overlays ----------------------------------------------------------
    @staticmethod
    def dim(surface, alpha=150) -> None:
        veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        veil.fill((*cfg.OVERLAY, alpha))
        surface.blit(veil, (0, 0))

    def draw_start(self, surface, hand_detected: bool, t: float, keyboard_mode: bool) -> None:
        self.dim(surface, 140)
        cx = cfg.WINDOW_WIDTH // 2 - 110

        text_with_shadow(surface, self.f_huge, "HandFlap", cfg.TEXT_LIGHT, center=(cx, 92))
        text_with_shadow(surface, self.f_body, "Flappy Bird, flown with your hand",
                         cfg.TEXT_MUTED, center=(cx, 140))

        card = rounded_panel((470, 250), (16, 22, 34), 205, 18, border=(60, 74, 98))
        card_pos = (cx - 235, 178)
        surface.blit(card, card_pos)

        lines = [
            ("Index finger", "move up / down to fly the bird", cfg.TEXT_LIGHT),
            ("Pinch", "thumb + index together = flap", cfg.ACCENT),
            ("Fist", "close your hand to pause", (255, 150, 90)),
            ("Open palm", "restart after game over", cfg.OK_GREEN),
        ]
        ly = card_pos[1] + 26
        for title, desc, color in lines:
            text_with_shadow(surface, self.f_mid, title, color,
                             topleft=(card_pos[0] + 26, ly))
            text_with_shadow(surface, self.f_small, desc, cfg.TEXT_MUTED,
                             topleft=(card_pos[0] + 190, ly + 9))
            ly += 44

        text_with_shadow(surface, self.f_tiny,
                         "keyboard fallback:  SPACE flap   P pause   R restart   "
                         "C camera panel   ESC quit",
                         (150, 162, 182), center=(cx, card_pos[1] + 218))

        pulse = 0.55 + 0.45 * math.sin(t * 4.0)
        if keyboard_mode:
            msg, color = "Camera unavailable - press SPACE to play", cfg.DANGER
        elif hand_detected:
            msg, color = "Hand detected - starting...", cfg.OK_GREEN
        else:
            msg, color = "Show your hand to the camera to begin", cfg.ACCENT
        img = self.f_mid.render(msg, True, color)
        img.set_alpha(int(150 + 105 * pulse))
        surface.blit(img, img.get_rect(center=(cx, 470)))

    def draw_countdown(self, surface, value: float) -> None:
        self.dim(surface, 90)
        n = max(1, math.ceil(value))
        frac = 1.0 - (value - math.floor(value))
        img = self.f_huge.render(str(n), True, cfg.TEXT_LIGHT)
        img = pygame.transform.rotozoom(img, 0, 1.0 + 0.9 * (1.0 - frac))
        img.set_alpha(int(255 * min(1.0, frac * 2)))
        surface.blit(img, img.get_rect(center=(cfg.WINDOW_WIDTH // 2 - 110,
                                               cfg.WINDOW_HEIGHT // 2)))

    def draw_pause(self, surface, t: float) -> None:
        self.dim(surface, 165)
        cx = cfg.WINDOW_WIDTH // 2 - 110
        text_with_shadow(surface, self.f_huge, "PAUSED", cfg.TEXT_LIGHT,
                         center=(cx, cfg.WINDOW_HEIGHT // 2 - 40))
        pulse = 0.5 + 0.5 * math.sin(t * 3.4)
        img = self.f_mid.render("open your hand or press P to resume", True, cfg.TEXT_MUTED)
        img.set_alpha(int(140 + 115 * pulse))
        surface.blit(img, img.get_rect(center=(cx, cfg.WINDOW_HEIGHT // 2 + 26)))

    def draw_game_over(self, surface, score: int, best: int, new_best: bool,
                       t: float, ready: bool) -> None:
        self.dim(surface, 170)
        cx = cfg.WINDOW_WIDTH // 2 - 110
        top = 120

        text_with_shadow(surface, self.f_huge, "GAME OVER", cfg.DANGER, center=(cx, top))

        card = rounded_panel((380, 176), (16, 22, 34), 215, 18, border=(60, 74, 98))
        card_pos = (cx - 190, top + 52)
        surface.blit(card, card_pos)

        text_with_shadow(surface, self.f_small, "SCORE", cfg.TEXT_MUTED,
                         center=(card_pos[0] + 105, card_pos[1] + 36))
        text_with_shadow(surface, self.f_big, str(score), cfg.TEXT_LIGHT,
                         center=(card_pos[0] + 105, card_pos[1] + 78))
        text_with_shadow(surface, self.f_small, "BEST", cfg.TEXT_MUTED,
                         center=(card_pos[0] + 275, card_pos[1] + 36))
        text_with_shadow(surface, self.f_big, str(best), cfg.ACCENT,
                         center=(card_pos[0] + 275, card_pos[1] + 78))

        if new_best:
            glow = 0.5 + 0.5 * math.sin(t * 6.0)
            img = self.f_mid.render("NEW HIGH SCORE!", True, cfg.ACCENT)
            img.set_alpha(int(140 + 115 * glow))
            surface.blit(img, img.get_rect(center=(card_pos[0] + 190, card_pos[1] + 142)))

        pulse = 0.5 + 0.5 * math.sin(t * 3.6)
        msg = "show an OPEN PALM to play again" if ready else "get ready..."
        color = cfg.OK_GREEN if ready else cfg.TEXT_MUTED
        img = self.f_mid.render(msg, True, color)
        img.set_alpha(int(150 + 105 * pulse))
        surface.blit(img, img.get_rect(center=(cx, card_pos[1] + 216)))
        text_with_shadow(surface, self.f_tiny, "or press R to restart   -   ESC to quit",
                         (150, 162, 182), center=(cx, card_pos[1] + 248))

    def draw_hand_lost_banner(self, surface, t: float) -> None:
        pulse = 0.5 + 0.5 * math.sin(t * 7.0)
        box = rounded_panel((300, 40), (60, 20, 26), int(140 + 60 * pulse), 12,
                            border=cfg.DANGER)
        pos = (cfg.WINDOW_WIDTH // 2 - 260, cfg.PLAY_BOTTOM - 62)
        surface.blit(box, pos)
        text_with_shadow(surface, self.f_small, "hand lost - bird is falling!",
                         cfg.TEXT_LIGHT, center=(pos[0] + 150, pos[1] + 20))
