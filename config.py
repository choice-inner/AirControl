from dataclasses import dataclass


@dataclass
class Config:
    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    detection_confidence: float = 0.7
    presence_confidence: float = 0.7
    tracking_confidence: float = 0.7
    max_hands: int = 1
    gesture_stable_frames: int = 3
    finger_min_angle: float = 155.0
    middle_finger_angle_hysteresis: float = 5.0
    middle_stable_frames: int = 2
    smoothing: float = 0.25
    cursor_jitter_deadzone_px: float = 4.0
    cursor_margin_x: float = 0.15
    cursor_margin_y: float = 0.15
    cursor_max_speed: float = 1.5
    # Dimensionless fingertip distance divided by wrist-to-middle-MCP distance.
    pinch_on_distance: float = 0.34
    pinch_off_distance: float = 0.42
    click_cooldown: float = 0.35
    click_max_duration: float = 0.8
    # The mapped screen position amplifies small camera/hand movements during a pinch.
    drag_start_distance_px: float = 48.0
    drag_move_epsilon_px: float = 1.0
    # Freeze short valid-hand release candidates during dragging; loss releases immediately.
    drag_release_grace_seconds: float = 0.12
    scroll_gain: float = 4.0
    # Stage 6 uses camera-frame pixels, independently of screen resolution.
    scroll_deadzone_px: float = 18.0
    scroll_step_px: float = 24.0
    scroll_max_steps_per_update: int = 5
    scroll_min_interval: float = 0.1
    scroll_max_sample_gap: float = 0.25
    # Independent stage 7 watchdog pauses input when camera/inference stops.
    control_frame_timeout: float = 0.75
