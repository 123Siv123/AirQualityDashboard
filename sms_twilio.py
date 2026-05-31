"""Twilio SMS alerts for AQ Monitor (optional, env-configured)."""

import os
import threading
from datetime import datetime

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

_sms_lock = threading.Lock()
_last_sms_at = None
_last_sms_key = None
_last_sms_error = None
_last_sms_ok_at = None
_sms_send_count = 0

COOLDOWN_SEC = int(os.environ.get("TWILIO_SMS_COOLDOWN_SEC", "300"))
SMS_ON_MODERATE = os.environ.get("TWILIO_SMS_MODERATE", "").lower() in ("1", "true", "yes", "on")
SKIP_SENSORS = frozenset({"Live Stream", "Telemetry", "System"})


def reload_config():
    """Reload Twilio flags after settings change."""
    global COOLDOWN_SEC, SMS_ON_MODERATE
    COOLDOWN_SEC = int(os.environ.get("TWILIO_SMS_COOLDOWN_SEC", "300"))
    SMS_ON_MODERATE = os.environ.get("TWILIO_SMS_MODERATE", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _parse_numbers():
    raw = os.environ.get("TWILIO_TO_NUMBER") or os.environ.get("TWILIO_ALERT_NUMBERS", "")
    return [n.strip() for n in raw.replace(";", ",").split(",") if n.strip()]


def is_configured():
    return bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
        and os.environ.get("TWILIO_FROM_NUMBER")
        and _parse_numbers()
    )


def sms_enabled():
    flag = os.environ.get("TWILIO_ENABLED", "auto").lower().strip()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return is_configured()
    return is_configured()


def _severity_allowed(severity):
    if severity == "critical":
        return True
    if severity == "moderate" and SMS_ON_MODERATE:
        return True
    return False


def status_dict():
    """Safe status for API (no secrets)."""
    numbers = _parse_numbers()
    return {
        "enabled": sms_enabled(),
        "configured": is_configured(),
        "recipients": len(numbers),
        "moderate_sms": SMS_ON_MODERATE,
        "cooldown_sec": COOLDOWN_SEC,
        "last_sent_iso": _last_sms_ok_at.isoformat() if _last_sms_ok_at else None,
        "last_error": _last_sms_error,
        "send_count": _sms_send_count,
    }


def maybe_send_alert(sensor, severity, detail):
    """Queue SMS for important sensor events (non-blocking)."""
    if not sms_enabled():
        return
    if sensor in SKIP_SENSORS:
        return
    if not _severity_allowed(severity):
        return

    threading.Thread(
        target=_send_sms,
        args=(severity, detail),
        daemon=True,
    ).start()


def send_test_sms(message=None):
    """Send a test SMS (raises if not configured). Returns message SID or error text."""
    if not is_configured():
        raise RuntimeError("Twilio is not configured. Set credentials in .env")
    body = message or "AQ Monitor: Twilio SMS test — alerts are connected."
    return _send_sms_sync("safe", body, force=True)


def _send_sms(severity, detail, force=False):
    global _last_sms_at, _last_sms_key, _last_sms_error, _last_sms_ok_at, _sms_send_count

    if not force and not sms_enabled():
        return

    now = datetime.now()
    with _sms_lock:
        key = f"{severity}|{detail}"
        if not force and _last_sms_key == key and _last_sms_ok_at and (now - _last_sms_ok_at).total_seconds() < 15:
            return
        if (
            not force
            and _last_sms_at
            and (now - _last_sms_at).total_seconds() < COOLDOWN_SEC
        ):
            return

    try:
        sid = _send_sms_sync(severity, detail, force=force)
        with _sms_lock:
            _last_sms_at = now
            _last_sms_key = key
            _last_sms_error = None
            _last_sms_ok_at = datetime.now()
            _sms_send_count += 1
        return sid
    except Exception as exc:
        with _sms_lock:
            _last_sms_error = str(exc)
        print("Twilio SMS error:", exc)
        return None


def _send_sms_sync(severity, detail, force=False):
    from twilio.rest import Client

    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_FROM_NUMBER"]
    recipients = _parse_numbers()

    label = severity.upper() if severity else "ALERT"
    body = f"AQ Monitor [{label}]: {detail}"
    if len(body) > 1500:
        body = body[:1497] + "..."

    client = Client(account_sid, auth_token)
    last_sid = None
    for to_number in recipients:
        msg = client.messages.create(body=body, from_=from_number, to=to_number)
        last_sid = msg.sid
    return last_sid
