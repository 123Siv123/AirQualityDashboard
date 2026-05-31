import json
import math
import os
import random
import threading
import time
from collections import deque
from datetime import datetime

import serial
from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

import settings_store
import sms_twilio

app = Flask(__name__)
DASHBOARD_BUILD = "layout-v13-status-sync"


@app.after_request
def disable_browser_cache(response):
    """Prevent stale dashboard HTML/CSS when Flask is restarted."""
    pwa_assets = ("/sw.js", "/static/manifest.webmanifest", "/static/sw.js")
    if request.path in pwa_assets or request.path.startswith("/static/icons/"):
        return response
    if request.path in ("/", "/login", "/dashboard", "/analytics", "/alerts", "/settings") or (
        request.path.startswith("/static/") and not request.path.endswith(
            (".png", ".webmanifest", "pwa-install.js", "sw.js")
        )
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(
        os.path.join(app.root_path, "static"),
        "sw.js",
        mimetype="application/javascript",
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response

_MQ2_DEFAULTS = {
    "safe_max": "650",
    "moderate": "651",
    "moderate_max": "850",
    "critical": "851",
    "poor_max": "2000",
    "moderate_clear": "620",
    "critical_clear": "820",
}
_STANDARD_DEFAULTS = {
    "safe_max": "240",
    "moderate": "241",
    "moderate_max": "280",
    "critical": "281",
    "poor_max": "340",
    "moderate_clear": "235",
    "critical_clear": "275",
}

_RUNTIME_SETTINGS = settings_store.load_settings()
settings_store.apply_settings_to_environ(_RUNTIME_SETTINGS)

_GAS_PROFILE = _RUNTIME_SETTINGS["gas_sensor_profile"]
_GAS_DEFAULTS = _STANDARD_DEFAULTS if _GAS_PROFILE == "standard" else _MQ2_DEFAULTS
SERIAL_PORT = _RUNTIME_SETTINGS["serial_port"]
SERIAL_BAUD = int(_RUNTIME_SETTINGS["serial_baud"])
GAS_SAFE_MAX = int(_RUNTIME_SETTINGS["gas_safe_max"])
GAS_MODERATE_THRESHOLD = int(_RUNTIME_SETTINGS["gas_moderate"])
GAS_MODERATE_MAX = int(_RUNTIME_SETTINGS["gas_moderate_max"])
GAS_CRITICAL_THRESHOLD = int(_RUNTIME_SETTINGS["gas_critical"])
GAS_POOR_MAX = int(_RUNTIME_SETTINGS["gas_poor_max"])
GAS_MODERATE_CLEAR = int(_RUNTIME_SETTINGS["gas_moderate_clear"])
GAS_CRITICAL_CLEAR = int(_RUNTIME_SETTINGS["gas_critical_clear"])

sensor_data = {
    "temperature": "--",
    "humidity": "--",
    "gas": "--",
    "status": "--",
}

data_lock = threading.Lock()
alert_history = deque(maxlen=100)
sensor_history = deque(maxlen=180)
alert_counts = {"critical": 0, "moderate": 0, "safe": 0}
last_alert_at = None
last_severity = "safe"
serial_connected = False
last_serial_read = None
last_snapshot_at = None
last_smoke_at = None
SMOKE_LATCH_SEC = int(_RUNTIME_SETTINGS["smoke_latch_sec"])

sim_state = {
    "gas": 195.0,
    "temp": 27.5,
    "humidity": 58.0,
    "gas_target": 195.0,
    "temp_target": 28.0,
    "hum_target": 57.0,
}

_gas_band_state = {"band": "normal"}
_last_stream_alert = {"instant": None, "gas": None, "time": None}

ser = None


def apply_runtime_settings(settings=None):
    """Apply settings dict to live globals (after admin save)."""
    global _RUNTIME_SETTINGS, _GAS_PROFILE, _GAS_DEFAULTS
    global SERIAL_PORT, SERIAL_BAUD, SMOKE_LATCH_SEC
    global GAS_SAFE_MAX, GAS_MODERATE_THRESHOLD, GAS_MODERATE_MAX
    global GAS_CRITICAL_THRESHOLD, GAS_POOR_MAX, GAS_MODERATE_CLEAR, GAS_CRITICAL_CLEAR

    if settings is None:
        settings = settings_store.load_settings()

    _RUNTIME_SETTINGS = settings
    settings_store.apply_settings_to_environ(settings)

    _GAS_PROFILE = settings["gas_sensor_profile"]
    _GAS_DEFAULTS = _STANDARD_DEFAULTS if _GAS_PROFILE == "standard" else _MQ2_DEFAULTS
    SERIAL_PORT = settings["serial_port"]
    SERIAL_BAUD = int(settings["serial_baud"])
    SMOKE_LATCH_SEC = int(settings["smoke_latch_sec"])
    GAS_SAFE_MAX = int(settings["gas_safe_max"])
    GAS_MODERATE_THRESHOLD = int(settings["gas_moderate"])
    GAS_MODERATE_MAX = int(settings["gas_moderate_max"])
    GAS_CRITICAL_THRESHOLD = int(settings["gas_critical"])
    GAS_POOR_MAX = int(settings["gas_poor_max"])
    GAS_MODERATE_CLEAR = int(settings["gas_moderate_clear"])
    GAS_CRITICAL_CLEAR = int(settings["gas_critical_clear"])
    sms_twilio.reload_config()


def reconnect_serial_port():
    global ser
    if ser:
        try:
            ser.close()
        except Exception:
            pass
        ser = None
    connect_serial()


def classify_status(status_text):
    if not status_text or status_text == "--":
        return "safe"

    normalized = status_text.lower().strip()

    if any(word in normalized for word in ("poor", "critical", "danger", "hazard", "unhealthy")):
        return "critical"
    if any(word in normalized for word in ("moderate", "warning", "caution")):
        return "moderate"
    if any(word in normalized for word in ("normal", "good", "safe")):
        return "safe"

    return "safe"


def parse_numeric_value(text):
    if not text or text == "--":
        return None

    digits = "".join(ch for ch in str(text) if ch.isdigit() or ch == ".")
    if not digits:
        return None

    try:
        return float(digits)
    except ValueError:
        return None


def parse_gas_value(gas_text):
    if not gas_text or gas_text == "--":
        return None

    digits = "".join(ch for ch in str(gas_text) if ch.isdigit() or ch == ".")
    if not digits:
        return None

    try:
        return float(digits)
    except ValueError:
        return None


def severity_from_gas(gas_value):
    if gas_value is None:
        return None
    if gas_value >= GAS_CRITICAL_THRESHOLD:
        return "critical"
    if gas_value >= GAS_MODERATE_THRESHOLD:
        return "moderate"
    return "safe"


def instantaneous_gas_band(gas_value):
    """Current reading only — used for dashboard display (not peak/history)."""
    if gas_value is None:
        return "normal"
    if gas_value >= GAS_CRITICAL_THRESHOLD:
        return "poor"
    if gas_value >= GAS_MODERATE_THRESHOLD:
        return "moderate"
    return "normal"


def gas_status_bundle(gas_value):
    """Single source of truth: level, label, and alert severity from live gas."""
    band = instantaneous_gas_band(gas_value)
    if band == "poor":
        return {
            "level": "poor",
            "label": "Poor Air Quality",
            "severity": "critical",
        }
    if band == "moderate":
        return {
            "level": "moderate",
            "label": "Moderate Air Quality",
            "severity": "moderate",
        }
    return {
        "level": "normal",
        "label": "Normal Air Quality",
        "severity": "safe",
    }


def gas_quality_band(gas_value):
    """Hysteresis for alerts/logging; UI uses instantaneous_gas_band."""
    global _gas_band_state
    if gas_value is None:
        return "normal"

    instant = instantaneous_gas_band(gas_value)
    band = _gas_band_state.get("band", "normal")
    if band == "poor":
        if gas_value < GAS_CRITICAL_CLEAR:
            band = "moderate" if gas_value >= GAS_MODERATE_CLEAR else "normal"
    elif band == "moderate":
        if gas_value >= GAS_CRITICAL_THRESHOLD:
            band = "poor"
        elif gas_value < GAS_MODERATE_CLEAR:
            band = "normal"
    else:
        band = instant

    _gas_band_state["band"] = band
    return band


def resolve_current_severity(gas_value, status_text=None):
    """Gas index is the source of truth when a reading exists."""
    if gas_value is not None:
        return gas_status_bundle(gas_value)["severity"]
    classified = classify_status(status_text)
    return classified if classified else "safe"


def is_smoke_detected(gas_value, status_text=None):
    """Smoke = poor air band (MQ-2 spike above calibrated poor threshold)."""
    if gas_value is not None and gas_value >= GAS_CRITICAL_THRESHOLD:
        return True
    if status_text and status_text != "--":
        normalized = status_text.lower()
        if "smoke" in normalized and any(
            word in normalized for word in ("detect", "alert", "poor", "critical", "hazard")
        ):
            return True
    return False


def format_relative_time(timestamp):
    if not timestamp:
        return "No alerts yet"

    delta_seconds = int((datetime.now() - timestamp).total_seconds())
    if delta_seconds < 5:
        return "Just now"
    if delta_seconds < 60:
        return f"{delta_seconds} sec ago"
    if delta_seconds < 3600:
        minutes = delta_seconds // 60
        return f"{minutes} min{'s' if minutes != 1 else ''} ago"
    hours = delta_seconds // 3600
    return f"{hours} hr{'s' if hours != 1 else ''} ago"


def add_alert(sensor, severity, detail, active=True, track_last=True):
    global last_alert_at, last_severity

    now = datetime.now()
    entry = {
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "timestamp": now.isoformat(),
        "sensor": sensor,
        "severity": severity,
        "detail": detail,
        "status": "Active" if active and severity == "critical" else (
            "Monitoring" if active and severity == "moderate" else "Resolved"
        ),
    }

    is_sensor_event = sensor != "System"

    with data_lock:
        alert_history.appendleft(entry)
        if is_sensor_event:
            alert_counts[severity] = alert_counts.get(severity, 0) + 1
        if track_last and is_sensor_event:
            last_alert_at = now
            last_severity = severity

    if is_sensor_event:
        sms_twilio.maybe_send_alert(sensor, severity, detail)


def record_status_change(status_text):
    severity = classify_status(status_text)
    add_alert("AQI Monitor", severity, f"Air quality status: {status_text.strip()}")


def record_gas_alert(gas_text, gas_value):
    severity = severity_from_gas(gas_value)
    if severity:
        add_alert("Gas Sensor", severity, f"Gas value: {gas_text.strip()}")


def capture_live_alert_event(gas_value, status_label=None):
    """Record band changes and throttled live readings (sim + serial)."""
    global _last_stream_alert

    if gas_value is None:
        return

    info = gas_status_bundle(gas_value)
    label = status_label if status_label and status_label != "--" else info["label"]
    instant = instantaneous_gas_band(gas_value)
    prev_instant = _last_stream_alert.get("instant")
    now = datetime.now()

    if prev_instant is not None and instant != prev_instant:
        add_alert(
            "Gas Sensor",
            info["severity"],
            f"Gas {gas_value:.0f} · {label}",
            active=instant != "normal",
            track_last=instant != "normal",
        )
        _last_stream_alert = {"instant": instant, "gas": gas_value, "time": now}
        return

    if prev_instant is None:
        _last_stream_alert = {"instant": instant, "gas": gas_value, "time": now}
        return

    elapsed = 999
    if _last_stream_alert.get("time"):
        elapsed = (now - _last_stream_alert["time"]).total_seconds()

    gas_delta = 0
    if _last_stream_alert.get("gas") is not None:
        gas_delta = abs(gas_value - _last_stream_alert["gas"])

    if elapsed < 12 and gas_delta < 8:
        return

    add_alert(
        "Live Stream",
        info["severity"],
        f"Gas {gas_value:.0f} · {label}",
        active=info["severity"] != "safe",
        track_last=False,
    )
    _last_stream_alert["time"] = now
    _last_stream_alert["gas"] = gas_value
    _last_stream_alert["instant"] = instant


def build_alert_logs(limit=25):
    """Live row + stored alerts + recent telemetry for the alerts table."""
    with data_lock:
        stored = list(alert_history)
        history = list(sensor_history)
        gas_value = parse_gas_value(sensor_data.get("gas"))

    rows = []
    if gas_value is not None:
        info = gas_status_bundle(gas_value)
        now = datetime.now()
        rows.append(
            {
                "time": now.strftime("%I:%M %p").lstrip("0"),
                "timestamp": now.isoformat(),
                "sensor": "● Live",
                "severity": info["severity"],
                "status": "Streaming",
                "detail": f"Gas {gas_value:.0f} · {info['label']}",
                "is_live": True,
            }
        )

    seen_ts = set()
    for entry in stored:
        ts = entry.get("timestamp")
        if ts:
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
        row = dict(entry)
        row["is_live"] = False
        rows.append(row)
        if len(rows) >= limit:
            return rows[:limit]

    for point in reversed(history[-30:]):
        ts = point.get("timestamp")
        if not ts or ts in seen_ts:
            continue
        seen_ts.add(ts)
        sev = point.get("severity") or severity_from_gas(point.get("gas")) or "safe"
        gas_part = point.get("gas")
        gas_display = f"{gas_part:.0f}" if isinstance(gas_part, (int, float)) else gas_part
        rows.append(
            {
                "time": point.get("time", "--"),
                "timestamp": ts,
                "sensor": "Telemetry",
                "severity": sev,
                "status": "Logged",
                "detail": f"Gas {gas_display} · {point.get('status', '--')}",
                "is_live": False,
            }
        )
        if len(rows) >= limit:
            break

    return rows[:limit]


def update_sensor_field(key, value):
    global last_serial_read, last_smoke_at

    cleaned = value.strip() if value else "--"

    with data_lock:
        previous_status = sensor_data.get("status")
        previous_gas = sensor_data.get("gas")
        sensor_data[key] = cleaned
        last_serial_read = datetime.now()
        current_status = sensor_data.get("status", "--")

    if key == "status" and cleaned != "--":
        gas_value = parse_gas_value(sensor_data.get("gas"))
        if gas_value is not None:
            derived = derive_status_from_metrics(gas_value, cleaned)
            with data_lock:
                sensor_data["status"] = derived
            if derived != previous_status:
                record_status_change(derived)
        elif cleaned != previous_status:
            record_status_change(cleaned)

    if key == "gas" and cleaned != "--":
        gas_value = parse_gas_value(cleaned)
        derived = derive_status_from_metrics(gas_value, current_status)
        with data_lock:
            sensor_data["status"] = derived
        if gas_value is not None:
            if is_smoke_detected(gas_value, derived):
                last_smoke_at = datetime.now()
            prev_gas = parse_gas_value(previous_gas)
            new_sev = severity_from_gas(gas_value) or "safe"
            old_sev = severity_from_gas(prev_gas) if prev_gas is not None else "safe"
            if new_sev != old_sev:
                record_gas_alert(cleaned, gas_value)
            capture_live_alert_event(gas_value, derived)

    record_sensor_snapshot()


def derive_status_from_metrics(gas_value, status_text=None):
    """Always derived from live gas when available."""
    if gas_value is not None:
        return gas_status_bundle(gas_value)["label"]
    if status_text and status_text != "--":
        classified = classify_status(status_text)
        if classified == "critical":
            return "Poor Air Quality"
        if classified == "moderate":
            return "Moderate Air Quality"
        return "Normal Air Quality"
    return "--"


def record_sensor_snapshot(force=False):
    global last_snapshot_at

    now = datetime.now()
    if (
        not force
        and last_snapshot_at
        and (now - last_snapshot_at).total_seconds() < 2
    ):
        return

    with data_lock:
        gas = parse_gas_value(sensor_data.get("gas"))
        temp = parse_numeric_value(sensor_data.get("temperature"))
        humidity = parse_numeric_value(sensor_data.get("humidity"))
        status = sensor_data.get("status", "--")

        if gas is None and temp is None and humidity is None and status == "--":
            return

        severity = resolve_current_severity(gas, status)

        sensor_history.append(
            {
                "time": now.strftime("%H:%M"),
                "timestamp": now.isoformat(),
                "gas": gas,
                "temperature": temp,
                "humidity": humidity,
                "status": status,
                "severity": severity,
            }
        )
        last_snapshot_at = now


def parse_serial_line(line):
    if "Temperature:" in line:
        update_sensor_field("temperature", line.split(":", 1)[1])
    elif "Humidity:" in line:
        update_sensor_field("humidity", line.split(":", 1)[1])
    elif "Gas Value:" in line:
        update_sensor_field("gas", line.split(":", 1)[1])
    elif "Status:" in line:
        update_sensor_field("status", line.split(":", 1)[1])


def connect_serial():
    global ser, serial_connected

    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
        time.sleep(2)
        serial_connected = True
        add_alert(
            "System",
            "safe",
            f"Serial connected on {SERIAL_PORT}",
            active=False,
            track_last=False,
        )
    except serial.SerialException:
        ser = None
        serial_connected = False
        add_alert(
            "System",
            "moderate",
            "Serial port unavailable — demo mode active",
            active=False,
            track_last=False,
        )


def serial_reader_loop():
    global serial_connected

    while True:
        if not ser:
            serial_connected = False
            time.sleep(2)
            continue

        try:
            if ser.in_waiting > 0:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    print(line)
                    parse_serial_line(line)
                    serial_connected = True
        except (serial.SerialException, OSError, UnicodeDecodeError):
            serial_connected = False
            time.sleep(1)
        else:
            time.sleep(0.05)


def resolve_last_alert_info(history, last_at):
    """Most recent real sensor alert (ignores system boot messages)."""
    for entry in history:
        if entry.get("sensor") == "System":
            continue
        try:
            timestamp = datetime.fromisoformat(entry["timestamp"])
        except (TypeError, ValueError):
            continue
        return {
            "text": format_relative_time(timestamp),
            "iso": entry["timestamp"],
            "clock": entry.get("time", "--"),
        }

    if last_at:
        return {
            "text": format_relative_time(last_at),
            "iso": last_at.isoformat(),
            "clock": last_at.strftime("%I:%M %p").lstrip("0"),
        }

    return {
        "text": "No sensor alerts yet",
        "iso": None,
        "clock": "--",
    }


def get_snapshot():
    global last_smoke_at
    with data_lock:
        last_alert = resolve_last_alert_info(list(alert_history), last_alert_at)
        total_events = sum(alert_counts.values())
        safe_ratio = 0
        if total_events:
            safe_ratio = round((alert_counts.get("safe", 0) / total_events) * 100)

        now = datetime.now()
        gas_value = parse_gas_value(sensor_data.get("gas"))
        history_gas = [p["gas"] for p in list(sensor_history) if p.get("gas") is not None]
        peak_gas = max(history_gas) if history_gas else (gas_value or 0)
        status_info = gas_status_bundle(gas_value)
        display_status = status_info["label"]
        air_level = status_info["level"]
        current_severity = status_info["severity"]
        sensor_data["status"] = display_status
        smoke_detected = is_smoke_detected(gas_value, None)
        if smoke_detected:
            last_smoke_at = now
        smoke_recent_sec = int((now - last_smoke_at).total_seconds()) if last_smoke_at else None
        smoke_recent = smoke_recent_sec is not None and smoke_recent_sec <= SMOKE_LATCH_SEC
        sensor_payload = dict(sensor_data)
        sensor_payload["status"] = display_status

        snapshot_age_sec = (
            int((datetime.now() - last_snapshot_at).total_seconds()) if last_snapshot_at else None
        )

        snapshot = {
            "sensor": sensor_payload,
            "display_status": display_status,
            "air_quality_level": air_level,
            "live_gas": gas_value,
            "gas_thresholds": {
                "safe_max": GAS_SAFE_MAX,
                "moderate": GAS_MODERATE_THRESHOLD,
                "moderate_max": GAS_MODERATE_MAX,
                "critical": GAS_CRITICAL_THRESHOLD,
                "profile": _GAS_PROFILE,
            },
            "smoke_detected": smoke_detected,
            "smoke_recent": smoke_recent,
            "smoke_recent_sec": smoke_recent_sec if smoke_recent else None,
            "smoke_last_iso": last_smoke_at.isoformat() if last_smoke_at else None,
            "summary": {
                "critical": alert_counts.get("critical", 0),
                "moderate": alert_counts.get("moderate", 0),
                "safe_percent": safe_ratio,
                "peak_gas": peak_gas,
                "last_alert": last_alert["text"],
                "last_alert_iso": last_alert["iso"],
                "last_alert_clock": last_alert["clock"],
            },
            "current_severity": current_severity,
            "stream": {
                "connected": serial_connected,
                "serial_fresh": (
                    last_serial_read is not None
                    and (datetime.now() - last_serial_read).total_seconds() < 10
                ),
                "snapshot_age_sec": snapshot_age_sec,
            },
            "sensors": build_sensor_health(
                gas_value is not None,
                sensor_data.get("status") not in ("--", ""),
                current_severity,
                serial_connected,
                smoke_detected,
                snapshot_age_sec,
            ),
        }

    snapshot["logs"] = build_alert_logs(25)
    snapshot["sms"] = sms_twilio.status_dict()
    return snapshot


def build_sensor_health(has_gas, has_status, severity, serial_connected, smoke_detected=False, snapshot_age_sec=None):
    is_fresh = snapshot_age_sec is not None and snapshot_age_sec <= 10

    if not is_fresh and not serial_connected:
        return {"gas": "Offline", "aqi": "Offline", "smoke": "Offline"}

    if serial_connected:
        gas = "Online" if has_gas else "Waiting"
        aqi = "Active" if has_status else "Waiting"
    else:
        gas = "Simulated" if has_gas else "Waiting"
        aqi = "Simulated" if has_status else "Waiting"

    if smoke_detected:
        smoke = "Alert"
    elif severity == "moderate":
        smoke = "Monitoring"
    else:
        smoke = "Healthy"

    return {"gas": gas, "aqi": aqi, "smoke": smoke}


def build_quick_actions(severity):
    if severity == "critical":
        return [
            {
                "step": "01",
                "accent": "vent",
                "icon": "🌀",
                "short_title": "Ventilation",
                "short_desc": "Flush indoor air now",
                "title": "Increase Indoor Ventilation Immediately",
                "detail": (
                    "Open entry/exit points for cross-ventilation and run exhaust fans at full "
                    "speed to flush contaminated air from the monitored zone."
                ),
                "eta": "0–5 min",
                "urgency": 95,
            },
            {
                "step": "02",
                "accent": "smoke",
                "icon": "🚭",
                "short_title": "Smoke Control",
                "short_desc": "Clear affected zones",
                "title": "Avoid Smoke Exposure in Affected Areas",
                "detail": (
                    "Restrict access to high-risk rooms. Stop smoking, cooking smoke, candles, "
                    "and any combustion activity until gas and AQI values stabilize."
                ),
                "eta": "Immediate",
                "urgency": 90,
            },
            {
                "step": "03",
                "accent": "filter",
                "icon": "⚙️",
                "short_title": "Filtration",
                "short_desc": "Run exhaust & HEPA",
                "title": "Activate Exhaust & Filtration Systems",
                "detail": (
                    "Power on HVAC exhaust, kitchen hoods, and HEPA purifiers. Replace clogged "
                    "filters if airflow is weak to maximize pollutant capture."
                ),
                "eta": "5–10 min",
                "urgency": 85,
            },
            {
                "step": "04",
                "accent": "monitor",
                "icon": "📊",
                "short_title": "AQI Monitor",
                "short_desc": "Track live readings",
                "title": "Monitor AQI Fluctuations Continuously",
                "detail": (
                    "Keep the live dashboard open and review readings every 2–3 minutes. "
                    "Document spikes using the alert export for incident tracking."
                ),
                "eta": "Ongoing",
                "urgency": 80,
            },
            {
                "step": "05",
                "accent": "mask",
                "icon": "😷",
                "short_title": "Protection",
                "short_desc": "Wear N95 / P2 masks",
                "title": "Wear Protective Masks (N95/P2)",
                "detail": (
                    "All occupants in affected areas should wear certified respiratory protection "
                    "until the system reports safe or normal air quality status."
                ),
                "eta": "Until clear",
                "urgency": 88,
            },
        ]

    if severity == "moderate":
        return [
            {
                "step": "01",
                "accent": "vent",
                "icon": "🪟",
                "short_title": "Ventilation",
                "short_desc": "Boost fresh airflow",
                "title": "Boost Ventilation Proactively",
                "detail": "Introduce fresh air before conditions worsen. Partial window opening is often sufficient.",
                "eta": "5 min",
                "urgency": 70,
            },
            {
                "step": "02",
                "accent": "smoke",
                "icon": "🔍",
                "short_title": "Inspection",
                "short_desc": "Find smoke sources",
                "title": "Inspect for Smoke Sources",
                "detail": "Walk through the facility and remove or isolate any visible smoke or odor sources.",
                "eta": "10 min",
                "urgency": 65,
            },
            {
                "step": "03",
                "accent": "filter",
                "icon": "🌬️",
                "short_title": "Filtration",
                "short_desc": "Enable purifiers",
                "title": "Run Filtration Equipment",
                "detail": "Enable air purifiers and check that exhaust pathways are unobstructed.",
                "eta": "5 min",
                "urgency": 60,
            },
            {
                "step": "04",
                "accent": "monitor",
                "icon": "📡",
                "short_title": "AQI Monitor",
                "short_desc": "Check every 15 min",
                "title": "Track AQI Every 15 Minutes",
                "detail": "Watch for upward trends in gas readings that may indicate developing pollution.",
                "eta": "Ongoing",
                "urgency": 55,
            },
            {
                "step": "05",
                "accent": "mask",
                "icon": "👥",
                "short_title": "Occupants",
                "short_desc": "Protect vulnerable people",
                "title": "Protect Sensitive Individuals",
                "detail": "Relocate children, elderly, or respiratory-sensitive occupants to better-ventilated areas.",
                "eta": "As needed",
                "urgency": 50,
            },
        ]

    return [
        {
            "step": "01",
            "accent": "vent",
            "icon": "✅",
            "short_title": "Ventilation",
            "short_desc": "Daily air exchange",
            "title": "Maintain Adequate Ventilation",
            "detail": "Schedule short daily air-exchange cycles to prevent pollutant accumulation.",
            "eta": "Daily",
            "urgency": 30,
        },
        {
            "step": "02",
            "accent": "smoke",
            "icon": "🚭",
            "short_title": "Smoke-Free",
            "short_desc": "Keep areas clean",
            "title": "Keep Areas Smoke-Free",
            "detail": "Enforce no-smoke policies indoors to preserve current safe air quality levels.",
            "eta": "Always",
            "urgency": 25,
        },
        {
            "step": "03",
            "accent": "filter",
            "icon": "🧰",
            "short_title": "Filtration",
            "short_desc": "Service filters",
            "title": "Service Filtration Systems",
            "detail": "Inspect filters monthly and replace per manufacturer guidelines.",
            "eta": "Monthly",
            "urgency": 20,
        },
        {
            "step": "04",
            "accent": "monitor",
            "icon": "📊",
            "short_title": "AQI Trends",
            "short_desc": "Weekly review",
            "title": "Review AQI Trends Weekly",
            "detail": "Use analytics to spot gradual increases before they become alerts.",
            "eta": "Weekly",
            "urgency": 15,
        },
        {
            "step": "05",
            "accent": "mask",
            "icon": "😷",
            "short_title": "PPE Stock",
            "short_desc": "Masks on standby",
            "title": "Keep Masks Available On-Site",
            "detail": "Store N95/P2 masks for rapid deployment if conditions escalate unexpectedly.",
            "eta": "Standby",
            "urgency": 10,
        },
    ]


def build_safety_recommendations(severity, sensor):
    status = (sensor.get("status") or "--").strip()
    gas = (sensor.get("gas") or "--").strip()
    temperature = (sensor.get("temperature") or "--").strip()
    humidity = (sensor.get("humidity") or "--").strip()
    quick_actions = build_quick_actions(severity)

    if severity == "critical":
        meta = {
            "level": "critical",
            "label": "High Risk",
            "headline": "Immediate protective actions required",
            "summary": (
                f"Live sensors report critical conditions (AQI: {status}, Gas: {gas}). "
                "Execute the protocol below to reduce exposure and stabilize indoor air quality."
            ),
        }
        items = [
            {
                "icon": "🌀",
                "category": "Ventilation",
                "title": "Increase fresh air exchange",
                "detail": "Open windows and doors on opposite sides to create cross-flow. Run exhaust fans at maximum capacity for at least 15 minutes.",
                "priority": "high",
            },
            {
                "icon": "😷",
                "category": "Personal Protection",
                "title": "Use N95 or equivalent masks",
                "detail": "Occupants in affected zones should wear certified respiratory protection until gas and AQI readings return to safe levels.",
                "priority": "high",
            },
            {
                "icon": "🚫",
                "category": "Source Control",
                "title": "Eliminate pollution sources",
                "detail": "Stop combustion activities (cooking smoke, candles, incense). Relocate to a ventilated area if readings continue to climb.",
                "priority": "high",
            },
            {
                "icon": "📡",
                "category": "Monitoring",
                "title": "Continuous sensor surveillance",
                "detail": f"Track gas ({gas}), temperature ({temperature}), and humidity ({humidity}) every few minutes. Do not re-enter closed spaces until status improves.",
                "priority": "medium",
            },
            {
                "icon": "🏥",
                "category": "Health Response",
                "title": "Watch for exposure symptoms",
                "detail": "Seek medical guidance if anyone experiences coughing, eye irritation, shortness of breath, or dizziness.",
                "priority": "medium",
            },
            {
                "icon": "📋",
                "category": "Documentation",
                "title": "Log incident for review",
                "detail": "Export the alert report and record time, severity, and actions taken for safety audits and compliance review.",
                "priority": "low",
            },
        ]
    elif severity == "moderate":
        meta = {
            "level": "moderate",
            "label": "Elevated Risk",
            "headline": "Precautionary measures recommended",
            "summary": (
                f"Moderate air quality detected (AQI: {status}, Gas: {gas}). "
                "Apply the guidance below to prevent escalation into critical conditions."
            ),
        }
        items = [
            {
                "icon": "🪟",
                "category": "Ventilation",
                "title": "Improve indoor airflow",
                "detail": "Partially open windows or activate HVAC fresh-air mode to dilute indoor pollutants and lower gas concentration.",
                "priority": "high",
            },
            {
                "icon": "🔍",
                "category": "Inspection",
                "title": "Identify emerging sources",
                "detail": "Check kitchens, workshops, and storage areas for smoke, chemical vapors, or dust that may be elevating sensor readings.",
                "priority": "medium",
            },
            {
                "icon": "⏱",
                "category": "Monitoring",
                "title": "Increase reading frequency",
                "detail": f"Review dashboard metrics every 10–15 minutes. Current temperature {temperature} and humidity {humidity} may influence pollutant behavior.",
                "priority": "medium",
            },
            {
                "icon": "👥",
                "category": "Occupant Safety",
                "title": "Limit sensitive exposure",
                "detail": "Children, elderly individuals, and those with respiratory conditions should reduce time in monitored zones.",
                "priority": "medium",
            },
            {
                "icon": "🧰",
                "category": "Equipment",
                "title": "Service filtration systems",
                "detail": "Verify air purifier filters and ventilation ducts are clean and operational to support pollutant removal.",
                "priority": "low",
            },
        ]
    else:
        meta = {
            "level": "safe",
            "label": "Low Risk",
            "headline": "Environment within safe operating range",
            "summary": (
                f"Sensors indicate stable conditions (AQI: {status}, Gas: {gas}). "
                "Maintain the preventive practices below to keep air quality healthy."
            ),
        }
        items = [
            {
                "icon": "✅",
                "category": "Status",
                "title": "Continue routine monitoring",
                "detail": "Keep the IoT monitoring system active and verify readings at regular intervals throughout the day.",
                "priority": "low",
            },
            {
                "icon": "🌿",
                "category": "Prevention",
                "title": "Sustain ventilation habits",
                "detail": "Schedule brief daily airflow cycles to prevent buildup of humidity and indoor pollutants.",
                "priority": "low",
            },
            {
                "icon": "🧪",
                "category": "Calibration",
                "title": "Verify sensor accuracy",
                "detail": f"Confirm gas ({gas}), temperature ({temperature}), and humidity ({humidity}) readings remain consistent with expected ambient conditions.",
                "priority": "low",
            },
            {
                "icon": "📊",
                "category": "Reporting",
                "title": "Archive baseline metrics",
                "detail": "Export periodic alert reports to establish a reference profile for future anomaly detection.",
                "priority": "low",
            },
        ]

    protocol_title = "Immediate Action Protocol"
    if severity == "moderate":
        protocol_title = "Precautionary Action Protocol"
    elif severity == "safe":
        protocol_title = "Preventive Maintenance Protocol"

    return {
        "meta": meta,
        "quick_actions": quick_actions,
        "protocol_title": protocol_title,
        "items": items,
    }


def build_alert_payload():
    snapshot = get_snapshot()
    severity = snapshot["current_severity"]

    if severity == "critical":
        banner = {
            "title": "⚠ CRITICAL POLLUTION DETECTED",
            "message": (
                "Harmful smoke particles and abnormal AQI/gas levels detected. "
                "Immediate ventilation is strongly recommended."
            ),
            "visible": True,
            "flash": True,
        }
    elif severity == "moderate":
        banner = {
            "title": "🟠 MODERATE AIR QUALITY WARNING",
            "message": (
                "Elevated pollution detected. Monitor conditions and improve ventilation."
            ),
            "visible": True,
            "flash": False,
        }
    else:
        banner = {
            "title": "🟢 ENVIRONMENT STABLE",
            "message": "All sensors report safe operating conditions.",
            "visible": True,
            "flash": False,
        }

    snapshot["banner"] = banner
    snapshot["safety"] = build_safety_recommendations(severity, snapshot["sensor"])
    return snapshot


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/")
def home():
    return render_template("welcome.html")


@app.route("/dashboard")
def dashboard():
    with data_lock:
        gas_value = parse_gas_value(sensor_data.get("gas"))
        display_status = derive_status_from_metrics(
            gas_value, sensor_data.get("status")
        )
        data = dict(sensor_data)
        data["status"] = display_status
        air_quality_level = instantaneous_gas_band(gas_value)
        return render_template(
            "dashboard.html",
            data=data,
            display_status=display_status,
            air_quality_level=air_quality_level,
            gas_critical=GAS_CRITICAL_THRESHOLD,
            gas_moderate=GAS_MODERATE_THRESHOLD,
            gas_safe_max=GAS_SAFE_MAX,
            gas_moderate_max=GAS_MODERATE_MAX,
            gas_poor_max=GAS_POOR_MAX,
        )


def tick_live_simulation():
    """Realistic IoT drift — uses serial when fresh, else smooth simulated stream."""
    global sim_state, last_serial_read, last_smoke_at

    now = datetime.now()
    recent_serial = (
        last_serial_read is not None
        and (now - last_serial_read).total_seconds() < 8
    )

    hour = now.hour
    day_wave = math.sin((hour / 24) * math.pi * 2) * 6
    afternoon_boost = 6 if 11 <= hour <= 19 else 0

    with data_lock:
        if recent_serial:
            gas = parse_gas_value(sensor_data.get("gas"))
            temp = parse_numeric_value(sensor_data.get("temperature"))
            hum = parse_numeric_value(sensor_data.get("humidity"))
            if gas is not None:
                sim_state["gas"] = gas + random.uniform(-1.5, 1.5)
            if temp is not None:
                sim_state["temp"] = temp + random.uniform(-0.3, 0.3)
            if hum is not None:
                sim_state["humidity"] = hum + random.uniform(-0.8, 0.8)
        else:
            for key, target_key, spread in (
                ("gas", "gas_target", 14),
                ("temp", "temp_target", 2.5),
                ("humidity", "hum_target", 6),
            ):
                current = sim_state[key]
                target = sim_state[target_key] + random.uniform(-spread * 0.2, spread * 0.2)
                sim_state[target_key] = max(0, target)
                delta = (target - current) * 0.15 + random.uniform(-spread * 0.08, spread * 0.08)
                sim_state[key] = current + delta

            sim_state["gas"] += day_wave * 0.12 + afternoon_boost * 0.08
            sim_state["gas_target"] = max(160, min(GAS_SAFE_MAX - 15, sim_state["gas_target"]))
            sim_state["gas"] = max(90, min(GAS_SAFE_MAX - 5, sim_state["gas"]))
            sim_state["temp"] = max(20, min(40, sim_state["temp"]))
            sim_state["humidity"] = max(30, min(90, sim_state["humidity"]))

            sensor_data["gas"] = f"{sim_state['gas']:.0f}"
            sensor_data["temperature"] = f"{sim_state['temp']:.1f}"
            sensor_data["humidity"] = f"{sim_state['humidity']:.0f}"
            sensor_data["status"] = derive_status_from_metrics(sim_state["gas"], "--")

    gas_value = parse_gas_value(sensor_data.get("gas"))
    status_label = sensor_data.get("status")
    if gas_value is not None:
        if is_smoke_detected(gas_value, status_label):
            last_smoke_at = datetime.now()
        capture_live_alert_event(
            gas_value,
            status_label if status_label != "--" else None,
        )
    record_sensor_snapshot(force=True)


def analytics_sim_loop():
    while True:
        try:
            tick_live_simulation()
        except Exception as exc:
            print("Analytics sim error:", exc)
        time.sleep(2)


def compute_trend(values, threshold_ratio=0.02):
    if not values or len(values) < 2:
        return "stable"

    recent = values[-3:] if len(values) >= 3 else values
    start = recent[0]
    end = recent[-1]
    if start == 0:
        start = 0.01
    change = (end - start) / abs(start)

    if change > threshold_ratio:
        return "rising"
    if change < -threshold_ratio:
        return "falling"
    return "stable"


def distribution_from_history(history_list):
    if not history_list:
        return {"normal": 68, "moderate": 22, "poor": 10}

    safe = moderate = critical = 0
    for point in history_list:
        gas_val = point.get("gas")
        sev = severity_from_gas(gas_val) if gas_val is not None else point.get("severity", "safe")
        if sev == "critical":
            critical += 1
        elif sev == "moderate":
            moderate += 1
        else:
            safe += 1

    total = safe + moderate + critical
    if total == 0:
        return {"normal": 68, "moderate": 22, "poor": 10}

    return {
        "normal": max(round((safe / total) * 100), 3),
        "moderate": max(round((moderate / total) * 100), 3),
        "poor": max(round((critical / total) * 100), 3),
    }


def build_distribution():
    with data_lock:
        critical = alert_counts.get("critical", 0)
        moderate = alert_counts.get("moderate", 0)
        safe = alert_counts.get("safe", 0)
        total = critical + moderate + safe

    if total == 0:
        return {"normal": 70, "moderate": 20, "poor": 10}

    return {
        "normal": max(round((safe / total) * 100), 5),
        "moderate": max(round((moderate / total) * 100), 5),
        "poor": max(round((critical / total) * 100), 5),
    }


def pollution_index(gas_value, base=120):
    return min(100, max(8, round((gas_value / max(base, 1)) * 42 + 18, 1)))


def generate_smooth_series(base_gas, base_temp, base_hum, count, period):
    """Backward smooth walk ending at current live values."""
    gas, temp, hum, labels = [], [], [], []
    g, t, h = base_gas, base_temp, base_hum

    volatility = {"today": 4, "weekly": 7, "monthly": 5}.get(period, 5)

    for index in range(count - 1, -1, -1):
        g = g + random.uniform(-volatility, volatility)
        t = t + random.uniform(-0.35, 0.35)
        h = h + random.uniform(-1.2, 1.2)
        g = max(50, min(GAS_POOR_MAX, g))
        t = max(21, min(38, t))
        h = max(32, min(88, h))
        gas.insert(0, round(g, 1))
        temp.insert(0, round(t, 1))
        hum.insert(0, round(h, 1))

        if period == "today":
            labels.insert(0, f"-{(count - index) * 20}m")
        elif period == "monthly":
            labels.insert(0, f"W{index + 1}")
        else:
            days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            labels.insert(0, days[index % 7])

    labels[-1] = "Now"
    pollution = [pollution_index(g, base_gas) for g in gas]

    return labels, gas, temp, hum, pollution


def resample_history(history_list, count, period, base_gas, base_temp, base_hum):
    if len(history_list) < 3:
        return generate_smooth_series(base_gas, base_temp, base_hum, count, period)

    points = list(history_list)[-count:]
    if len(points) < count:
        prefix_labels, prefix_gas, prefix_temp, prefix_hum, _ = generate_smooth_series(
            base_gas,
            base_temp,
            base_hum,
            count - len(points),
            period,
        )
        gas = prefix_gas[: count - len(points)]
        temp = prefix_temp[: count - len(points)]
        hum = prefix_hum[: count - len(points)]
        labels = prefix_labels[: count - len(points)]
    else:
        gas, temp, hum, labels = [], [], [], []

    for point in points:
        labels.append(point.get("time", "--"))
        gas.append(point.get("gas") if point.get("gas") is not None else base_gas)
        temp.append(
            point.get("temperature")
            if point.get("temperature") is not None
            else base_temp
        )
        hum.append(
            point.get("humidity") if point.get("humidity") is not None else base_hum
        )

    if labels:
        labels[-1] = "Now"

    pollution = [pollution_index(g, base_gas) for g in gas]
    return labels, gas, temp, hum, pollution


def build_chart_dataset(period, history_list, sensor):
    base_gas = parse_gas_value(sensor.get("gas")) or sim_state["gas"]
    base_temp = parse_numeric_value(sensor.get("temperature")) or sim_state["temp"]
    base_hum = parse_numeric_value(sensor.get("humidity")) or sim_state["humidity"]

    if period == "today":
        count = 12
    elif period == "monthly":
        count = 4
    else:
        count = 7

    return dict(
        zip(
            ("labels", "gas", "temperature", "humidity", "pollution"),
            resample_history(history_list, count, period, base_gas, base_temp, base_hum),
        )
    )


def aqi_gauge_percent(gas_value, severity):
    if severity == "critical":
        return min(96, 70 + (gas_value or 150) / 8)
    if severity == "moderate":
        return min(72, 45 + (gas_value or 120) / 6)
    return max(18, min(42, 25 + (gas_value or 90) / 12))


def build_insights(history_list, severity, trends, sensor):
    insights = []
    status = sensor.get("status", "--")
    gas = parse_gas_value(sensor.get("gas"))

    if severity == "critical":
        insights.append(
            "Critical pollution signature detected — matches smoke/particulate surge patterns."
        )
        insights.append(
            "Peak gas trend is "
            + trends.get("gas", "rising")
            + "; recommend immediate ventilation cycle."
        )
    elif severity == "moderate":
        insights.append(
            "Moderate elevation in gas index — often peaks during afternoon occupancy."
        )
        insights.append(
            "Humidity trend "
            + trends.get("humidity", "stable")
            + " — monitor for compound indoor air quality effects."
        )
    else:
        insights.append(
            "Environmental metrics remain within stable industrial safety band."
        )
        insights.append(
            "Temperature and humidity correlation indicates balanced HVAC performance."
        )

    if trends.get("gas") == "rising":
        eta_text = ""
        try:
            recent = [p for p in history_list if p.get("gas") is not None][-6:]
            if len(recent) >= 2:
                dt = max(1, len(recent) - 1) * 2  # approx sim cadence (2s)
                dv = float(recent[-1]["gas"]) - float(recent[0]["gas"])
                rate = dv / dt
                if rate > 0.3 and gas is not None and gas < GAS_CRITICAL_THRESHOLD:
                    seconds = int((GAS_CRITICAL_THRESHOLD - gas) / rate)
                    if 0 < seconds < 7200:
                        minutes = max(1, round(seconds / 60))
                        eta_text = f" Estimated smoke threshold in ~{minutes} min."
        except Exception:
            eta_text = ""
        insights.append(
            f"Gas index climbing toward {gas or '—'} — early intervention prevents alert escalation.{eta_text}"
        )
    elif trends.get("gas") == "falling":
        insights.append("Gas levels recovering — post-ventilation improvement likely.")

    if len(history_list) >= 5:
        insights.append(
            f"Stream quality: {len(history_list)} samples in rolling buffer · confidence high."
        )

    return insights[:4]


def build_analytics_payload():
    snapshot = get_snapshot()
    sensor = snapshot["sensor"]
    now = datetime.now()

    with data_lock:
        history_list = list(sensor_history)
        total_alerts = sum(alert_counts.values())
        stream_live = serial_connected and last_serial_read and (
            now - last_serial_read
        ).total_seconds() < 10

    distribution = distribution_from_history(history_list)

    gas_values = [p["gas"] for p in history_list if p.get("gas") is not None]
    temp_values = [
        p["temperature"] for p in history_list if p.get("temperature") is not None
    ]
    hum_values = [p["humidity"] for p in history_list if p.get("humidity") is not None]

    live_gas = parse_gas_value(sensor.get("gas")) or (gas_values[-1] if gas_values else 95)
    avg_gas = round(sum(gas_values) / len(gas_values), 1) if gas_values else live_gas
    peak_gas = max(gas_values) if gas_values else live_gas

    trends = {
        "gas": compute_trend(gas_values or [live_gas]),
        "temperature": compute_trend(temp_values or [sim_state["temp"]]),
        "humidity": compute_trend(hum_values or [sim_state["humidity"]]),
    }

    gas_value = parse_gas_value(sensor.get("gas"))
    display_status = snapshot.get("display_status") or derive_status_from_metrics(
        gas_value, sensor.get("status")
    )
    severity = resolve_current_severity(gas_value, display_status)
    updated_seconds = 0
    if last_snapshot_at:
        updated_seconds = int((now - last_snapshot_at).total_seconds())

    return {
        "sensor": sensor,
        "severity": severity,
        "stream": {
            "label": "LIVE SENSOR STREAM" if stream_live else "SIMULATED IoT STREAM",
            "live": stream_live,
            "updated_seconds_ago": updated_seconds,
            "updated_at": now.isoformat(),
        },
        "gauge": {
            "percent": round(aqi_gauge_percent(live_gas, severity), 1),
            "aqi_index": round(live_gas),
        },
        "kpis": {
            "avg_gas": avg_gas,
            "peak_gas": peak_gas,
            "safe_percent": snapshot["summary"]["safe_percent"],
            "alert_count": total_alerts,
            "temperature": sensor.get("temperature", "--"),
            "humidity": sensor.get("humidity", "--"),
            "status": display_status,
            "trends": trends,
        },
        "display_status": display_status,
        "distribution": distribution,
        "insights": build_insights(history_list, severity, trends, sensor),
        "datasets": {
            "today": build_chart_dataset("today", history_list, sensor),
            "weekly": build_chart_dataset("weekly", history_list, sensor),
            "monthly": build_chart_dataset("monthly", history_list, sensor),
        },
        "history_points": len(history_list),
        "thresholds": {
            "safe_max": GAS_SAFE_MAX,
            "moderate": GAS_MODERATE_THRESHOLD,
            "moderate_max": GAS_MODERATE_MAX,
            "critical": GAS_CRITICAL_THRESHOLD,
            "poor_max": GAS_POOR_MAX,
        },
    }


@app.route("/analytics")
def analytics():
    payload = build_analytics_payload()
    return render_template(
        "analytics.html",
        analytics_json=json.dumps(payload),
    )


@app.route("/api/analytics")
def api_analytics():
    return jsonify(build_analytics_payload())


@app.route("/settings")
def settings_page():
    return render_template(
        "settings.html",
        settings_json=json.dumps(settings_store.public_settings(settings_store.load_settings())),
    )


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(settings_store.public_settings(settings_store.load_settings()))


@app.route("/api/settings", methods=["POST"])
def api_settings_save():
    payload = request.get_json(silent=True) or {}
    normalized = settings_store.normalize_payload(payload)
    errors = settings_store.validate_settings(normalized)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    old_port = SERIAL_PORT
    settings_store.save_settings(normalized)
    apply_runtime_settings(normalized)

    if normalized["serial_port"] != old_port:
        reconnect_serial_port()

    return jsonify(
        {
            "ok": True,
            "message": "Settings saved and applied.",
            "settings": settings_store.public_settings(normalized),
            "serial_connected": serial_connected,
        }
    )


@app.route("/api/settings/reconnect-serial", methods=["POST"])
def api_settings_reconnect_serial():
    reconnect_serial_port()
    return jsonify({"ok": True, "serial_connected": serial_connected, "serial_port": SERIAL_PORT})


@app.route("/alerts")
def alerts():
    payload = build_alert_payload()
    return render_template(
        "alerts.html",
        data=payload["sensor"],
        summary=payload["summary"],
        logs=payload["logs"],
        sensors=payload["sensors"],
        banner=payload["banner"],
        safety=payload["safety"],
        current_severity=payload["current_severity"],
        alert_json=json.dumps(payload),
    )


@app.route("/api/sensor")
def api_sensor():
    with data_lock:
        return jsonify(dict(sensor_data))


@app.route("/api/alerts")
def api_alerts():
    return jsonify(build_alert_payload())


@app.route("/api/sms/status")
def api_sms_status():
    return jsonify(sms_twilio.status_dict())


@app.route("/api/sms/test", methods=["POST"])
def api_sms_test():
    if os.environ.get("TWILIO_ALLOW_TEST", "").lower() not in ("1", "true", "yes", "on"):
        return jsonify({"ok": False, "error": "Set TWILIO_ALLOW_TEST=1 in .env to enable test SMS"}), 403
    try:
        sid = sms_twilio.send_test_sms()
        return jsonify({"ok": True, "sid": sid, "status": sms_twilio.status_dict()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/debug/set_gas", methods=["POST"])
def api_debug_set_gas():
    """Debug-only: force gas value to trigger alert/SMS flows."""
    if os.environ.get("DEBUG_ALLOW_SET_GAS", "").lower() not in ("1", "true", "yes", "on"):
        return jsonify({"ok": False, "error": "Set DEBUG_ALLOW_SET_GAS=1 in .env to enable"}), 403

    payload = request.get_json(silent=True) or {}
    value = payload.get("gas")
    gas_value = parse_gas_value(value)
    if gas_value is None:
        return jsonify({"ok": False, "error": "Provide JSON body like {\"gas\": 300}"}), 400

    update_sensor_field("gas", str(int(round(gas_value))))
    return jsonify({"ok": True, "sensor": get_snapshot()["sensor"], "status": get_snapshot().get("display_status")})


@app.route("/api/debug/payload_keys")
def api_debug_payload_keys():
    if os.environ.get("DEBUG_ALLOW_SET_GAS", "").lower() not in ("1", "true", "yes", "on"):
        return jsonify({"ok": False, "error": "Set DEBUG_ALLOW_SET_GAS=1 in .env to enable"}), 403
    payload = build_alert_payload()
    return jsonify({"ok": True, "keys": sorted(list(payload.keys()))})


@app.route("/api/build")
def api_build():
    """Verify the running server is this project copy."""
    dash_path = os.path.join(app.root_path, "templates", "dashboard.html")
    tag = "unknown"
    try:
        with open(dash_path, encoding="utf-8") as f:
            head = f.read(8000)
            if "Build v13" in head:
                tag = "Build v13"
            elif "Build v12" in head:
                tag = "Build v12"
            elif "Build v11" in head:
                tag = "Build v11"
            elif "Layout v10" in head:
                tag = "Layout v10"
            elif "Layout v" in head:
                import re

                m = re.search(r"Layout v[\d.]+", head)
                tag = m.group(0) if m else "old"
    except OSError:
        tag = "missing"

    analytics_tag = "unknown"
    analytics_path = os.path.join(app.root_path, "templates", "analytics.html")
    try:
        with open(analytics_path, encoding="utf-8") as f:
            ahead = f.read(4000)
            if "Analytics Grid v4" in ahead or "60% left" in ahead:
                analytics_tag = "Analytics Grid v4"
            elif "Analytics Grid v3" in ahead or "no scroll" in ahead:
                analytics_tag = "Analytics Grid v3"
            elif "Analytics Grid v2" in ahead:
                analytics_tag = "Analytics Grid v2"
            elif "Analytics Grid v1" in ahead:
                analytics_tag = "Analytics Grid v1"
            elif "analytics-layout.css" in ahead:
                analytics_tag = "analytics-layout (legacy)"
    except OSError:
        analytics_tag = "missing"

    return jsonify(
        {
            "build": DASHBOARD_BUILD,
            "dashboard_tag": tag,
            "analytics_tag": analytics_tag,
            "gas_profile": _GAS_PROFILE,
            "gas_thresholds": {
                "safe_max": GAS_SAFE_MAX,
                "moderate": GAS_MODERATE_THRESHOLD,
                "moderate_max": GAS_MODERATE_MAX,
                "critical": GAS_CRITICAL_THRESHOLD,
                "poor_max": GAS_POOR_MAX,
            },
            "root": app.root_path,
            "template": dash_path,
        }
    )


connect_serial()
reader_thread = threading.Thread(target=serial_reader_loop, daemon=True)
reader_thread.start()
analytics_thread = threading.Thread(target=analytics_sim_loop, daemon=True)
analytics_thread.start()

if __name__ == "__main__":
    dash_file = os.path.join(app.root_path, "templates", "dashboard.html")
    print("=" * 50)
    print("AQ Monitor Flask")
    print("  Root:", os.path.abspath(app.root_path))
    print("  Dashboard template:", os.path.abspath(dash_file))
    print(f"  Gas sensor profile: {_GAS_PROFILE.upper()} (MQ-2 = high thresholds)")
    print(
        f"  Bands: Safe 0–{GAS_SAFE_MAX} | Moderate {GAS_MODERATE_THRESHOLD}–{GAS_MODERATE_MAX}"
        f" | Poor {GAS_CRITICAL_THRESHOLD}+"
    )
    sms = sms_twilio.status_dict()
    if sms["enabled"]:
        print(f"  Twilio SMS: ON ({sms['recipients']} recipient(s), cooldown {sms['cooldown_sec']}s)")
    elif sms["configured"]:
        print("  Twilio SMS: configured but TWILIO_ENABLED=off")
    else:
        print("  Twilio SMS: off (set TWILIO_* in .env to enable)")
    print("  Open: http://127.0.0.1:5000/dashboard")
    print("  Verify: http://127.0.0.1:5000/api/build")
    print("=" * 50)
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    print(f"  LAN (phone/PWA): http://<your-pc-ip>:{port}/dashboard")
    app.run(host=host, port=port, debug=False)
