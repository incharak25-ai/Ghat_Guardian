"""
GHAT-GUARDIAN Emergency Alert Dispatcher
Patent Claim 4: Automated geo-targeted multi-channel emergency dispatch.

When MPU6050 detects crash → this module fires within 2 seconds:
  1. SMS  via MSG91 (Indian carrier, ₹0.20/SMS)
  2. WhatsApp via Meta Cloud API
  3. WebSocket alarm to rescue dashboard

Set these in Replit Secrets:
  MSG91_AUTH_KEY      → from msg91.com dashboard
  MSG91_SENDER_ID     → 6-char sender ID e.g. GHATGD
  MSG91_TEMPLATE_ID   → approved DLT template ID
  WHATSAPP_TOKEN      → Meta WhatsApp Cloud API token
  WHATSAPP_PHONE_ID   → Meta phone number ID
  ALERT_PHONE_NUMBERS → comma-separated fallback numbers e.g. +919876543210,+918765432109
"""

import logging
import requests
from celery import shared_task
from django.conf import settings
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────

def google_maps_link(lat, lng):
    return f"https://maps.google.com/?q={lat},{lng}"

def format_sms(vehicle_id, lat, lng, trigger, nearest_unit, eta_minutes, triggered_at):
    """Build SMS message with crash details — kept under 160 chars for single SMS."""
    trigger_txt = "AUTO-CRASH DETECTED" if trigger == "AUTO_IMU" else "MANUAL SOS"
    return (
        f"GHAT-GUARDIAN SOS\n"
        f"Vehicle: {vehicle_id}\n"
        f"Type: {trigger_txt}\n"
        f"Location: {lat:.5f}, {lng:.5f}\n"
        f"Maps: {google_maps_link(lat, lng)}\n"
        f"Nearest unit: {nearest_unit}\n"
        f"ETA: {eta_minutes} min\n"
        f"Time: {triggered_at}"
    )


# ── MSG91 SMS (India) ─────────────────────────────────────────────────────

def send_sms_msg91(phone_numbers: list, message: str) -> bool:
    """
    Send SMS via MSG91 — best for India.
    Docs: https://docs.msg91.com/reference/send-sms
    Free trial: 100 SMS. Production: ₹0.20/SMS.

    Args:
        phone_numbers: list of strings e.g. ['+919876543210']
        message:       SMS body text
    Returns:
        True if successful
    """
    auth_key    = getattr(settings, 'MSG91_AUTH_KEY', '')
    sender_id   = getattr(settings, 'MSG91_SENDER_ID', 'GHATGD')
    template_id = getattr(settings, 'MSG91_TEMPLATE_ID', '')

    if not auth_key:
        logger.warning("MSG91_AUTH_KEY not set — SMS not sent")
        return False

    recipients = [{"mobiles": num.replace('+', '').replace(' ', '')} for num in phone_numbers]

    payload = {
        "template_id": template_id,
        "short_url":   "0",
        "realTimeResponse": "1",
        "recipients":  recipients,
        "message":     message,
        "sender":      sender_id,
    }

    try:
        resp = requests.post(
            "https://api.msg91.com/api/v5/flow/",
            json=payload,
            headers={
                "authkey":      auth_key,
                "content-type": "application/json",
            },
            timeout=5,
        )
        data = resp.json()
        if data.get("type") == "success":
            logger.info(f"SMS sent to {phone_numbers} via MSG91")
            return True
        else:
            logger.error(f"MSG91 error: {data}")
            return False
    except Exception as e:
        logger.error(f"MSG91 request failed: {e}")
        return False


# ── Twilio SMS fallback ───────────────────────────────────────────────────

def send_sms_twilio(phone_numbers: list, message: str) -> bool:
    """
    Fallback SMS via Twilio if MSG91 fails.
    Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER in Replit Secrets.
    """
    sid   = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN',  '')
    from_ = getattr(settings, 'TWILIO_FROM_NUMBER', '')

    if not all([sid, token, from_]):
        logger.warning("Twilio credentials not set — skipping Twilio fallback")
        return False

    success = True
    for num in phone_numbers:
        try:
            resp = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"From": from_, "To": num, "Body": message},
                timeout=5,
            )
            if resp.status_code == 201:
                logger.info(f"Twilio SMS sent to {num}")
            else:
                logger.error(f"Twilio error for {num}: {resp.text}")
                success = False
        except Exception as e:
            logger.error(f"Twilio request failed for {num}: {e}")
            success = False
    return success


# ── WhatsApp via Meta Cloud API ───────────────────────────────────────────

def send_whatsapp(phone_numbers: list, vehicle_id: str, lat: float, lng: float,
                  nearest_unit: str, eta_minutes: int) -> bool:
    """
    Send WhatsApp message with location to rescue units.
    Uses Meta WhatsApp Cloud API (free tier: 1000 conversations/month).
    Setup: https://developers.facebook.com/docs/whatsapp/cloud-api

    Set WHATSAPP_TOKEN and WHATSAPP_PHONE_ID in Replit Secrets.
    """
    token    = getattr(settings, 'WHATSAPP_TOKEN',    '')
    phone_id = getattr(settings, 'WHATSAPP_PHONE_ID', '')

    if not all([token, phone_id]):
        logger.warning("WhatsApp credentials not set — skipping WhatsApp alert")
        return False

    # Message text
    body = (
        f"🆘 *GHAT-GUARDIAN EMERGENCY*\n\n"
        f"*Vehicle:* {vehicle_id}\n"
        f"*Location:* {lat:.5f}, {lng:.5f}\n"
        f"*Maps:* {google_maps_link(lat, lng)}\n"
        f"*Nearest unit:* {nearest_unit}\n"
        f"*ETA:* {eta_minutes} minutes\n\n"
        f"_Auto-dispatched by Ghat-Guardian Safety System_"
    )

    success = True
    for num in phone_numbers:
        clean_num = num.replace('+', '').replace(' ', '')
        payload = {
            "messaging_product": "whatsapp",
            "to":                clean_num,
            "type":              "text",
            "text":              {"body": body},
        }
        try:
            resp = requests.post(
                f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
                timeout=5,
            )
            if resp.status_code == 200:
                logger.info(f"WhatsApp sent to {num}")
            else:
                logger.error(f"WhatsApp error for {num}: {resp.text}")
                success = False
        except Exception as e:
            logger.error(f"WhatsApp request failed for {num}: {e}")
            success = False
    return success


# ── Dashboard WebSocket alarm ─────────────────────────────────────────────

def trigger_dashboard_alarm(sos_payload: dict):
    """
    Send alarm event to rescue dashboard via Redis WebSocket.
    Dashboard plays the Web Audio siren when this arrives.
    """
    channel_layer = get_channel_layer()
    try:
        async_to_sync(channel_layer.group_send)(
            'rescue_coordination',
            {
                'type':    'sos_alert',
                'payload': {
                    **sos_payload,
                    'alarm': True,   # ← tells dashboard to play siren
                }
            }
        )
        logger.info("Dashboard alarm triggered via WebSocket")
    except Exception as e:
        logger.error(f"Dashboard alarm failed: {e}")


# ── Main Celery task ──────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def dispatch_emergency_alerts(self, sos_data: dict):
    """
    CELERY TASK — called by views.py when SOS fires.
    Runs asynchronously so the ESP32 API response isn't delayed.

    Fires all 3 alert channels simultaneously:
      1. SMS  → nearest rescue unit phone number
      2. WhatsApp → rescue unit WhatsApp number
      3. WebSocket → rescue dashboard alarm sound

    Args:
        sos_data: dict with vehicle_id, lat, lng, trigger,
                  nearest_unit, eta_minutes, triggered_at,
                  rescue_phone, rescue_whatsapp
    """
    vehicle_id    = sos_data.get('vehicle_id', 'UNKNOWN')
    lat           = float(sos_data.get('lat', 0))
    lng           = float(sos_data.get('lng', 0))
    trigger       = sos_data.get('trigger', 'AUTO_IMU')
    nearest_unit  = sos_data.get('nearest_unit', 'Nearest Unit')
    eta_minutes   = sos_data.get('eta_minutes', 10)
    triggered_at  = sos_data.get('triggered_at', '')
    rescue_phones = sos_data.get('rescue_phones', [])     # list of phone numbers
    rescue_wa     = sos_data.get('rescue_whatsapp', [])   # list of WhatsApp numbers

    # Also include fallback numbers from settings
    fallback = getattr(settings, 'ALERT_PHONE_NUMBERS', '')
    if fallback:
        rescue_phones += [n.strip() for n in fallback.split(',') if n.strip()]

    message = format_sms(vehicle_id, lat, lng, trigger, nearest_unit, eta_minutes, triggered_at)

    logger.critical(
        f"EMERGENCY DISPATCH: {vehicle_id} at ({lat}, {lng}) "
        f"— {trigger} — ETA {eta_minutes}min to {nearest_unit}"
    )

    results = {
        'sms':       False,
        'whatsapp':  False,
        'dashboard': False,
    }

    # 1. SMS via MSG91 (fallback to Twilio)
    if rescue_phones:
        results['sms'] = send_sms_msg91(rescue_phones, message)
        if not results['sms']:
            logger.warning("MSG91 failed — trying Twilio fallback")
            results['sms'] = send_sms_twilio(rescue_phones, message)
    else:
        logger.warning("No rescue phone numbers configured — SMS not sent")

    # 2. WhatsApp
    if rescue_wa:
        results['whatsapp'] = send_whatsapp(
            rescue_wa, vehicle_id, lat, lng, nearest_unit, eta_minutes
        )

    # 3. Dashboard WebSocket alarm
    results['dashboard'] = True
    trigger_dashboard_alarm(sos_data)

    logger.info(f"Alert dispatch results: {results}")
    return results


# ── Helper: get rescue unit contact numbers ───────────────────────────────

def get_rescue_contacts(rescue_unit_id: int) -> dict:
    """
    Fetch phone and WhatsApp numbers for a RescueUnit from the DB.
    Called by views.py before firing the Celery task.
    """
    from vehicles.models import RescueUnit
    try:
        unit = RescueUnit.objects.get(pk=rescue_unit_id)
        return {
            'phones':    [unit.contact]   if unit.contact   else [],
            'whatsapp':  [unit.whatsapp]  if hasattr(unit, 'whatsapp') and unit.whatsapp else [],
        }
    except RescueUnit.DoesNotExist:
        return {'phones': [], 'whatsapp': []}
