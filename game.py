"""Game loop, state machine and the glue between hand input and gameplay.

This module knows nothing about OpenCV or MediaPipe. It only ever sees the
`HandState` snapshot published by `hand_tracker`, which means the game can be
played with the keyboard alone if no camera is present.
"""

from __future__ import annotations

import json

import pygame

import settings as cfg
from background import Background
from effects import EffectSystem
from gestures import FIST, PALM, PINCH
from hand_tracker import HandState, HandTracker
from hud import Hud
from obstacles import PipeManager
from player import Bird

# Game states
START = "start"
COUNTDOWN = "countdown"
PLAYING = "playing"
PAUSED = "paused"
GAME_OVER = "game over"

RESTART_LOCKOUT = 0.9  # seconds after a crash before a palm can restart


class Game:
    def __init__(self, screen: pygame.Surface, tracker: HandTracker):
        self.screen = screen
        self.tracker = tracker
        self.world = pygame.Surface(screen.get_size())
        self.clock = pygame.time.Clock()
        self.running = True

        self.background = Background()
        self.pipes = PipeManager()
        self.bird = Bird()
        self.effects = EffectSystem()
        self.hud = Hud()

        self.state = START
        self.score = 0
        self.best = self._load_best()
        self.new_best = False
        self.countdown = 0.0
        self.state_time = 0.0
        self.t = 0.0
        self.show_panel = True
        self.hand = HandState(error=tracker.error)
        self.target_y: float | None = None
        self._score_pop = 0.0
        self._trail_timer = 0.0
        self._hand_present_time = 0.0
        self.enter_menu()

    # -- persistence -------------------------------------------------------
    def _load_best(self) -> int:
        try:
            with open(cfg.HIGHSCORE_FILE, "r", encoding="utf-8") as fh:
                return int(json.load(fh).get("best", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            return 0  # missing or corrupt file simply means "no record yet"

    def _save_best(self) -> None:
        try:
            with open(cfg.HIGHSCORE_FILE, "w", encoding="utf-8") as fh:
                json.dump({"best": self.best}, fh)
        except OSError:
            pass  # a read-only directory must never crash the game

    # -- state transitions -------------------------------------------------
    def set_state(self, state: str) -> None:
        self.state = state
        self.state_time = 0.0

    def start_countdown(self) -> None:
        self.reset_round()
        self.countdown = 3.0
        self.set_state(COUNTDOWN)

    def reset_round(self) -> None:
        self.score = 0
        self.new_best = False
        self._score_pop = 0.0
        self.pipes.reset()
        self.bird.x = cfg.BIRD_X
        self.bird.start_y = cfg.BIRD_START_Y
        self.bird.reset(cfg.BIRD_START_Y)
        self.effects.clear()

    def enter_menu(self) -> None:
        self.bird.x = cfg.MENU_BIRD_X
        self.bird.start_y = cfg.MENU_BIRD_Y
        self.bird.reset(cfg.MENU_BIRD_Y)
        self.set_state(START)

    def game_over(self) -> None:
        if self.state == GAME_OVER:
            return
        self.bird.alive = False
        self.effects.crash_burst(self.bird.x, self.bird.y)
        if self.score > self.best:
            self.best = self.score
            self.new_best = True
            self._save_best()
        self.set_state(GAME_OVER)

    # -- input -------------------------------------------------------------
    def handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)

    def _handle_key(self, key: int) -> None:
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.running = False
        elif key == pygame.K_c:
            self.show_panel = not self.show_panel
        elif key in (pygame.K_SPACE, pygame.K_UP):
            if self.state == START:
                self.start_countdown()
            elif self.state == PLAYING:
                self.flap()
            elif self.state == PAUSED:
                self.set_state(PLAYING)
        elif key == pygame.K_p:
            if self.state == PLAYING:
                self.set_state(PAUSED)
            elif self.state == PAUSED:
                self.set_state(PLAYING)
        elif key == pygame.K_r:
            if self.state in (GAME_OVER, PLAYING, PAUSED):
                self.start_countdown()

    def handle_hand(self) -> None:
        """Translate the CV snapshot into gameplay actions."""
        state = self.hand

        # Continuous control: fingertip -> a target height in the playfield.
        if state.usable:
            lo = cfg.BIRD_RADIUS + 12
            hi = cfg.PLAY_BOTTOM - cfg.BIRD_RADIUS - 12
            new_target = lo + (hi - lo) * state.control
            if self.target_y is None or abs(new_target - self.target_y) > cfg.CONTROL_DEADZONE:
                self.target_y = new_target
        else:
            self.target_y = None  # hand gone: hand off to gravity

        # Auto-start once a hand has been held steady in view.
        if self.state == START:
            self._hand_present_time = self._hand_present_time + 1 if state.detected else 0
            if self._hand_present_time > 25:  # ~0.4 s of continuous detection
                self._hand_present_time = 0
                self.start_countdown()

        for event in state.events:
            self._handle_gesture(event)

    def _handle_gesture(self, gesture: str) -> None:
        if gesture == PINCH:
            if self.state == PLAYING:
                self.flap()
            elif self.state == START:
                self.start_countdown()
        elif gesture == FIST:
            if self.state == PLAYING:
                self.set_state(PAUSED)
            elif self.state == PAUSED:
                self.set_state(PLAYING)
        elif gesture == PALM:
            if self.state == GAME_OVER and self.state_time > RESTART_LOCKOUT:
                self.start_countdown()
            elif self.state == PAUSED:
                self.set_state(PLAYING)

    def flap(self) -> None:
        self.bird.flap()
        self.effects.flap_burst(self.bird.x - 6, self.bird.y + 10, cfg.BIRD_WING)

    # -- simulation --------------------------------------------------------
    def update(self, dt: float) -> None:
        self.t += dt
        self.state_time += dt
        self.hand = self.tracker.get_state()
        self.handle_hand()

        speed = self.pipes.speed_for(self.score)
        self._score_pop = max(0.0, self._score_pop - dt * 3.2)

        if self.state == START:
            self.background.update(dt, cfg.PIPE_SPEED * 0.5)
            self.bird.idle(dt, self.t)
        elif self.state == COUNTDOWN:
            self.background.update(dt, speed * 0.5)
            self.bird.idle(dt, self.t)
            self.countdown -= dt
            if self.countdown <= 0:
                self.bird.reset(self.bird.y)
                self.set_state(PLAYING)
        elif self.state == PLAYING:
            self.background.update(dt, speed)
            self.bird.update(dt, self.target_y)
            self.pipes.update(dt, self.score)
            self._update_scoring()
            self._emit_trail(dt)
            self._check_collisions()
        elif self.state == GAME_OVER:
            self.background.update(dt, speed * 0.25)
            self.bird.update(dt, None)
            floor = cfg.PLAY_BOTTOM - self.bird.radius
            if self.bird.y > floor:
                self.bird.y = floor
                self.bird.vy = 0.0

        self.effects.update(dt)

    def _update_scoring(self) -> None:
        gained = self.pipes.collect_score(self.bird.x)
        if gained:
            self.score += gained
            self._score_pop = 1.0
            self.effects.score_burst(self.bird.x + 30, self.bird.y, cfg.ACCENT)
            self.effects.popup(f"+{gained}", self.bird.x + 60, self.bird.y - 24,
                               self.hud.f_mid, cfg.ACCENT)
            if self.score % 5 == 0:
                self.effects.popup("SPEED UP!", cfg.WINDOW_WIDTH // 2, 160,
                                   self.hud.f_mid, cfg.DANGER)

    def _emit_trail(self, dt: float) -> None:
        self._trail_timer += dt
        if self._trail_timer >= 0.03:
            self._trail_timer = 0.0
            self.effects.trail(self.bird.x - 14, self.bird.y + 6, (255, 236, 190))

    def _check_collisions(self) -> None:
        r = self.bird.radius
        if self.bird.y + r >= cfg.PLAY_BOTTOM:
            self.bird.y = cfg.PLAY_BOTTOM - r
            self.game_over()
            return
        if self.pipes.collides(self.bird.x, self.bird.y, r):
            self.game_over()

    # -- rendering ---------------------------------------------------------
    def draw(self) -> None:
        world = self.world
        self.background.draw(world)
        self.pipes.draw(world)

        if self.state == PLAYING and self.hand.usable:
            self.hud.draw_hand_guide(world, self.target_y)

        self.effects.draw(world)
        self.bird.draw(world, 1.7 if self.state == START else 1.0)
        self.background.draw_ground(world)

        offset = self.effects.shake_offset
        self.screen.blit(world, offset)

        if self.effects.flash > 0.01:
            flash = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            flash.fill((255, 255, 255, int(180 * min(1.0, self.effects.flash))))
            self.screen.blit(flash, (0, 0))

        if self.state in (PLAYING, PAUSED, COUNTDOWN):
            self.hud.draw_score(self.screen, self.score, self._score_pop)
            if self.state == PLAYING and not self.hand.usable and not self.keyboard_mode:
                self.hud.draw_hand_lost_banner(self.screen, self.t)

        if self.state == START:
            self.hud.draw_start(self.screen, self.hand.detected, self.t, self.keyboard_mode)
        elif self.state == COUNTDOWN:
            self.hud.draw_countdown(self.screen, self.countdown)
        elif self.state == PAUSED:
            self.hud.draw_pause(self.screen, self.t)
        elif self.state == GAME_OVER:
            self.hud.draw_game_over(self.screen, self.score, self.best, self.new_best,
                                    self.t, self.state_time > RESTART_LOCKOUT)

        if self.show_panel:
            self.hud.draw_camera_panel(self.screen, self.hand, self.state,
                                       self.clock.get_fps(), self.keyboard_mode)

        pygame.display.flip()

    @property
    def keyboard_mode(self) -> bool:
        return not self.tracker.available

    # -- main loop ---------------------------------------------------------
    def run(self) -> None:
        while self.running:
            # Cap dt so a stall (window drag, first-frame model load) cannot
            # teleport the bird through a pipe.
            dt = min(self.clock.tick(cfg.FPS) / 1000.0, 0.05)
            self.handle_events()
            self.update(dt)
            self.draw()
