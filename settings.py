"""Central configuration for HandFlap.

Every tunable number lives here so gameplay feel and CV behaviour can be
adjusted without touching logic.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
HIGHSCORE_FILE = ROOT_DIR / "highscore.json"
MODEL_DIR = ROOT_DIR / "models"
MODEL_PATH = MODEL_DIR / "hand_landmarker.task"
# Fetched once during setup; the game never touches the network while running.
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

# --------------------------------------------------------------------------
# Window / timing
# --------------------------------------------------------------------------
WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 640
WINDOW_TITLE = "HandFlap - Webcam Controlled Flappy Bird"
FPS = 60
GROUND_HEIGHT = 96
PLAY_TOP = 0
PLAY_BOTTOM = WINDOW_HEIGHT - GROUND_HEIGHT

# --------------------------------------------------------------------------
# Webcam capture
# --------------------------------------------------------------------------
CAMERA_INDEX = 0
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
CAPTURE_FPS = 30
# MediaPipe runs on a downscaled copy; detection quality barely changes but
# per-frame cost drops a lot.
DETECT_WIDTH = 320
MIRROR_CAMERA = True  # selfie view feels natural

# Webcam preview panel drawn inside the pygame window
PANEL_WIDTH = 256
PANEL_HEIGHT = 192
PANEL_MARGIN = 16

# --------------------------------------------------------------------------
# MediaPipe Hands
# --------------------------------------------------------------------------
MAX_NUM_HANDS = 2  # detect two, then pick the most confident one
MIN_DETECTION_CONFIDENCE = 0.6
MIN_TRACKING_CONFIDENCE = 0.5
MODEL_COMPLEXITY = 0  # 0 = lite/fast, 1 = full/accurate

# How long a fingertip position stays usable after the hand disappears.
HAND_LOST_GRACE = 0.35  # seconds
# How far (normalised) the tracked fingertip may jump between frames and still
# count as the same hand.
CONTINUITY_RADIUS = 0.35

# --------------------------------------------------------------------------
# Fingertip smoothing (One Euro filter)
# --------------------------------------------------------------------------
# Lower min_cutoff -> smoother but laggier. beta counteracts lag on fast moves.
EURO_MIN_CUTOFF = 1.2
EURO_BETA = 0.035
EURO_DERIV_CUTOFF = 1.0

# --------------------------------------------------------------------------
# Control mapping
# --------------------------------------------------------------------------
# Vertical slice of the camera frame mapped onto the playfield. Ignoring the
# extreme edges means the player never has to reach out of frame.
CONTROL_TOP = 0.18
CONTROL_BOTTOM = 0.82
CONTROL_DEADZONE = 4.0  # px, ignore sub-pixel hand tremor

# --------------------------------------------------------------------------
# Gesture thresholds
# --------------------------------------------------------------------------
# All distances are normalised by hand size, so they hold at any camera range.
PINCH_ON = 0.42   # below this ratio -> pinch closed
PINCH_OFF = 0.60  # above this ratio -> pinch released (hysteresis)
FIST_EXTENDED_MAX = 1     # at most 1 finger extended -> fist
PALM_EXTENDED_MIN = 4     # at least 4 fingers extended -> open palm
FINGER_EXTEND_RATIO = 1.08  # tip must be this much further from wrist than pip
GESTURE_STABLE_FRAMES = 3   # consecutive agreeing frames before committing
GESTURE_COOLDOWN = 0.55     # seconds between repeated discrete triggers

# --------------------------------------------------------------------------
# Bird physics
# --------------------------------------------------------------------------
BIRD_X = 250
BIRD_START_Y = WINDOW_HEIGHT * 0.45
# Where the bird hovers on the start screen: clear of the instruction card and
# the webcam panel.
MENU_BIRD_X = 775
MENU_BIRD_Y = 470
BIRD_RADIUS = 18
BIRD_COLLIDER_SCALE = 0.78  # forgiving hitbox

GRAVITY = 1500.0            # px/s^2, free fall (no hand)
HAND_GRAVITY_SCALE = 0.22   # gravity is mostly cancelled while hand-guided
FOLLOW_GAIN = 7.5           # target velocity = error * gain
FOLLOW_RESPONSE = 14.0      # how fast actual velocity reaches target velocity
FLAP_IMPULSE = -430.0       # pinch flap
MAX_FALL_SPEED = 780.0
MAX_RISE_SPEED = -640.0
BIRD_MAX_TILT = 70.0        # degrees

# --------------------------------------------------------------------------
# Pipes / difficulty
# --------------------------------------------------------------------------
PIPE_WIDTH = 88
PIPE_SPACING = 330.0        # horizontal distance between pipes, px
PIPE_SPACING_MIN = 250.0
PIPE_SPEED = 210.0          # px/s at score 0
PIPE_SPEED_MAX = 400.0
PIPE_SPEED_PER_POINT = 5.0
PIPE_GAP = 215.0            # vertical opening at score 0
PIPE_GAP_MIN = 150.0
PIPE_GAP_PER_POINT = 3.0
PIPE_EDGE_MARGIN = 70.0     # keep gaps away from ceiling/ground
PIPE_MAX_GAP_DELTA = 170.0  # max gap-centre change between consecutive pipes

# --------------------------------------------------------------------------
# Colours (R, G, B)
# --------------------------------------------------------------------------
SKY_TOP = (86, 173, 235)
SKY_BOTTOM = (196, 235, 245)
SUN = (255, 238, 176)
HILL_FAR = (126, 190, 168)
HILL_NEAR = (94, 168, 143)
CLOUD = (255, 255, 255)
GROUND_TOP = (222, 199, 130)
GROUND_BODY = (196, 168, 104)
GRASS_TOP = (118, 200, 106)
GRASS_DARK = (82, 165, 78)
PIPE_BODY = (86, 190, 96)
PIPE_LIGHT = (146, 224, 140)
PIPE_DARK = (48, 128, 62)
PIPE_EDGE = (32, 86, 44)
BIRD_BODY = (255, 206, 74)
BIRD_BODY_DARK = (232, 164, 40)
BIRD_WING = (255, 240, 205)
BIRD_BEAK = (240, 122, 52)
BIRD_EYE = (38, 38, 46)
TEXT_LIGHT = (255, 255, 255)
TEXT_DARK = (28, 34, 44)
TEXT_MUTED = (204, 214, 226)
ACCENT = (255, 196, 64)
DANGER = (238, 92, 84)
OK_GREEN = (118, 216, 130)
PANEL_BG = (18, 22, 30)
OVERLAY = (10, 14, 22)
