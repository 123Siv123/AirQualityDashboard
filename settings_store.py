"""Load/save AQ Monitor configuration (settings.json + .env merge)."""

import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
ENV_FILE = os.path.join(ROOT, ".env")

GAS_PROFILES = {
    "standard": {
        "gas_safe_max": 240,
        "gas_moderate": 241,
        "gas_moderate_max": 280,
        "gas_critical": 281,
        "gas_poor_max": 340,
        "gas_moderate_clear": 235,
        "gas_critical_clear": 275,
    },
    "mq2": {
        "gas_safe_max": 650,
        "gas_moderate": 651,
        "gas_moderate_max": 850,
        "gas_critical": 851,
        "gas_poor_max": 2000,
        "gas_moderate_clear": 620,
        "gas_critical_clear": 820,
    },
}

ENV_KEYS = {
    "GAS_SENSOR": "gas_sensor_profile",
    "GAS_SAFE_MAX": "gas_safe_max",
    "GAS_MODERATE": "gas_moderate",
    "GAS_MODERATE_MAX": "gas_moderate_max",
    "GAS_CRITICAL": "gas_critical",
    "GAS_POOR_MAX": "gas_poor_max",
    "GAS_MODERATE_CLEAR": "gas_moderate_clear",
    "GAS_CRITICAL_CLEAR": "gas_critical_clear",
    "SMOKE_LATCH_SEC": "smoke_latch_sec",
    "SERIAL_PORT": "serial_port",
    "SERIAL_BAUD": "serial_baud",
    "TWILIO_ENABLED": "twilio_enabled",
    "TWILIO_FROM_NUMBER": "twilio_from_number",
    "TWILIO_TO_NUMBER": "twilio_to_number",
    "TWILIO_SMS_MODERATE": "twilio_sms_moderate",
    "TWILIO_SMS_COOLDOWN_SEC": "twilio_sms_cooldown_sec",
}


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_env_lines():
    if not os.path.isfile(ENV_FILE):
        return []
    with open(ENV_FILE, encoding="utf-8") as f:
        return f.readlines()


def _patch_env(updates):
    """Merge key=value pairs into .env without removing other keys."""
    lines = _read_env_lines()
    seen = set()
    out = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            out.append(line)

    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}\n")

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(out)


def _defaults_from_env():
    profile = os.environ.get("GAS_SENSOR", "standard").lower().strip()
    if profile not in GAS_PROFILES:
        profile = "standard"
    base = dict(GAS_PROFILES[profile])

    def _int(key, fallback):
        try:
            return int(os.environ.get(key, fallback))
        except (TypeError, ValueError):
            return int(fallback)

    return {
        "gas_sensor_profile": profile,
        "gas_safe_max": _int("GAS_SAFE_MAX", base["gas_safe_max"]),
        "gas_moderate": _int("GAS_MODERATE", base["gas_moderate"]),
        "gas_moderate_max": _int("GAS_MODERATE_MAX", base["gas_moderate_max"]),
        "gas_critical": _int("GAS_CRITICAL", base["gas_critical"]),
        "gas_poor_max": _int("GAS_POOR_MAX", base["gas_poor_max"]),
        "gas_moderate_clear": _int("GAS_MODERATE_CLEAR", base["gas_moderate_clear"]),
        "gas_critical_clear": _int("GAS_CRITICAL_CLEAR", base["gas_critical_clear"]),
        "smoke_latch_sec": _int("SMOKE_LATCH_SEC", 60),
        "serial_port": os.environ.get("SERIAL_PORT", "COM7"),
        "serial_baud": _int("SERIAL_BAUD", 115200),
        "twilio_enabled": os.environ.get("TWILIO_ENABLED", "1").lower() in ("1", "true", "yes", "on"),
        "twilio_from_number": os.environ.get("TWILIO_FROM_NUMBER", ""),
        "twilio_to_number": os.environ.get("TWILIO_TO_NUMBER", ""),
        "twilio_sms_moderate": os.environ.get("TWILIO_SMS_MODERATE", "").lower() in ("1", "true", "yes", "on"),
        "twilio_sms_cooldown_sec": _int("TWILIO_SMS_COOLDOWN_SEC", 300),
        "twilio_account_sid": os.environ.get("TWILIO_ACCOUNT_SID", ""),
        "twilio_auth_token_set": bool(os.environ.get("TWILIO_AUTH_TOKEN")),
    }


def load_settings():
    _ensure_data_dir()
    settings = _defaults_from_env()

    if os.path.isfile(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                settings.update({k: v for k, v in stored.items() if k in settings or k.startswith("gas_") or k.startswith("twilio_") or k in ("serial_port", "serial_baud", "smoke_latch_sec")})
        except (json.JSONDecodeError, OSError):
            pass

    return settings


def settings_to_env(settings):
    return {
        "GAS_SENSOR": str(settings.get("gas_sensor_profile", "standard")),
        "GAS_SAFE_MAX": str(int(settings["gas_safe_max"])),
        "GAS_MODERATE": str(int(settings["gas_moderate"])),
        "GAS_MODERATE_MAX": str(int(settings["gas_moderate_max"])),
        "GAS_CRITICAL": str(int(settings["gas_critical"])),
        "GAS_POOR_MAX": str(int(settings["gas_poor_max"])),
        "GAS_MODERATE_CLEAR": str(int(settings["gas_moderate_clear"])),
        "GAS_CRITICAL_CLEAR": str(int(settings["gas_critical_clear"])),
        "SMOKE_LATCH_SEC": str(int(settings["smoke_latch_sec"])),
        "SERIAL_PORT": str(settings["serial_port"]).strip(),
        "SERIAL_BAUD": str(int(settings["serial_baud"])),
        "TWILIO_ENABLED": "1" if settings.get("twilio_enabled") else "0",
        "TWILIO_FROM_NUMBER": str(settings.get("twilio_from_number", "")).strip(),
        "TWILIO_TO_NUMBER": str(settings.get("twilio_to_number", "")).strip(),
        "TWILIO_SMS_MODERATE": "1" if settings.get("twilio_sms_moderate") else "0",
        "TWILIO_SMS_COOLDOWN_SEC": str(int(settings["twilio_sms_cooldown_sec"])),
    }


def apply_settings_to_environ(settings):
    for key, value in settings_to_env(settings).items():
        os.environ[key] = value


def save_settings(settings):
    _ensure_data_dir()
    persist = {k: settings[k] for k in settings if not k.startswith("twilio_auth") and k != "twilio_account_sid"}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(persist, f, indent=2)
    _patch_env(settings_to_env(settings))
    apply_settings_to_environ(settings)


def public_settings(settings):
    safe = {k: v for k, v in settings.items() if k != "twilio_account_sid"}
    sid = settings.get("twilio_account_sid") or os.environ.get("TWILIO_ACCOUNT_SID", "")
    masked_sid = ""
    if sid and len(sid) > 6:
        masked_sid = sid[:4] + "…" + sid[-4:]
    elif sid:
        masked_sid = "••••"

    import sms_twilio

    return {
        **{k: v for k, v in safe.items() if not k.startswith("twilio_auth")},
        "twilio_account_sid_masked": masked_sid,
        "twilio_auth_token_set": bool(os.environ.get("TWILIO_AUTH_TOKEN")),
        "twilio_status": sms_twilio.status_dict(),
        "profiles": list(GAS_PROFILES.keys()),
        "profile_presets": GAS_PROFILES,
    }


def validate_settings(data):
    errors = []
    profile = str(data.get("gas_sensor_profile", "standard")).lower().strip()
    if profile not in GAS_PROFILES:
        errors.append("Invalid gas sensor profile")

    try:
        safe = int(data["gas_safe_max"])
        mod = int(data["gas_moderate"])
        mod_max = int(data["gas_moderate_max"])
        crit = int(data["gas_critical"])
        if not (safe < mod <= mod_max < crit):
            errors.append("Thresholds must increase: safe < moderate ≤ moderate_max < critical")
    except (KeyError, TypeError, ValueError):
        errors.append("Invalid gas threshold numbers")

    port = str(data.get("serial_port", "")).strip()
    if not port:
        errors.append("Serial port is required")

    try:
        latch = int(data.get("smoke_latch_sec", 60))
        if latch < 5 or latch > 600:
            errors.append("Smoke latch must be between 5 and 600 seconds")
    except (TypeError, ValueError):
        errors.append("Invalid smoke latch value")

    if data.get("twilio_enabled"):
        if not str(data.get("twilio_to_number", "")).strip():
            errors.append("Twilio To number is required when SMS is enabled")

    return errors


def normalize_payload(data):
    current = load_settings()
    profile = str(data.get("gas_sensor_profile", current["gas_sensor_profile"])).lower().strip()

    if data.get("apply_profile_preset") and profile in GAS_PROFILES:
        preset = GAS_PROFILES[profile]
        for k, v in preset.items():
            data[k] = v

    out = dict(current)
    out["gas_sensor_profile"] = profile
    for key in (
        "gas_safe_max", "gas_moderate", "gas_moderate_max", "gas_critical",
        "gas_poor_max", "gas_moderate_clear", "gas_critical_clear",
        "smoke_latch_sec", "serial_baud", "twilio_sms_cooldown_sec",
    ):
        if key in data:
            out[key] = int(data[key])

    if "gas_poor_max" not in data and "gas_critical" in data:
        out["gas_poor_max"] = int(data["gas_critical"]) + 60
    if "gas_moderate_clear" not in data and "gas_moderate" in data:
        out["gas_moderate_clear"] = max(0, int(data["gas_moderate"]) - 6)
    if "gas_critical_clear" not in data and "gas_critical" in data:
        out["gas_critical_clear"] = max(0, int(data["gas_critical"]) - 6)
    if "serial_port" in data:
        out["serial_port"] = str(data["serial_port"]).strip()
    out["twilio_enabled"] = bool(data.get("twilio_enabled", current["twilio_enabled"]))
    out["twilio_sms_moderate"] = bool(data.get("twilio_sms_moderate", current["twilio_sms_moderate"]))
    for key in ("twilio_from_number", "twilio_to_number"):
        if key in data:
            out[key] = str(data[key]).strip()
    return out
