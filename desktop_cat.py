from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import math
import os
import queue
import random
import socket
import sys
import threading
import time
import tkinter as tk
import uuid
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlparse, urlunparse

from PIL import Image, ImageTk
import websocket
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


SPI_GETWORKAREA = 0x0030
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

OPENCLAW_CLIENT_ID = "openclaw-control-ui"
OPENCLAW_CLIENT_MODE = "webchat"
OPENCLAW_ROLE = "operator"
OPENCLAW_SCOPES = ("operator.admin", "operator.approvals", "operator.pairing")
OPENCLAW_CONTROL_UI_TABS = {
    "agents",
    "channels",
    "chat",
    "config",
    "cron",
    "debug",
    "instances",
    "logs",
    "nodes",
    "overview",
    "sessions",
    "skills",
    "usage",
}
OPENCLAW_DEVICE_IDENTITY_VERSION = 1
OPENCLAW_DEVICE_AUTH_VERSION = 1
DEFAULT_OPENCLAW_SESSION_KEY = "auto"
AUTO_OPENCLAW_SESSION_ALIASES = {"", "auto", "latest", "recent"}


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class PetConfig:
    sprite_path: Path
    emote_dir: Path | None = None
    coin_dir: Path | None = None
    state_path: Path | None = None
    runtime_path: Path | None = None
    session_state_path: Path | None = None
    openclaw_url: str = ""
    openclaw_token: str = ""
    openclaw_session_key: str = DEFAULT_OPENCLAW_SESSION_KEY
    device_identity_path: Path | None = None
    device_auth_path: Path | None = None
    frame_width: int = 32
    frame_height: int = 32
    scale: int = 4
    frame_delay_ms: int = 120
    margin: int = 8
    anchor_refresh_ms: int = 3000
    white_threshold: int = 240
    min_opaque_pixels: int = 8
    min_action_pause_ms: int = 250
    max_action_pause_ms: int = 1100
    frame_jitter_ms: int = 35
    range_width: int = 360
    range_padding: int = 18
    range_indicator_height: int = 22
    emote_scale: int = 1
    emote_gap: int = 2
    emote_frame_delay_ms: int = 180
    connected_emote_duration_ms: int = 3000
    task_complete_emote_duration_ms: int = 3000
    task_pounce_recover_ms: int = 180
    connection_poll_ms: int = 3000
    connection_timeout_ms: int = 1200
    coin_tick_ms: int = 60
    coin_frame_delay_ms: int = 120
    coin_spawn_min_ms: int = 1300
    coin_spawn_max_ms: int = 2600
    coin_max_count: int = 4
    coin_floor_gap: int = 6
    coin_hover_px: float = 2.5

    @property
    def pet_width(self) -> int:
        return self.frame_width * self.scale

    @property
    def pet_height(self) -> int:
        return self.frame_height * self.scale

    @property
    def emote_width(self) -> int:
        return self.frame_width * self.emote_scale

    @property
    def emote_height(self) -> int:
        return self.frame_height * self.emote_scale

    @property
    def window_width(self) -> int:
        return max(self.range_width, self.pet_width + self.range_padding * 2)

    @property
    def window_height(self) -> int:
        return self.emote_height + self.emote_gap + self.pet_height + self.range_indicator_height


@dataclass(frozen=True)
class ActionSpec:
    name: str
    role: str
    weight: float = 1.0
    speed_multiplier: float = 1.0
    move_step_multiplier: float = 0.0
    min_cycles: int = 1
    max_cycles: int = 1
    min_pause_ms: int = 250
    max_pause_ms: int = 1100
    min_hold_ms: int = 0
    max_hold_ms: int = 0
    ping_pong_chance: float = 0.0


@dataclass(frozen=True)
class OpenClawConnectionInfo:
    base_url: str = ""
    gateway_url: str = ""
    token: str = ""


@dataclass
class CoinState:
    kind: str
    item_id: int
    frames: list[ImageTk.PhotoImage]
    x: float
    y: float
    target_y: float
    fall_speed: float
    bob_phase: float
    bob_speed: float
    grounded: bool = False
    frame_index: int = 0
    frame_elapsed_ms: int = 0

    @property
    def width(self) -> int:
        return self.frames[0].width()

    @property
    def height(self) -> int:
        return self.frames[0].height()

    @property
    def image(self) -> ImageTk.PhotoImage:
        return self.frames[self.frame_index % len(self.frames)]


DEFAULT_ACTION_SPECS = [
    ActionSpec("idle_1", "idle", weight=1.15, min_cycles=5, max_cycles=9, min_pause_ms=70, max_pause_ms=180, ping_pong_chance=0.18),
    ActionSpec("idle_2", "idle", weight=1.0, min_cycles=5, max_cycles=8, min_pause_ms=70, max_pause_ms=180, ping_pong_chance=0.12),
    ActionSpec("idle_3", "idle", weight=1.0, min_cycles=4, max_cycles=8, min_pause_ms=70, max_pause_ms=180, ping_pong_chance=0.14),
    ActionSpec("idle_4", "idle", weight=0.9, min_cycles=4, max_cycles=7, min_pause_ms=70, max_pause_ms=180, ping_pong_chance=0.08),
    ActionSpec("wander", "walk", weight=1.0, speed_multiplier=1.0, move_step_multiplier=1.2, min_cycles=2, max_cycles=4, min_pause_ms=20, max_pause_ms=80, ping_pong_chance=0.08),
    ActionSpec("run", "run", weight=0.75, speed_multiplier=0.72, move_step_multiplier=2.3, min_cycles=2, max_cycles=3, min_pause_ms=10, max_pause_ms=60),
    ActionSpec("work", "work", weight=0.0, speed_multiplier=0.9, move_step_multiplier=1.75, min_cycles=2, max_cycles=4, min_pause_ms=0, max_pause_ms=20),
    ActionSpec("wander_2", "walk", weight=1.05, speed_multiplier=0.9, move_step_multiplier=1.35, min_cycles=3, max_cycles=6, min_pause_ms=5, max_pause_ms=40, ping_pong_chance=0.14),
    ActionSpec("pounce", "play", weight=0.9, speed_multiplier=0.86, move_step_multiplier=1.65, min_cycles=2, max_cycles=4, min_pause_ms=15, max_pause_ms=70, ping_pong_chance=0.0),
    ActionSpec("stretch", "stretch", weight=0.7, speed_multiplier=1.15, min_cycles=1, max_cycles=2, min_pause_ms=80, max_pause_ms=220),
]


ROLE_TRANSITIONS = {
    "idle": {"idle": 7.0, "walk": 2.4, "play": 1.6, "stretch": 1.1, "run": 0.25},
    "walk": {"idle": 3.0, "walk": 1.5, "play": 1.8, "run": 1.1, "stretch": 0.8},
    "run": {"walk": 3.6, "idle": 2.5, "play": 1.4, "stretch": 0.5, "run": 0.35},
    "play": {"idle": 2.8, "walk": 1.9, "play": 1.1, "stretch": 1.5, "run": 0.7},
    "stretch": {"idle": 4.8, "walk": 1.4, "play": 0.9},
    "work": {"idle": 1.0, "walk": 1.0, "run": 1.0},
}


def build_action_specs(action_count: int) -> list[ActionSpec]:
    specs = list(DEFAULT_ACTION_SPECS[:action_count])
    while len(specs) < action_count:
        specs.append(ActionSpec(f"idle_{len(specs) + 1}", "idle"))
    return specs


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_path(name: str) -> Path:
    return get_app_dir() / name


def load_session_state(session_state_path: Path | None) -> dict[str, str]:
    if session_state_path is None or not session_state_path.exists():
        return {}

    try:
        payload = json.loads(session_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    recent_session_key = str(payload.get("recent_session_key", "")).strip()
    active_session_key = str(payload.get("active_session_key", "")).strip()
    return {
        "recent_session_key": recent_session_key,
        "active_session_key": active_session_key,
    }


def save_session_state(
    session_state_path: Path | None,
    *,
    recent_session_key: str = "",
    active_session_key: str = "",
) -> None:
    if session_state_path is None:
        return

    payload: dict[str, str] = {}
    if recent_session_key.strip():
        payload["recent_session_key"] = recent_session_key.strip()
    if active_session_key.strip():
        payload["active_session_key"] = active_session_key.strip()

    try:
        if payload:
            session_state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        elif session_state_path.exists():
            session_state_path.unlink()
    except Exception:
        pass


def parse_args() -> argparse.Namespace:
    default_sprite = app_path("Cat Sprite Sheet.png")
    default_emote_dir = app_path("pipo-popupemotes Split images")
    default_coin_dir = app_path("Coin_Gems")
    parser = argparse.ArgumentParser(description="Pawly desktop pet for Windows")
    parser.add_argument("--sprite", type=Path, default=default_sprite)
    parser.add_argument("--emote-dir", type=Path, default=default_emote_dir)
    parser.add_argument("--coin-dir", type=Path, default=default_coin_dir)
    parser.add_argument("--openclaw-url", default=os.environ.get("OPENCLAW_URL", ""))
    parser.add_argument("--openclaw-token", default=os.environ.get("OPENCLAW_TOKEN", ""))
    parser.add_argument("--openclaw-session-key", default=os.environ.get("OPENCLAW_SESSION_KEY", DEFAULT_OPENCLAW_SESSION_KEY))
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--frame-width", type=int, default=32)
    parser.add_argument("--frame-height", type=int, default=32)
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--margin", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def get_work_area() -> RECT:
    rect = RECT()
    ok = user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if not ok:
        raise ctypes.WinError()
    return rect


def get_window_rect(hwnd: int) -> RECT | None:
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect


def find_tray_rect() -> RECT | None:
    taskbar_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not taskbar_hwnd:
        return None

    for class_name in ("TrayNotifyWnd", "ClockButton", "TrayClockWClass"):
        hwnd = user32.FindWindowExW(taskbar_hwnd, 0, class_name, None)
        if hwnd:
            rect = get_window_rect(hwnd)
            if rect:
                return rect

    rect = get_window_rect(taskbar_hwnd)
    if not rect:
        return None

    width = min(220, rect.width)
    return RECT(rect.right - width, rect.top, rect.right, rect.bottom)


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))


def position_above_tray(pet_width: int, pet_height: int, margin: int) -> tuple[int, int]:
    work_area = get_work_area()
    tray_rect = find_tray_rect()

    if tray_rect:
        x = tray_rect.left + (tray_rect.width - pet_width) // 2
        y = tray_rect.top - pet_height - margin
    else:
        x = work_area.right - pet_width - margin
        y = work_area.bottom - pet_height - margin

    x = clamp(x, work_area.left, work_area.right - pet_width)
    y = clamp(y, work_area.top, work_area.bottom - pet_height)
    return x, y


def clamp_window_position(
    window_width: int,
    window_height: int,
    x: int,
    y: int,
    *,
    visible_left: int = 0,
    visible_top: int = 0,
    visible_width: int | None = None,
    visible_height: int | None = None,
) -> tuple[int, int]:
    work_area = get_work_area()
    visible_width = window_width if visible_width is None else visible_width
    visible_height = window_height if visible_height is None else visible_height

    min_x = work_area.left - visible_left
    max_x = work_area.right - visible_left - visible_width
    min_y = work_area.top - visible_top
    max_y = work_area.bottom - visible_top - visible_height

    x = clamp(x, min_x, max_x)
    y = clamp(y, min_y, max_y)
    return x, y


def normalize_openclaw_url(openclaw_url: str) -> str:
    url = openclaw_url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"http://{url}"
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[-1].lower() in OPENCLAW_CONTROL_UI_TABS:
        path_parts = path_parts[:-1]
    normalized_path = "/" + "/".join(path_parts) if path_parts else ""
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", parsed.query, parsed.fragment))


def normalize_openclaw_session_key(session_key: str) -> str:
    normalized = session_key.strip()
    return "" if normalized.lower() in AUTO_OPENCLAW_SESSION_ALIASES else normalized


def extract_openclaw_token(openclaw_url: str) -> str:
    normalized = normalize_openclaw_url(openclaw_url)
    if not normalized:
        return ""

    parsed = urlparse(normalized)
    token_keys = {"token", "gatewayToken", "authToken"}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in token_keys and value.strip():
            return value.strip()
    for key, value in parse_qsl(parsed.fragment, keep_blank_values=True):
        if key in token_keys and value.strip():
            return value.strip()
    return ""


def build_openclaw_connection_info(openclaw_url: str, explicit_token: str = "") -> OpenClawConnectionInfo:
    normalized = normalize_openclaw_url(openclaw_url)
    if not normalized:
        return OpenClawConnectionInfo()

    parsed = urlparse(normalized)
    gateway_scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    gateway_path = parsed.path or "/"
    base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    gateway_url = urlunparse((gateway_scheme, parsed.netloc, gateway_path, "", "", ""))
    token = explicit_token.strip() or extract_openclaw_token(normalized)
    return OpenClawConnectionInfo(base_url=base_url, gateway_url=gateway_url, token=token)


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_or_create_device_identity(identity_path: Path) -> dict[str, str | int]:
    if identity_path.exists():
        try:
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            public_key = str(payload["publicKey"])
            private_key = str(payload["privateKey"])
            public_key_bytes = b64url_decode(public_key)
            device_id = sha256_hex(public_key_bytes)
            if str(payload.get("deviceId", "")).strip() != device_id:
                payload["deviceId"] = device_id
                identity_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "version": int(payload.get("version", OPENCLAW_DEVICE_IDENTITY_VERSION)),
                "deviceId": device_id,
                "publicKey": public_key,
                "privateKey": private_key,
            }
        except Exception:
            pass

    private_key_obj = Ed25519PrivateKey.generate()
    private_key_bytes = private_key_obj.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_key_bytes = private_key_obj.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    payload = {
        "version": OPENCLAW_DEVICE_IDENTITY_VERSION,
        "deviceId": sha256_hex(public_key_bytes),
        "publicKey": b64url_encode(public_key_bytes),
        "privateKey": b64url_encode(private_key_bytes),
        "createdAtMs": int(time.time() * 1000),
    }
    identity_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_device_auth_token(auth_path: Path | None, device_id: str, role: str) -> str:
    if auth_path is None or not auth_path.exists():
        return ""
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if str(payload.get("deviceId", "")) != device_id:
        return ""
    token_record = (payload.get("tokens") or {}).get(role, {})
    token = token_record.get("token")
    return token.strip() if isinstance(token, str) else ""


def save_device_auth_token(auth_path: Path | None, device_id: str, role: str, token: str, scopes: list[str]) -> None:
    if auth_path is None or not token.strip():
        return

    payload = {
        "version": OPENCLAW_DEVICE_AUTH_VERSION,
        "deviceId": device_id,
        "tokens": {},
    }
    if auth_path.exists():
        try:
            existing = json.loads(auth_path.read_text(encoding="utf-8"))
            if str(existing.get("deviceId", "")) == device_id and isinstance(existing.get("tokens"), dict):
                payload["tokens"] = dict(existing["tokens"])
        except Exception:
            pass

    payload["tokens"][role] = {
        "token": token.strip(),
        "role": role,
        "scopes": sorted({scope.strip() for scope in scopes if scope.strip()}),
        "updatedAtMs": int(time.time() * 1000),
    }
    auth_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_openclaw_connect_message(device_id: str, token: str, nonce: str, signed_at_ms: int) -> str:
    return "|".join(
        [
            "v2",
            device_id,
            OPENCLAW_CLIENT_ID,
            OPENCLAW_CLIENT_MODE,
            OPENCLAW_ROLE,
            ",".join(OPENCLAW_SCOPES),
            str(signed_at_ms),
            token,
            nonce,
        ]
    )


def build_openclaw_connect_payload(
    identity_path: Path,
    auth_path: Path | None,
    explicit_token: str,
    nonce: str,
    instance_id: str,
) -> tuple[dict, str, dict[str, str | int]]:
    identity = load_or_create_device_identity(identity_path)
    device_id = str(identity["deviceId"])
    token = load_device_auth_token(auth_path, device_id, OPENCLAW_ROLE) or explicit_token.strip()
    signed_at_ms = int(time.time() * 1000)
    signing_message = build_openclaw_connect_message(device_id, token, nonce, signed_at_ms)
    private_key_obj = Ed25519PrivateKey.from_private_bytes(b64url_decode(str(identity["privateKey"])))
    signature = private_key_obj.sign(signing_message.encode("utf-8"))
    payload = {
        "minProtocol": 3,
        "maxProtocol": 3,
        "client": {
            "id": OPENCLAW_CLIENT_ID,
            "version": "desktop-cat",
            "platform": sys.platform,
            "mode": OPENCLAW_CLIENT_MODE,
            "instanceId": instance_id,
        },
        "role": OPENCLAW_ROLE,
        "scopes": list(OPENCLAW_SCOPES),
        "device": {
            "id": device_id,
            "publicKey": str(identity["publicKey"]),
            "signature": b64url_encode(signature),
            "signedAt": signed_at_ms,
            "nonce": nonce,
        },
        "caps": [],
        "userAgent": "OpenClawCat/1.0",
        "locale": "zh-CN",
    }
    if token:
        payload["auth"] = {"token": token}
    return payload, token, identity


def probe_openclaw(openclaw_url: str, timeout_ms: int) -> bool:
    url = normalize_openclaw_url(openclaw_url)
    if not url:
        return False

    parsed = urlparse(url)
    if not parsed.hostname:
        return False

    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme in {"https", "wss"}:
        port = 443
    else:
        port = 80

    timeout_s = max(0.2, timeout_ms / 1000)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def transparentize_white(frame: Image.Image, white_threshold: int) -> tuple[Image.Image, int]:
    rgba = frame.convert("RGBA")
    pixels = []
    opaque_pixels = 0

    for red, green, blue, alpha in rgba.getdata():
        if red >= white_threshold and green >= white_threshold and blue >= white_threshold:
            pixels.append((0, 0, 0, 0))
        else:
            pixels.append((red, green, blue, alpha))
            opaque_pixels += 1

    rgba.putdata(pixels)
    return rgba, opaque_pixels


def extract_actions(config: PetConfig) -> list[list[Image.Image]]:
    sprite = Image.open(config.sprite_path).convert("RGBA")

    if sprite.width % config.frame_width != 0 or sprite.height % config.frame_height != 0:
        raise ValueError(
            f"Sprite size {sprite.width}x{sprite.height} is not divisible by "
            f"{config.frame_width}x{config.frame_height}."
        )

    columns = sprite.width // config.frame_width
    rows = sprite.height // config.frame_height
    actions: list[list[Image.Image]] = []

    for row in range(rows):
        frames: list[Image.Image] = []
        for col in range(columns):
            left = col * config.frame_width
            top = row * config.frame_height
            cell = sprite.crop((left, top, left + config.frame_width, top + config.frame_height))
            cell, opaque_pixels = transparentize_white(cell, config.white_threshold)
            if opaque_pixels >= config.min_opaque_pixels:
                frames.append(cell)
        if frames:
            actions.append(frames)

    if not actions:
        raise ValueError("No usable animation frames were found in the sprite sheet.")

    return actions


def load_emote_frames(emote_path: Path, scale: int) -> list[Image.Image]:
    sheet = Image.open(emote_path).convert("RGBA")
    if sheet.height <= 0 or sheet.width % sheet.height != 0:
        raise ValueError(f"Unexpected emote size for {emote_path.name}: {sheet.width}x{sheet.height}")

    frame_size = sheet.height
    frame_count = sheet.width // frame_size
    raw_frames: list[Image.Image] = []
    crop_box: tuple[int, int, int, int] | None = None
    for index in range(frame_count):
        frame = sheet.crop((index * frame_size, 0, (index + 1) * frame_size, frame_size))
        raw_frames.append(frame)
        bbox = frame.getbbox()
        if bbox is None:
            continue
        if crop_box is None:
            crop_box = bbox
            continue
        crop_box = (
            min(crop_box[0], bbox[0]),
            min(crop_box[1], bbox[1]),
            max(crop_box[2], bbox[2]),
            max(crop_box[3], bbox[3]),
        )

    if crop_box is None:
        crop_box = (0, 0, frame_size, frame_size)

    frames: list[Image.Image] = []
    for frame in raw_frames:
        cropped = frame.crop(crop_box)
        frames.append(cropped.resize((cropped.width * scale, cropped.height * scale), Image.Resampling.NEAREST))
    return frames


def load_emote_sets(config: PetConfig) -> dict[str, list[Image.Image]]:
    if config.emote_dir is None:
        raise ValueError("Emote directory is not configured.")

    disconnected_path = config.emote_dir / "pipo-popupemotes149.png"
    connected_path = config.emote_dir / "pipo-popupemotes100.png"
    task_complete_path = config.emote_dir / "pipo-popupemotes080.png"
    return {
        "disconnected": load_emote_frames(disconnected_path, config.emote_scale),
        "connected": load_emote_frames(connected_path, config.emote_scale),
        "task_complete": load_emote_frames(task_complete_path, config.emote_scale),
    }


def resize_to_fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    if image.width <= 0 or image.height <= 0:
        return image
    scale = min(max_width / image.width, max_height / image.height)
    resized_width = max(1, round(image.width * scale))
    resized_height = max(1, round(image.height * scale))
    return image.resize((resized_width, resized_height), Image.Resampling.NEAREST)


def load_coin_frames(coin_path: Path, target_width: int, target_height: int) -> list[Image.Image]:
    sheet = Image.open(coin_path).convert("RGBA")
    if sheet.height <= 0 or sheet.width % sheet.height != 0:
        raise ValueError(f"Unexpected coin size for {coin_path.name}: {sheet.width}x{sheet.height}")

    frame_size = sheet.height
    frame_count = sheet.width // frame_size
    frames: list[Image.Image] = []
    for index in range(frame_count):
        frame = sheet.crop((index * frame_size, 0, (index + 1) * frame_size, frame_size))
        bbox = frame.getbbox() or (0, 0, frame.width, frame.height)
        cropped = frame.crop(bbox)
        frames.append(resize_to_fit(cropped, target_width, target_height))
    return frames


def load_coin_sets(config: PetConfig, target_width: int, target_height: int) -> dict[str, list[Image.Image]]:
    if config.coin_dir is None:
        raise ValueError("Coin directory is not configured.")
    return {
        "gold": load_coin_frames(config.coin_dir / "MonedaD.png", target_width, target_height),
        "silver": load_coin_frames(config.coin_dir / "MonedaP.png", target_width, target_height),
        "red": load_coin_frames(config.coin_dir / "MonedaR.png", target_width, target_height),
    }


def build_tk_actions(
    root: tk.Tk, actions: list[list[Image.Image]], scale: int
) -> tuple[list[list[ImageTk.PhotoImage]], list[list[ImageTk.PhotoImage]]]:
    root.update_idletasks()
    tk_actions: list[list[ImageTk.PhotoImage]] = []
    flipped_actions: list[list[ImageTk.PhotoImage]] = []
    for action in actions:
        tk_frames: list[ImageTk.PhotoImage] = []
        flipped_frames: list[ImageTk.PhotoImage] = []
        for frame in action:
            scaled = frame.resize((frame.width * scale, frame.height * scale), Image.Resampling.NEAREST)
            tk_frames.append(ImageTk.PhotoImage(scaled))
            flipped = scaled.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            flipped_frames.append(ImageTk.PhotoImage(flipped))
        tk_actions.append(tk_frames)
        flipped_actions.append(flipped_frames)
    return tk_actions, flipped_actions


def build_tk_image_sequences(
    root: tk.Tk, image_sequences: dict[str, list[Image.Image]]
) -> dict[str, list[ImageTk.PhotoImage]]:
    root.update_idletasks()
    return {
        key: [ImageTk.PhotoImage(image) for image in frames]
        for key, frames in image_sequences.items()
    }



def extract_message_role(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    role = message.get("role")
    return role.strip().lower() if isinstance(role, str) else ""


class OpenClawGatewayMonitor:
    def __init__(
        self,
        config: PetConfig,
        status_queue: queue.Queue[dict],
        stop_event: threading.Event,
    ) -> None:
        self.config = config
        self.status_queue = status_queue
        self.stop_event = stop_event
        self.connection_info = build_openclaw_connection_info(config.openclaw_url, config.openclaw_token)
        self.instance_id = f"desktop-cat-{uuid.uuid4()}"
        self.last_connected: bool | None = None
        self.last_task_active: bool | None = None
        self.preferred_session_key = normalize_openclaw_session_key(config.openclaw_session_key)
        self.auto_session_mode = not bool(self.preferred_session_key)
        session_state = load_session_state(config.session_state_path) if self.auto_session_mode else {}
        self.main_session_key = "main"
        self.main_key = "main"
        self.default_agent_id = ""
        self.recent_session_key = self.preferred_session_key or str(session_state.get("recent_session_key", "")).strip()
        self.active_session_key = (
            self.preferred_session_key
            or str(session_state.get("active_session_key", "")).strip()
            or self.recent_session_key
        )
        self.target_session_keys: set[str] = set()
        self.refresh_target_session_keys()

    def emit(self, payload: dict) -> None:
        self.status_queue.put(payload)

    def emit_connection(self, connected: bool) -> None:
        if connected == self.last_connected:
            return
        self.last_connected = connected
        self.emit({"type": "connection", "connected": connected})

    def emit_task(self, active: bool) -> None:
        if active == self.last_task_active:
            return
        self.last_task_active = active
        self.emit({"type": "task", "active": active})

    def emit_pairing(self, required: bool, message: str = "", code: str = "") -> None:
        self.emit(
            {
                "type": "pairing",
                "required": required,
                "message": message.strip(),
                "code": code.strip(),
            }
        )

    def send_request(self, ws: websocket.WebSocket, method: str, params: dict) -> str:
        request_id = str(uuid.uuid4())
        ws.send(json.dumps({"type": "req", "id": request_id, "method": method, "params": params}))
        return request_id

    def refresh_target_session_keys(self) -> None:
        if self.preferred_session_key:
            self.target_session_keys = {self.preferred_session_key}
            return
        keys = set()
        if self.active_session_key.strip():
            keys.add(self.active_session_key.strip())
        if self.recent_session_key.strip():
            keys.add(self.recent_session_key.strip())
        self.target_session_keys = keys

    def persist_session_state(self) -> None:
        if not self.auto_session_mode:
            return
        save_session_state(
            self.config.session_state_path,
            recent_session_key=self.recent_session_key,
            active_session_key=self.active_session_key,
        )

    def get_history_session_key(self) -> str:
        return self.preferred_session_key or self.active_session_key or self.recent_session_key or ""

    def matches_target_session(self, session_key: str) -> bool:
        normalized = session_key.strip()
        if not normalized or not self.target_session_keys:
            return True
        return normalized in self.target_session_keys

    def initialize_task_state_from_history(self, payload: dict, session_key: str = "") -> bool:
        messages = payload.get("messages") if isinstance(payload, dict) else None
        last_role = ""
        if isinstance(messages, list):
            for message in reversed(messages):
                last_role = extract_message_role(message)
                if last_role:
                    break
        active = bool(last_role and last_role != "assistant")
        if self.auto_session_mode:
            history_session_key = session_key.strip() or self.get_history_session_key().strip()
            if history_session_key:
                self.recent_session_key = history_session_key
            self.active_session_key = history_session_key if active else ""
            self.refresh_target_session_keys()
            self.persist_session_state()
        self.emit_task(active)
        return active

    def get_history_probe_session_key(self, payload: dict, task_active: bool) -> str:
        if not self.auto_session_mode or task_active or not isinstance(payload, dict):
            return ""

        session_key = str(payload.get("sessionKey", "")).strip()
        if not session_key:
            return ""

        state = str(payload.get("state", "")).strip().lower()
        role = extract_message_role(payload.get("message"))
        has_run_id = isinstance(payload.get("runId"), str) and bool(str(payload.get("runId")).strip())
        progress_signal = bool(
            state in {"queued", "started", "running", "reading", "delta"}
            or (has_run_id and state not in {"", "final", "error", "aborted"})
        )

        if role in {"user", "human", "operator"}:
            return ""
        if not progress_signal:
            return ""
        return session_key

    def process_chat_event(self, payload: dict, task_active: bool) -> bool:
        if not isinstance(payload, dict):
            return task_active

        session_key = str(payload.get("sessionKey", "")).strip()
        effective_session_key = session_key or self.active_session_key
        state = str(payload.get("state", "")).strip().lower()
        role = extract_message_role(payload.get("message"))
        has_run_id = isinstance(payload.get("runId"), str) and bool(str(payload.get("runId")).strip())
        is_assistant = role == "assistant"
        trigger_roles = {"user", "human", "operator"}
        user_start_signal = bool(effective_session_key) and role in trigger_roles
        progress_signal = bool(state in {"queued", "started", "running", "reading", "delta"} or (has_run_id and state not in {"", "final", "error", "aborted"}))

        if self.preferred_session_key:
            if session_key and not self.matches_target_session(session_key):
                return task_active
        else:
            if session_key:
                self.recent_session_key = session_key
                self.persist_session_state()

            if user_start_signal:
                self.active_session_key = effective_session_key
                self.refresh_target_session_keys()
                self.persist_session_state()
            elif session_key and self.active_session_key and session_key != self.active_session_key:
                return task_active
            elif not effective_session_key:
                return task_active

        if user_start_signal:
            if not task_active:
                self.emit_task(True)
            return True

        if state == "final":
            if is_assistant:
                if self.auto_session_mode:
                    self.active_session_key = ""
                    self.refresh_target_session_keys()
                    self.persist_session_state()
                if task_active:
                    self.emit_task(False)
                return False
            return task_active

        if state in {"error", "aborted"}:
            if self.auto_session_mode:
                self.active_session_key = ""
                self.refresh_target_session_keys()
                self.persist_session_state()
            if task_active:
                self.emit_task(False)
            return False

        if task_active and progress_signal:
            return True

        return task_active

    def connect_once(self) -> None:
        if not self.connection_info.gateway_url:
            self.emit_connection(False)
            self.emit_task(False)
            self.stop_event.wait(max(0.5, self.config.connection_poll_ms / 1000))
            return

        ws = websocket.create_connection(
            self.connection_info.gateway_url,
            timeout=max(1.0, self.config.connection_timeout_ms / 1000),
            enable_multithread=True,
        )
        ws.settimeout(1.0)
        connect_sent = False
        connect_nonce = ""
        connect_deadline = time.monotonic() + 0.75
        pending_requests: dict[str, str] = {}
        history_probe_cooldowns: dict[str, float] = {}
        task_active = False
        identity: dict[str, str | int] | None = None

        try:
            while not self.stop_event.is_set():
                if not connect_sent and time.monotonic() >= connect_deadline:
                    if self.config.device_identity_path is None:
                        raise RuntimeError("device identity path is not configured")
                    payload, _token, identity = build_openclaw_connect_payload(
                        self.config.device_identity_path,
                        self.config.device_auth_path,
                        self.connection_info.token,
                        connect_nonce,
                        self.instance_id,
                    )
                    request_id = self.send_request(ws, "connect", payload)
                    pending_requests[request_id] = "connect"
                    connect_sent = True

                try:
                    raw_message = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException as exc:
                    raise RuntimeError("gateway connection closed") from exc

                if raw_message is None:
                    continue

                try:
                    message = json.loads(raw_message)
                except Exception:
                    continue

                if message.get("type") == "event":
                    event_name = str(message.get("event", "")).strip()
                    if event_name == "connect.challenge" and not connect_sent:
                        challenge_payload = message.get("payload") or {}
                        nonce = challenge_payload.get("nonce")
                        connect_nonce = nonce.strip() if isinstance(nonce, str) else ""
                        if self.config.device_identity_path is None:
                            raise RuntimeError("device identity path is not configured")
                        payload, _token, identity = build_openclaw_connect_payload(
                            self.config.device_identity_path,
                            self.config.device_auth_path,
                            self.connection_info.token,
                            connect_nonce,
                            self.instance_id,
                        )
                        request_id = self.send_request(ws, "connect", payload)
                        pending_requests[request_id] = "connect"
                        connect_sent = True
                        continue

                    if event_name == "chat":
                        event_payload = message.get("payload") or {}
                        probe_session_key = self.get_history_probe_session_key(event_payload, task_active)
                        if probe_session_key:
                            now = time.monotonic()
                            if history_probe_cooldowns.get(probe_session_key, 0.0) <= now:
                                history_request_id = self.send_request(
                                    ws,
                                    "chat.history",
                                    {"sessionKey": probe_session_key, "limit": 12},
                                )
                                pending_requests[history_request_id] = f"history:{probe_session_key}"
                                history_probe_cooldowns[probe_session_key] = now + 1.5
                        task_active = self.process_chat_event(event_payload, task_active)
                    continue

                if message.get("type") != "res":
                    continue

                request_id = str(message.get("id", ""))
                request_kind = pending_requests.pop(request_id, "")
                if not request_kind:
                    continue

                if not message.get("ok"):
                    error = message.get("error") or {}
                    error_code = str(error.get("code") or "").strip()
                    error_message = str(error.get("message") or error_code or "request failed").strip()
                    normalized_error = f"{error_code} {error_message}".lower()
                    pairing_required = "pairing-required" in normalized_error or "not-paired" in normalized_error
                    self.emit_pairing(pairing_required, error_message, error_code)
                    raise RuntimeError(str(error_message))

                payload = message.get("payload") or {}
                if request_kind == "connect":
                    snapshot = payload.get("snapshot") or {}
                    session_defaults = snapshot.get("sessionDefaults") or {}
                    main_session_key = session_defaults.get("mainSessionKey")
                    main_key = session_defaults.get("mainKey")
                    default_agent_id = session_defaults.get("defaultAgentId")
                    if isinstance(main_session_key, str) and main_session_key.strip():
                        self.main_session_key = main_session_key.strip()
                    if isinstance(main_key, str) and main_key.strip():
                        self.main_key = main_key.strip()
                    if isinstance(default_agent_id, str) and default_agent_id.strip():
                        self.default_agent_id = default_agent_id.strip()
                    self.refresh_target_session_keys()

                    auth_payload = payload.get("auth") or {}
                    device_token = auth_payload.get("deviceToken")
                    auth_role = auth_payload.get("role") if isinstance(auth_payload.get("role"), str) else OPENCLAW_ROLE
                    auth_scopes = auth_payload.get("scopes") if isinstance(auth_payload.get("scopes"), list) else list(OPENCLAW_SCOPES)
                    if isinstance(device_token, str) and device_token.strip() and identity is not None:
                        save_device_auth_token(
                            self.config.device_auth_path,
                            str(identity["deviceId"]),
                            auth_role,
                            device_token,
                            [str(scope) for scope in auth_scopes],
                        )

                    self.emit_pairing(False)
                    self.emit_connection(True)
                    history_session_key = self.get_history_session_key()
                    if history_session_key:
                        history_request_id = self.send_request(ws, "chat.history", {"sessionKey": history_session_key, "limit": 60})
                        pending_requests[history_request_id] = f"history:{history_session_key}"
                    else:
                        self.emit_task(False)
                    continue

                if request_kind.startswith("history:"):
                    history_session_key = request_kind.partition(":")[2].strip()
                    task_active = self.initialize_task_state_from_history(payload, history_session_key)
        finally:
            try:
                ws.close()
            except Exception:
                pass
            self.active_session_key = self.preferred_session_key or ""
            self.refresh_target_session_keys()
            self.persist_session_state()
            self.emit_connection(False)
            self.emit_task(False)

    def run(self) -> None:
        backoff_seconds = 0.8
        while not self.stop_event.is_set():
            try:
                self.connect_once()
                backoff_seconds = 0.8
            except Exception as exc:
                normalized_error = str(exc).strip().lower()
                if "pairing-required" not in normalized_error and "not-paired" not in normalized_error:
                    self.emit_pairing(False)
                self.emit_connection(False)
                self.emit_task(False)
            if self.stop_event.wait(backoff_seconds):
                break
            backoff_seconds = min(backoff_seconds * 1.7, 15.0)


class DesktopCat:
    def __init__(self, root: tk.Tk, config: PetConfig, action_images: list[list[Image.Image]]):
        self.root = root
        self.config = config
        self.action_bounds = [
            [frame.getbbox() or (0, 0, frame.width, frame.height) for frame in action]
            for action in action_images
        ]
        self.actions, self.flipped_actions = build_tk_actions(root, action_images, config.scale)
        self.emote_images = build_tk_image_sequences(root, load_emote_sets(config))
        self.window_width = config.window_width
        self.max_emote_width = max(frame.width() for frames in self.emote_images.values() for frame in frames)
        self.max_emote_height = max(frame.height() for frames in self.emote_images.values() for frame in frames)
        self.coin_images = (
            build_tk_image_sequences(root, load_coin_sets(config, self.max_emote_width, self.max_emote_height))
            if config.coin_dir is not None
            else {}
        )
        self.max_coin_width = max((frame.width() for frames in self.coin_images.values() for frame in frames), default=self.max_emote_width)
        self.max_coin_height = max((frame.height() for frames in self.coin_images.values() for frame in frames), default=self.max_emote_height)
        self.window_height = self.max_emote_height + config.emote_gap + config.pet_height + config.range_indicator_height
        self.action_specs = build_action_specs(len(self.actions))
        self.task_move_action_index = 4 if len(self.actions) > 4 else 0
        self.work_action_index = 8 if len(self.actions) > 8 else max(0, len(self.actions) - 1)
        self.disconnected_action_index = 6 if len(self.actions) > 6 else self.work_action_index
        self.stretch_action_index = next((index for index, spec in enumerate(self.action_specs) if spec.role == "stretch"), max(0, len(self.actions) - 1))
        self.current_action_index = self.disconnected_action_index
        self.current_role = self.action_specs[self.current_action_index].role if self.action_specs else "idle"
        self.current_frame_index = 0
        self.current_frame_order: list[int] = [0]
        self.current_frame_delay_ms = config.frame_delay_ms
        self.current_hold_ms = 0
        self.current_emote_key = "disconnected"
        self.current_emote_index = 0
        self.current_emote_visible = True
        self.connection_state = False
        self.task_active = False
        self.pairing_required = False
        self.pairing_error = ""
        self.wakeup_after_connect = False
        self.animation_after_id: str | None = None
        self.transition_after_id: str | None = None
        self.emote_after_id: str | None = None
        self.emote_hide_after_id: str | None = None
        self.connection_process_after_id: str | None = None
        self.coin_after_id: str | None = None
        self.connection_queue: queue.Queue[dict] = queue.Queue()
        self.connection_stop_event = threading.Event()
        self.connection_thread: threading.Thread | None = None
        self.coins: list[CoinState] = []
        self.next_coin_spawn_at = 0.0
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.drag_enabled = False
        self.dragged = False
        self.docked = True
        self.window_x = 0
        self.window_y = 0
        self.recent_actions = deque(maxlen=min(4, max(1, len(self.actions) - 2)))
        self.direction = random.choice([-1, 1])
        self.pet_x = (self.window_width - config.pet_width) / 2
        self.pet_y = self.max_emote_height + config.emote_gap
        self.min_pet_x = config.range_padding
        self.max_pet_x = self.window_width - config.range_padding - config.pet_width
        self.range_top = 4
        self.range_bottom = self.pet_y + config.pet_height + 8
        self.ground_y = self.window_height - config.range_indicator_height // 2

        self.bg_key = "#00ff00"
        self.root.configure(bg=self.bg_key)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", self.bg_key)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Redock", command=self.redock)
        self.menu.add_command(label="Random Action", command=self.choose_next_action)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.close)

        self.canvas = tk.Canvas(
            self.root,
            width=self.window_width,
            height=self.window_height,
            bg=self.bg_key,
            borderwidth=0,
            highlightthickness=0,
        )
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_end)
        self.canvas.bind("<Button-3>", self.show_menu)
        self.draw_movement_range()
        self.emote_item = self.canvas.create_image(0, 0, anchor="nw")
        self.pet_item = self.canvas.create_image(self.pet_x, self.pet_y, anchor="nw")

        self.apply_toolwindow_style()
        self.write_runtime_state()
        self.set_emote_state(False)
        self.choose_next_action(first_pick=True)
        saved_position = self.load_saved_position()
        if saved_position is None:
            self.redock()
        else:
            self.pin_window(*saved_position, persist=False)
        self.start_connection_monitor()
        self.process_connection_updates()
        self.start_emote_animation()
        self.tick_coins()
        self.tick_animation()
        self.refresh_anchor()

    def draw_movement_range(self) -> None:
        return

    def close(self) -> None:
        if not self.docked:
            self.save_position()
        self.cancel_scheduled_callbacks()
        self.connection_stop_event.set()
        self.clear_runtime_state()
        self.root.destroy()

    def apply_toolwindow_style(self) -> None:
        hwnd = self.root.winfo_id()
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex_style = (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)

    def write_runtime_state(self) -> None:
        if self.config.runtime_path is None:
            return
        payload = {
            "pid": os.getpid(),
            "pairingRequired": self.pairing_required,
            "pairingError": self.pairing_error,
        }
        self.config.runtime_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear_runtime_state(self) -> None:
        if self.config.runtime_path is None or not self.config.runtime_path.exists():
            return
        try:
            data = json.loads(self.config.runtime_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if data.get("pid") in (None, os.getpid()):
            self.config.runtime_path.unlink(missing_ok=True)

    def cancel_scheduled_callbacks(self) -> None:
        for callback_id in (
            self.animation_after_id,
            self.transition_after_id,
            self.emote_after_id,
            self.emote_hide_after_id,
            self.connection_process_after_id,
            self.coin_after_id,
        ):
            if callback_id:
                try:
                    self.root.after_cancel(callback_id)
                except Exception:
                    pass
        self.animation_after_id = None
        self.transition_after_id = None
        self.emote_after_id = None
        self.emote_hide_after_id = None
        self.connection_process_after_id = None
        self.coin_after_id = None

    def cancel_emote_hide_callback(self) -> None:
        if self.emote_hide_after_id:
            try:
                self.root.after_cancel(self.emote_hide_after_id)
            except Exception:
                pass
            self.emote_hide_after_id = None

    def restore_default_emote(self) -> None:
        self.emote_hide_after_id = None
        self.current_emote_key = "connected" if self.connection_state else "disconnected"
        self.current_emote_index = 0
        self.current_emote_visible = not self.connection_state
        self.draw_current_emote()

    def set_emote_state(self, connected: bool) -> None:
        self.cancel_emote_hide_callback()
        self.current_emote_key = "connected" if connected else "disconnected"
        self.current_emote_index = 0
        self.current_emote_visible = True
        if connected:
            self.emote_hide_after_id = self.root.after(
                self.config.connected_emote_duration_ms,
                self.restore_default_emote,
            )
        self.draw_current_emote()

    def show_temporary_emote(self, emote_key: str, duration_ms: int) -> None:
        if emote_key not in self.emote_images:
            return
        self.cancel_emote_hide_callback()
        self.current_emote_key = emote_key
        self.current_emote_index = 0
        self.current_emote_visible = True
        self.draw_current_emote()
        self.emote_hide_after_id = self.root.after(duration_ms, self.restore_default_emote)

    def get_current_emote_position(self) -> tuple[int, int]:
        emote_frames = self.emote_images[self.current_emote_key]
        emote_frame = emote_frames[self.current_emote_index % len(emote_frames)]
        frame_order_index = min(self.current_frame_index, len(self.current_frame_order) - 1)
        cat_frame_index = self.current_frame_order[frame_order_index]
        bounds = self.action_bounds[self.current_action_index][cat_frame_index]
        visible_left = self.pet_x + bounds[0] * self.config.scale
        visible_top = self.pet_y + bounds[1] * self.config.scale
        visible_width = (bounds[2] - bounds[0]) * self.config.scale
        emote_x = round(visible_left + (visible_width - emote_frame.width()) / 2)
        emote_y = round(visible_top - emote_frame.height() + 2)
        return emote_x, emote_y

    def start_emote_animation(self) -> None:
        self.draw_current_emote()
        self.emote_after_id = self.root.after(self.config.emote_frame_delay_ms, self.advance_emote_animation)

    def draw_current_emote(self) -> None:
        if not self.current_emote_visible:
            self.canvas.itemconfigure(self.emote_item, image="")
            return

        frames = self.emote_images[self.current_emote_key]
        frame = frames[self.current_emote_index % len(frames)]
        emote_x, emote_y = self.get_current_emote_position()
        emote_y = max(0, emote_y)
        self.canvas.itemconfigure(self.emote_item, image=frame)
        self.canvas.coords(self.emote_item, emote_x, emote_y)

    def advance_emote_animation(self) -> None:
        frames = self.emote_images[self.current_emote_key]
        self.current_emote_index = (self.current_emote_index + 1) % len(frames)
        self.draw_current_emote()
        self.emote_after_id = self.root.after(self.config.emote_frame_delay_ms, self.advance_emote_animation)

    def start_connection_monitor(self) -> None:
        monitor = OpenClawGatewayMonitor(self.config, self.connection_queue, self.connection_stop_event)
        self.connection_thread = threading.Thread(target=monitor.run, daemon=True)
        self.connection_thread.start()

    def process_connection_updates(self) -> None:
        updates: list[dict] = []
        while True:
            try:
                updates.append(self.connection_queue.get_nowait())
            except queue.Empty:
                break

        for update in updates:
            update_type = update.get("type")
            if update_type == "connection":
                connected = bool(update.get("connected"))
                if connected != self.connection_state:
                    self.apply_connection_state(connected)
                continue
            if update_type == "pairing":
                self.apply_pairing_state(
                    bool(update.get("required")),
                    str(update.get("message") or "").strip(),
                )
                continue
            if update_type == "task":
                active = bool(update.get("active"))
                if active != self.task_active:
                    self.apply_task_state(active)

        self.connection_process_after_id = self.root.after(100, self.process_connection_updates)

    def apply_connection_state(self, connected: bool) -> None:
        self.connection_state = connected
        if connected:
            self.pairing_required = False
            self.pairing_error = ""
        self.set_emote_state(connected)
        self.write_runtime_state()
        if connected:
            self.wakeup_after_connect = False
            if self.task_active:
                self.force_action_index(self.get_task_action_index(self.get_target_coin()))
            else:
                self.force_action_index(self.stretch_action_index)
            return

        self.wakeup_after_connect = False
        self.apply_task_state(False)
        self.force_action_index(self.disconnected_action_index)

    def apply_task_state(self, active: bool) -> None:
        active = bool(active and self.connection_state)
        if active == self.task_active:
            if not active:
                self.clear_coins()
            return

        self.task_active = active
        if active:
            self.restore_default_emote()
            self.seed_task_coins()
            self.force_action_index(self.get_task_action_index(self.get_target_coin()))
            return

        self.clear_coins()
        if self.connection_state:
            self.cancel_animation_callbacks()
            self.choose_next_action()
            self.tick_animation()
            self.show_temporary_emote("task_complete", self.config.task_complete_emote_duration_ms)

    def apply_pairing_state(self, required: bool, message: str = "") -> None:
        self.pairing_required = required
        self.pairing_error = message if required else ""
        self.write_runtime_state()

    def cancel_animation_callbacks(self) -> None:
        for callback_id_attr in ("animation_after_id", "transition_after_id"):
            callback_id = getattr(self, callback_id_attr)
            if callback_id:
                try:
                    self.root.after_cancel(callback_id)
                except Exception:
                    pass
                setattr(self, callback_id_attr, None)

    def force_action_index(self, action_index: int) -> None:
        if not self.actions:
            return
        action_index = max(0, min(action_index, len(self.actions) - 1))
        self.cancel_animation_callbacks()
        self.activate_action(action_index)
        self.tick_animation()

    def load_saved_position(self) -> tuple[int, int] | None:
        if self.config.state_path is None or not self.config.state_path.exists():
            return None

        try:
            data = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            x = int(data["x"])
            y = int(data["y"])
        except Exception:
            return None

        return clamp_window_position(
            self.window_width,
            self.window_height,
            x,
            y,
            visible_left=round(self.pet_x),
            visible_top=self.pet_y,
            visible_width=self.config.pet_width,
            visible_height=self.config.pet_height,
        )

    def save_position(self) -> None:
        if self.config.state_path is None:
            return

        x, y = clamp_window_position(
            self.window_width,
            self.window_height,
            self.window_x,
            self.window_y,
            visible_left=round(self.pet_x),
            visible_top=self.pet_y,
            visible_width=self.config.pet_width,
            visible_height=self.config.pet_height,
        )
        payload = {"x": x, "y": y}
        self.config.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear_saved_position(self) -> None:
        if self.config.state_path is None:
            return
        if self.config.state_path.exists():
            self.config.state_path.unlink()

    def move_window(self, x: int, y: int) -> tuple[int, int]:
        x, y = clamp_window_position(
            self.window_width,
            self.window_height,
            x,
            y,
            visible_left=round(self.pet_x),
            visible_top=self.pet_y,
            visible_width=self.config.pet_width,
            visible_height=self.config.pet_height,
        )
        self.window_x = x
        self.window_y = y
        self.root.geometry(f"{self.window_width}x{self.window_height}+{x}+{y}")
        return x, y

    def pin_window(self, x: int, y: int, persist: bool = True) -> None:
        self.docked = False
        self.move_window(x, y)
        if persist:
            self.save_position()

    def pointer_on_pet(self, event: tk.Event) -> bool:
        within_cat_x = self.pet_x <= event.x <= self.pet_x + self.config.pet_width
        within_cat_y = self.pet_y <= event.y <= self.pet_y + self.config.pet_height
        if within_cat_x and within_cat_y:
            return True

        if not self.current_emote_visible:
            return False

        frames = self.emote_images[self.current_emote_key]
        frame = frames[self.current_emote_index % len(frames)]
        emote_x, emote_y = self.get_current_emote_position()
        emote_y = max(0, emote_y)
        within_emote_x = emote_x <= event.x <= emote_x + frame.width()
        within_emote_y = emote_y <= event.y <= emote_y + frame.height()
        return within_emote_x and within_emote_y

    def clear_coins(self) -> None:
        for coin in self.coins:
            self.canvas.delete(coin.item_id)
        self.coins.clear()

    def schedule_next_coin_spawn(self, immediate: bool = False) -> None:
        if immediate:
            self.next_coin_spawn_at = time.monotonic()
            return
        delay_ms = random.randint(self.config.coin_spawn_min_ms, self.config.coin_spawn_max_ms)
        self.next_coin_spawn_at = time.monotonic() + delay_ms / 1000

    def seed_task_coins(self) -> None:
        self.clear_coins()
        if not self.coin_images:
            return
        for _ in range(min(2, self.config.coin_max_count)):
            self.spawn_coin(initial=True)
        self.schedule_next_coin_spawn()

    def get_coin_spawn_bounds(self, coin_width: int) -> tuple[int, int]:
        collectible_frames = [index for index in (2, 3) if index < len(self.action_bounds[self.work_action_index])]
        if not collectible_frames:
            min_x = self.min_pet_x
            max_x = self.max_pet_x + self.config.pet_width - coin_width
            return round(min_x), round(max(min_x, max_x))

        bounds = [self.action_bounds[self.work_action_index][index] for index in collectible_frames]
        left_reach = min(bound[0] for bound in bounds) * self.config.scale
        right_reach = max(bound[2] for bound in bounds) * self.config.scale
        lunge_margin = max(coin_width * 0.35, self.config.scale * 5)

        min_x = self.min_pet_x + left_reach - lunge_margin
        max_x = self.max_pet_x + right_reach - coin_width + lunge_margin

        min_x = clamp(round(min_x), 0, max(0, self.window_width - coin_width))
        max_x = clamp(round(max_x), min_x, max(0, self.window_width - coin_width))
        return min_x, max_x

    def spawn_coin(self, initial: bool = False) -> None:
        if not self.coin_images or len(self.coins) >= self.config.coin_max_count:
            return

        kind = random.choices(["gold", "silver", "red"], weights=[0.58, 0.29, 0.13], k=1)[0]
        frames = self.coin_images[kind]
        coin_width = frames[0].width()
        coin_height = frames[0].height()
        min_x, max_x = self.get_coin_spawn_bounds(coin_width)
        x = random.randint(min_x, max_x)
        target_y = self.window_height - self.config.range_indicator_height - coin_height - self.config.coin_floor_gap
        start_y = -coin_height - random.randint(0, self.max_emote_height + 18)
        if initial:
            start_y -= random.randint(0, self.max_emote_height + 24)

        item_id = self.canvas.create_image(x, start_y, image=frames[0], anchor="nw")
        self.canvas.tag_lower(item_id, self.pet_item)
        self.coins.append(
            CoinState(
                kind=kind,
                item_id=item_id,
                frames=frames,
                x=float(x),
                y=float(start_y),
                target_y=float(target_y),
                fall_speed=random.uniform(5.2, 7.4),
                bob_phase=random.uniform(0.0, math.tau),
                bob_speed=random.uniform(0.16, 0.28),
            )
        )

    def tick_coins(self) -> None:
        self.coin_after_id = None

        if self.task_active and self.connection_state and self.coin_images:
            if len(self.coins) < self.config.coin_max_count and time.monotonic() >= self.next_coin_spawn_at:
                self.spawn_coin()
                self.schedule_next_coin_spawn()
        elif self.coins and not self.task_active:
            self.clear_coins()

        for coin in list(self.coins):
            coin.frame_elapsed_ms += self.config.coin_tick_ms
            while coin.frame_elapsed_ms >= self.config.coin_frame_delay_ms:
                coin.frame_elapsed_ms -= self.config.coin_frame_delay_ms
                coin.frame_index = (coin.frame_index + 1) % len(coin.frames)

            if not coin.grounded:
                coin.y += coin.fall_speed
                coin.fall_speed = min(12.0, coin.fall_speed + 0.55)
                if coin.y >= coin.target_y:
                    coin.y = coin.target_y
                    coin.grounded = True
            else:
                coin.bob_phase += coin.bob_speed
                coin.y = coin.target_y + math.sin(coin.bob_phase) * self.config.coin_hover_px

            self.canvas.itemconfigure(coin.item_id, image=coin.image)
            self.canvas.coords(coin.item_id, round(coin.x), round(coin.y))

        self.collect_overlapping_coins()
        self.coin_after_id = self.root.after(self.config.coin_tick_ms, self.tick_coins)

    def get_current_source_frame_index(self) -> int:
        if not self.current_frame_order:
            return 0
        frame_order_index = min(self.current_frame_index, max(0, len(self.current_frame_order) - 1))
        return self.current_frame_order[frame_order_index]

    def get_pet_hitbox(self) -> tuple[float, float, float, float]:
        if not self.actions:
            return self.pet_x, self.pet_y, self.pet_x + self.config.pet_width, self.pet_y + self.config.pet_height
        frame_index = self.get_current_source_frame_index()
        bounds = self.action_bounds[self.current_action_index][frame_index]
        return (
            self.pet_x + bounds[0] * self.config.scale,
            self.pet_y + bounds[1] * self.config.scale,
            self.pet_x + bounds[2] * self.config.scale,
            self.pet_y + bounds[3] * self.config.scale,
        )

    def can_collect_coin_on_current_frame(self) -> bool:
        if self.current_action_index != self.work_action_index:
            return False
        return self.get_current_source_frame_index() in {2, 3}

    def get_task_pounce_distance(self, coin: CoinState | None = None) -> float:
        if coin is None:
            return float(self.config.scale * 12)
        return max(coin.width * 1.2, self.config.scale * 12)

    def should_use_task_pounce(self, coin: CoinState | None) -> bool:
        if coin is None:
            return False
        pet_center_x = self.pet_x + self.config.pet_width / 2
        coin_center_x = coin.x + coin.width / 2
        return abs(coin_center_x - pet_center_x) <= self.get_task_pounce_distance(coin)

    def get_task_action_index(self, coin: CoinState | None = None) -> int:
        if self.should_use_task_pounce(coin):
            return self.work_action_index
        return self.task_move_action_index

    def sync_task_action(self, target_coin: CoinState | None = None) -> None:
        if not self.task_active or not self.connection_state or not self.actions:
            return
        desired_action_index = self.get_task_action_index(target_coin)
        if (
            self.current_action_index == self.work_action_index
            and desired_action_index != self.work_action_index
            and self.current_frame_index < len(self.current_frame_order)
        ):
            return
        if desired_action_index == self.current_action_index:
            return
        self.activate_action(desired_action_index)

    def get_target_coin(self) -> CoinState | None:
        if not self.coins:
            return None
        candidates = [coin for coin in self.coins if coin.grounded] or self.coins
        pet_center = self.pet_x + self.config.pet_width / 2
        return min(candidates, key=lambda coin: abs((coin.x + coin.width / 2) - pet_center))

    def collect_overlapping_coins(self) -> None:
        if not self.coins:
            return
        if not self.can_collect_coin_on_current_frame():
            return

        pet_left, pet_top, pet_right, pet_bottom = self.get_pet_hitbox()
        pet_center_x = (pet_left + pet_right) / 2
        collected_any = False
        remaining: list[CoinState] = []
        for coin in self.coins:
            coin_left = coin.x
            coin_top = coin.y
            coin_right = coin_left + coin.width
            coin_bottom = coin_top + coin.height
            coin_center_x = (coin_left + coin_right) / 2
            overlap_x = coin_right >= pet_left + 2 and coin_left <= pet_right - 2
            overlap_y = coin_bottom >= pet_top + self.config.pet_height * 0.16 and coin_top <= pet_bottom
            lunge_reach = abs(coin_center_x - pet_center_x) <= max(coin.width * 1.1, self.config.scale * 9)
            if (overlap_x and overlap_y) or (lunge_reach and overlap_y):
                self.canvas.delete(coin.item_id)
                collected_any = True
                continue
            remaining.append(coin)
        self.coins = remaining
        if collected_any and self.current_action_index == self.work_action_index:
            self.current_hold_ms = max(self.current_hold_ms, self.config.task_pounce_recover_ms)
        if self.task_active and not self.coins:
            self.schedule_next_coin_spawn()

    def pick_action_index_for_role(self, role: str, filter_recent: bool = True) -> int:
        choices = [index for index, spec in enumerate(self.action_specs) if spec.role == role]
        if not choices:
            choices = list(range(len(self.actions)))
        if filter_recent:
            choices = self.filter_recent_choices(choices)
        weights = [self.action_specs[index].weight for index in choices]
        return random.choices(choices, weights=weights, k=1)[0]

    def activate_action(self, action_index: int) -> None:
        self.current_action_index = action_index
        self.current_role = self.action_specs[self.current_action_index].role
        self.recent_actions.append(self.current_action_index)
        self.current_frame_index = 0
        spec = self.action_specs[self.current_action_index]
        self.current_frame_order = self.build_frame_order(spec, len(self.actions[self.current_action_index]))
        self.current_frame_delay_ms = self.get_randomized_frame_delay(spec)
        self.current_hold_ms = self.get_randomized_hold(spec)
        self.prepare_motion(spec)

    def force_role(self, role: str) -> None:
        action_index = self.pick_action_index_for_role(role, filter_recent=False)
        self.force_action_index(action_index)

    def choose_next_action(self, first_pick: bool = False) -> None:
        if not self.connection_state:
            self.activate_action(self.disconnected_action_index)
            return
        if self.task_active:
            self.activate_action(self.get_task_action_index(self.get_target_coin()))
            return
        next_role = self.choose_next_role(first_pick)
        action_index = self.pick_action_index_for_role(next_role)
        self.activate_action(action_index)

    def choose_next_role(self, first_pick: bool) -> str:
        available_roles = sorted({spec.role for spec in self.action_specs if spec.role not in {"work"}})
        if not available_roles:
            return "idle"

        if self.wakeup_after_connect and "stretch" in available_roles:
            self.wakeup_after_connect = False
            return "stretch"

        if first_pick:
            opener_weights = {"idle": 5.0, "stretch": 1.0, "walk": 1.0}
            roles = [role for role in available_roles if role in opener_weights]
            if roles:
                return random.choices(roles, weights=[opener_weights[role] for role in roles], k=1)[0]
            return random.choice(available_roles)

        transitions = ROLE_TRANSITIONS.get(self.current_role, ROLE_TRANSITIONS["idle"])
        roles = [role for role in available_roles if role in transitions]
        if roles:
            return random.choices(roles, weights=[transitions[role] for role in roles], k=1)[0]

        return random.choice(available_roles)

    def filter_recent_choices(self, choices: list[int]) -> list[int]:
        recent_choices = set(self.recent_actions)
        filtered_choices = [index for index in choices if index not in recent_choices]
        if filtered_choices:
            return filtered_choices

        if len(choices) > 1 and self.current_action_index in choices:
            without_current = [index for index in choices if index != self.current_action_index]
            if without_current:
                return without_current

        return choices

    def build_frame_order(self, spec: ActionSpec, frame_count: int) -> list[int]:
        if self.task_active and self.current_action_index == self.work_action_index:
            pounce_sequence = [index for index in (1, 2, 2, 3, 3, 4) if index < frame_count]
            if pounce_sequence:
                return pounce_sequence

        if frame_count <= 2:
            return list(range(frame_count))

        order = list(range(frame_count))
        if random.random() < spec.ping_pong_chance:
            order = order + list(range(frame_count - 2, 0, -1))

        cycle_count = random.randint(spec.min_cycles, spec.max_cycles)
        return order * cycle_count

    def get_randomized_frame_delay(self, spec: ActionSpec) -> int:
        base_delay = int(self.config.frame_delay_ms * spec.speed_multiplier)
        if self.task_active and self.current_action_index == self.work_action_index:
            base_delay = int(base_delay * 1.22)
            jitter = random.randint(-max(6, self.config.frame_jitter_ms // 3), max(6, self.config.frame_jitter_ms // 3))
            return max(65, base_delay + jitter)
        if not self.connection_state and self.current_action_index == self.disconnected_action_index:
            base_delay = int(base_delay * 1.28)
        jitter = random.randint(-self.config.frame_jitter_ms, self.config.frame_jitter_ms)
        return max(50, base_delay + jitter)

    def get_randomized_hold(self, spec: ActionSpec) -> int:
        if self.task_active and self.current_action_index in {self.work_action_index, self.task_move_action_index}:
            return 0
        if not self.connection_state and self.current_action_index == self.disconnected_action_index:
            return random.randint(900, 1800)
        if spec.max_hold_ms <= 0:
            return 0
        return random.randint(spec.min_hold_ms, spec.max_hold_ms)

    def get_transition_pause(self, spec: ActionSpec) -> int:
        if self.task_active and self.current_action_index in {self.work_action_index, self.task_move_action_index}:
            return 0
        if not self.connection_state and self.current_action_index == self.disconnected_action_index:
            return random.randint(550, 1100)
        return random.randint(spec.min_pause_ms, spec.max_pause_ms)

    def prepare_motion(self, spec: ActionSpec) -> None:
        if spec.move_step_multiplier <= 0:
            return
        if self.task_active and self.current_action_index in {self.work_action_index, self.task_move_action_index}:
            return
        if random.random() < 0.22:
            self.direction *= -1

    def get_move_step(self, spec: ActionSpec) -> int:
        if spec.move_step_multiplier <= 0:
            return 0
        return max(1, round(self.config.scale * spec.move_step_multiplier))

    def update_patrol_motion(self, step: int) -> None:
        next_x = self.pet_x + step * self.direction
        if next_x <= self.min_pet_x:
            next_x = self.min_pet_x
            self.direction = 1
        elif next_x >= self.max_pet_x:
            next_x = self.max_pet_x
            self.direction = -1
        self.pet_x = next_x

    def update_work_motion(self, step: int) -> None:
        target_coin = self.get_target_coin()
        if target_coin is None:
            self.update_patrol_motion(max(1, step // 2))
            return

        pet_center_x = self.pet_x + self.config.pet_width / 2
        target_center_x = target_coin.x + target_coin.width / 2
        delta_x = target_center_x - pet_center_x
        if abs(delta_x) <= 1:
            return

        self.direction = -1 if delta_x < 0 else 1
        move_distance = min(abs(delta_x), step)
        self.pet_x = clamp(self.pet_x + move_distance * self.direction, self.min_pet_x, self.max_pet_x)

    def update_motion(self, spec: ActionSpec) -> None:
        if not self.connection_state and self.current_action_index == self.disconnected_action_index:
            return
        step = self.get_move_step(spec)
        if step <= 0:
            return
        if self.task_active and self.current_action_index in {self.work_action_index, self.task_move_action_index}:
            self.update_work_motion(step)
            return
        self.update_patrol_motion(step)

    def draw_current_frame(self) -> None:
        frames = self.flipped_actions[self.current_action_index] if self.direction < 0 else self.actions[self.current_action_index]
        frame_order_index = min(self.current_frame_index, max(0, len(self.current_frame_order) - 1))
        frame = frames[self.current_frame_order[frame_order_index]]
        self.canvas.itemconfigure(self.pet_item, image=frame)
        self.canvas.coords(self.pet_item, round(self.pet_x), self.pet_y)
        self.draw_current_emote()

    def queue_next_action(self) -> None:
        self.transition_after_id = None
        self.choose_next_action()
        self.tick_animation()

    def tick_animation(self) -> None:
        self.animation_after_id = None
        target_coin = self.get_target_coin() if self.task_active else None
        if self.task_active and self.connection_state:
            self.sync_task_action(target_coin)
        spec = self.action_specs[self.current_action_index]
        self.update_motion(spec)
        self.draw_current_frame()

        self.current_frame_index += 1
        if self.current_frame_index >= len(self.current_frame_order):
            transition_pause_ms = self.get_transition_pause(spec)
            self.transition_after_id = self.root.after(self.current_hold_ms + transition_pause_ms, self.queue_next_action)
            return

        self.animation_after_id = self.root.after(self.current_frame_delay_ms, self.tick_animation)

    def show_menu(self, event: tk.Event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def on_drag_start(self, event: tk.Event) -> None:
        self.drag_enabled = self.pointer_on_pet(event)
        self.dragged = False
        if not self.drag_enabled:
            return
        self.drag_offset_x = event.x_root - self.root.winfo_x()
        self.drag_offset_y = event.y_root - self.root.winfo_y()

    def on_drag_move(self, event: tk.Event) -> None:
        if not self.drag_enabled:
            return
        self.dragged = True
        x = event.x_root - self.drag_offset_x
        y = event.y_root - self.drag_offset_y
        self.pin_window(x, y, persist=False)

    def on_drag_end(self, _event: tk.Event) -> None:
        if not self.drag_enabled:
            return
        self.drag_enabled = False
        if self.dragged:
            self.save_position()

    def redock(self) -> None:
        self.docked = True
        self.clear_saved_position()
        x, y = position_above_tray(self.window_width, self.window_height, self.config.margin)
        self.move_window(x, y)

    def refresh_anchor(self) -> None:
        if self.docked:
            self.redock()
        self.root.after(self.config.anchor_refresh_ms, self.refresh_anchor)


def main() -> None:
    enable_dpi_awareness()
    args = parse_args()
    config = PetConfig(
        sprite_path=args.sprite,
        emote_dir=args.emote_dir,
        coin_dir=args.coin_dir,
        state_path=app_path("desktop_cat_state.json"),
        runtime_path=app_path("desktop_cat_runtime.json"),
        session_state_path=app_path("desktop_cat_session_state.json"),
        openclaw_url=args.openclaw_url,
        openclaw_token=args.openclaw_token,
        openclaw_session_key=normalize_openclaw_session_key(args.openclaw_session_key),
        device_identity_path=app_path("openclaw_device_identity.json"),
        device_auth_path=app_path("openclaw_device_auth.json"),
        frame_width=args.frame_width,
        frame_height=args.frame_height,
        scale=args.scale,
        frame_delay_ms=max(1, int(1000 / max(1, args.fps))),
        margin=args.margin,
    )

    actions = extract_actions(config)

    if args.dry_run:
        specs = build_action_specs(len(actions))
        connection_info = build_openclaw_connection_info(config.openclaw_url, config.openclaw_token)
        print(f"sprite={config.sprite_path}")
        print(f"emote_dir={config.emote_dir}")
        print(f"coin_dir={config.coin_dir}")
        print(f"openclaw_url={normalize_openclaw_url(config.openclaw_url) or '(not set)'}")
        print(f"gateway_url={connection_info.gateway_url or '(not set)'}")
        print(f"openclaw_token={'(set)' if connection_info.token else '(not set)'}")
        session_label = config.openclaw_session_key or "(auto latest session)"
        print(f"openclaw_session_key={session_label}")
        print(f"actions={len(actions)}")
        print("frames_per_action=" + ",".join(str(len(action)) for action in actions))
        print("action_map=" + "; ".join(f"{index + 1}:{spec.name}/{spec.role}" for index, spec in enumerate(specs)))
        return

    root = tk.Tk()
    root.title("Pawly")
    DesktopCat(root, config, actions)
    root.mainloop()


if __name__ == "__main__":
    main()
