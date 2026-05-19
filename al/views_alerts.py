"""
GHAT-GUARDIAN API Views
REST endpoints that the ESP32 calls every second.
After saving data, broadcasts to WebSocket via Redis channel layer.

V2V Communication Note:
------------------------
The current version uses SERVER-SIDE V2V SIMULATION.
The backend identifies nearby vehicles using GPS + PostGIS and generates
simulated V2V warning messages delivered through the dashboard WebSocket.

The nRF24L01+ hardware module is NOT used in this version.
Real nRF24L01+ based vehicle-to-vehicle wireless communication
will be added as a future hardware enhancement (future scope).

Sensor coverage:
  GPS (NEO-6M)     → lat, lng, speed, heading → PostGIS PointField
  MPU6050          → crash flag → /api/sos/ → SOSAlert model
  BME280           → temperature, humidity → VehicleTelemetry model
  LM393 LDR        → ambient_light → VehicleTelemetry model
  KY-008 Laser     → fog_visibility → ml_engine risk calculation
  SOS Push Button  → trigger=MANUAL_BUTTON → /api/sos/ endpoint

Output devices (controlled by ESP32 firmware, not backend):
  SSD1306 OLED     → displays condition based on risk_level returned
  Active Buzzer    → triggered by firmware on CRITICAL risk
  Green/Yellow/Red LEDs → firmware switches based on led_status field
"""

import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Vehicle, VehicleTelemetry, SOSAlert, RescueUnit, BlackSpot
from .serializers import (SOSAlertSerializer, BlackSpotSerializer, RescueUnitSerializer)
from .ml_engine import calculate_overall_risk, calculate_rescue_eta, haversine_distance

logger = logging.getLogger(__name__)
channel_layer = get_channel_layer()

# ── LED status map — returned to ESP32 so firmware knows which LED to light ──
# GREEN  = GPIO18 (normal operation)
# YELLOW = GPIO19 (warning — fog, black spot, nearby vehicle)
# RED    = GPIO23 (critical — collision imminent, SOS)
LED_STATUS_MAP = {
    'LOW':      'GREEN',
    'MEDIUM':   'YELLOW',
    'HIGH':     'YELLOW',
    'CRITICAL': 'RED',
}

# ── Server-side V2V simulation thresholds ────────────────────────────────────
# These replace nRF24L01+ hardware in the current version.
# When two vehicles are within these distances, the backend generates
# a simulated V2V warning and delivers it through the dashboard WebSocket.
V2V_WARN_DISTANCE_M  = 500   # Generate V2V alert when vehicles within 500m
V2V_CLOSE_DISTANCE_M = 150   # Critical V2V alert when within 150m


def generate_server_side_v2v_alert(
    vehicle_id: str,
    nearby_vehicles: list,
    ttc_result: dict
) -> str | None:
    """
    SERVER-SIDE V2V SIMULATION (replaces nRF24L01+ hardware).

    In real V2V (future scope), the nRF24L01+ radio on each ESP32 would
    broadcast a 32-byte packet directly to nearby vehicles over 2.4GHz mesh.

    In this version, the backend simulates this by:
    1. Using PostGIS ST_DWithin to find vehicles within 500m
    2. Checking TTC from ml_engine
    3. Generating a warning message delivered via WebSocket dashboard

    The warning reaches the driver through the dashboard and driver mobile app
    instead of directly through the nRF24L01+ radio.

    Args:
        vehicle_id:      Current vehicle ID
        nearby_vehicles: List of nearby vehicle dicts from PostGIS query
        ttc_result:      TTC calculation result from ml_engine
    Returns:
        Warning message string or None
    """
    if not nearby_vehicles:
        return None

    closest = nearby_vehicles[0]  # Already sorted by distance in query
    dist_m  = closest.get('distance_m', 999)

    # TTC-based warning (most urgent)
    if ttc_result and ttc_result.get('ttc_seconds'):
        ttc = ttc_result['ttc_seconds']
        if ttc <= 3:
            return (f"[SERVER V2V] COLLISION IMMINENT with {closest['vehicle_id']} "
                    f"— {ttc:.1f}s — BRAKE NOW")
        elif ttc <= 6:
            return (f"[SERVER V2V] {closest['vehicle_id']} approaching fast "
                    f"— {ttc:.1f}s to collision — Slow down")
        elif ttc <= 10:
            return (f"[SERVER V2V] Vehicle {closest['vehicle_id']} detected ahead "
                    f"— {ttc:.1f}s — Caution")

    # Distance-based warning (when TTC not yet critical)
    if dist_m <= V2V_CLOSE_DISTANCE_M:
        return (f"[SERVER V2V] Vehicle {closest['vehicle_id']} very close "
                f"— {dist_m:.0f}m away")
    elif dist_m <= V2V_WARN_DISTANCE_M:
        return (f"[SERVER V2V] Vehicle {closest['vehicle_id']} nearby "
                f"— {dist_m:.0f}m — Monitor speed")

    return None


def process_telemetry_data(data: dict) -> dict:
    """
    Core processing function — called by both REST API and WebSocket consumer.

    Pipeline:
    1. Parse incoming ESP32 GPS + sensor data
    2. Find nearby vehicles via PostGIS ST_DWithin (server-side V2V)
    3. Run ML risk engine (TTC + fog + black spot)
    4. Generate server-side V2V simulation alert if needed
    5. Compute LED status for ESP32 firmware
    6. Save to PostGIS database
    7. Broadcast full payload to rescue dashboard via Redis WebSocket

    Args:
        data: dict — incoming JSON from ESP32 or simulator
    Returns:
        payload dict — broadcasted to dashboard
    """
    vehicle_id = data.get('vehicle_id', 'UNKNOWN')
    lat        = float(data.get('lat', 0))
    lng        = float(data.get('lng', 0))
    speed      = float(data.get('speed', 0))
    heading    = float(data.get('heading', 0))

    current_point = Point(lng, lat, srid=4326)

    # ── Step 1: Find nearby vehicles (PostGIS ST_DWithin) ─────────────────
    # This is the server-side equivalent of nRF24L01+ discovery.
    # We look for any vehicle that sent a GPS update in the last 5 seconds
    # AND is within 1km of the current vehicle.
    recent_cutoff = timezone.now() - timezone.timedelta(seconds=5)
    nearby_qs = (VehicleTelemetry.objects
                 .filter(timestamp__gte=recent_cutoff)
                 .exclude(vehicle__vehicle_id=vehicle_id)
                 .filter(location__distance_lte=(current_point, Distance(m=1000)))
                 .select_related('vehicle')
                 .order_by('location'))   # Closest first

    nearby_vehicles = []
    for t in nearby_qs:
        dist = haversine_distance(lat, lng, t.location.y, t.location.x)
        nearby_vehicles.append({
            'vehicle_id':  t.vehicle.vehicle_id,
            'lat':         t.location.y,
            'lng':         t.location.x,
            'speed':       t.speed,
            'heading':     t.heading,
            'distance_m':  dist,
        })

    # ── Step 2: Run ML risk engine ────────────────────────────────────────
    risk_result = calculate_overall_risk(
        telemetry_data={
            'lat':            lat,
            'lng':            lng,
            'speed':          speed,
            'heading':        heading,
            'fog_visibility': data.get('fog_visibility'),
        },
        nearby_vehicles=nearby_vehicles
    )

    # ── Step 3: Black Spot check (PostGIS ST_Contains) ────────────────────
    in_black_spot = BlackSpot.objects.filter(
        zone__contains=current_point
    ).first()

    if in_black_spot:
        if risk_result['risk_level'] in ['LOW', 'MEDIUM']:
            risk_result['risk_level'] = 'HIGH'
        risk_result['warning'] = risk_result['warning'] or in_black_spot.warning_msg

    # ── Step 4: Server-side V2V simulation ───────────────────────────────
    # Generates the alert that nRF24L01+ would have sent over the air.
    # Delivered via WebSocket dashboard instead of radio.
    ttc_result  = risk_result.get('ttc_result')
    v2v_alert   = generate_server_side_v2v_alert(vehicle_id, nearby_vehicles, ttc_result)

    # ── Step 5: Compute LED status for ESP32 firmware ─────────────────────
    # Backend sends this back so the firmware knows which GPIO to trigger:
    # GPIO18 = GREEN (LOW risk), GPIO19 = YELLOW (MEDIUM/HIGH), GPIO23 = RED (CRITICAL)
    led_status  = LED_STATUS_MAP.get(risk_result['risk_level'], 'GREEN')

    # ── Step 6: Save to PostGIS ───────────────────────────────────────────
    vehicle, _  = Vehicle.objects.get_or_create(vehicle_id=vehicle_id)
    telemetry   = VehicleTelemetry.objects.create(
        vehicle        = vehicle,
        location       = current_point,
        speed          = speed,
        heading        = heading,
        temperature    = data.get('temperature'),
        humidity       = data.get('humidity'),
        ambient_light  = data.get('ambient_light'),
        fog_visibility = data.get('fog_visibility'),
        risk_level     = risk_result['risk_level'],
        warning        = risk_result['warning'],
        sos_active     = bool(data.get('sos_active', False)),
        v2v_alert      = v2v_alert,   # Server-generated, not from hardware radio
    )

    # ── Step 7: Build and broadcast payload to rescue dashboard ──────────
    payload = {
        'vehicle_id':    vehicle_id,
        'lat':           lat,
        'lng':           lng,
        'speed':         telemetry.speed,
        'heading':       telemetry.heading,

        # Risk engine output
        'risk_level':    telemetry.risk_level,
        'warning':       telemetry.warning,

        # Sensor readings (from ESP32 hardware)
        'fog_visibility': telemetry.fog_visibility,   # KY-008 Laser + LDR
        'temperature':   telemetry.temperature,        # BME280
        'humidity':      telemetry.humidity,           # BME280
        'ambient_light': telemetry.ambient_light,      # LM393 LDR

        # Status flags
        'sos_active':    telemetry.sos_active,

        # Server-side V2V simulation output
        # NOTE: In future scope, this will come from nRF24L01+ hardware radio
        'v2v_alert':     v2v_alert,
        'v2v_mode':      'SERVER_SIMULATION',  # Clearly marks current V2V method

        # TTC details for dashboard panels
        'ttc_seconds':   ttc_result.get('ttc_seconds') if ttc_result else None,
        'nearby_count':  len(nearby_vehicles),
        'nearby_vehicles': [
            {'vehicle_id': v['vehicle_id'], 'distance_m': round(v['distance_m'], 1)}
            for v in nearby_vehicles
        ],

        # Black spot info
        'in_black_spot': in_black_spot.name if in_black_spot else None,

        # LED status — returned to ESP32 firmware via WebSocket response
        # GREEN=GPIO18 (normal), YELLOW=GPIO19 (warning), RED=GPIO23 (critical/SOS)
        'led_status':    led_status,

        'timestamp':     telemetry.timestamp.isoformat(),
    }

    # ── Broadcast telemetry to all rescue dashboards ──────────────────────
    async_to_sync(channel_layer.group_send)(
        'rescue_coordination',
        {'type': 'telemetry_update', 'payload': payload}
    )

    # ── Broadcast V2V alert separately to V2V Message Panel ──────────────
    if v2v_alert:
        async_to_sync(channel_layer.group_send)(
            'rescue_coordination',
            {
                'type': 'v2v_alert',
                'payload': {
                    'from_vehicle': vehicle_id,
                    'alert':        v2v_alert,
                    'mode':         'SERVER_SIMULATION',
                    'nearby':       [v['vehicle_id'] for v in nearby_vehicles],
                    'timestamp':    telemetry.timestamp.isoformat(),
                }
            }
        )

    return payload


# ─── ENDPOINT 1: Telemetry (ESP32 calls this every second) ───────────────────
@api_view(['POST'])
def telemetry_ingest(request):
    """
    POST /api/telemetry/
    Called by ESP32 every second with GPS + all sensor data.
    Also accepts data from simulator.py during development/testing.

    The backend covers all sensor inputs:
      - GPS (NEO-6M): lat, lng, speed, heading
      - MPU6050: crash detection via /api/sos/ (separate endpoint)
      - BME280: temperature, humidity
      - LM393 LDR: ambient_light
      - KY-008 Laser: fog_visibility
      - SOS Button: sos_active flag or /api/sos/ with trigger=MANUAL_BUTTON

    Response includes led_status so ESP32 firmware knows which LED to trigger:
      GREEN  → GPIO18 (normal, LOW risk)
      YELLOW → GPIO19 (warning, MEDIUM or HIGH risk)
      RED    → GPIO23 (critical or SOS)

    Expected JSON from ESP32:
    {
        "vehicle_id":    "GG-001",
        "lat":           12.9716,
        "lng":           77.5946,
        "speed":         42.0,
        "heading":       195.0,
        "temperature":   24.5,
        "humidity":      78.0,
        "ambient_light": 620.0,
        "fog_visibility": 85.0,
        "sos_active":    false
    }
    """
    try:
        payload = process_telemetry_data(request.data)

        # Return risk_level and led_status so ESP32 firmware can
        # update OLED display, buzzer, and LEDs accordingly
        return Response({
            'status':     'ok',
            'risk_level': payload['risk_level'],
            'warning':    payload['warning'],
            'led_status': payload['led_status'],   # GREEN / YELLOW / RED → firmware GPIO
            'v2v_alert':  payload['v2v_alert'],    # Server-simulated V2V message
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Telemetry ingestion error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ─── ENDPOINT 2: SOS Alert (Patent Claim 3) ──────────────────────────────────
@api_view(['POST'])
def sos_trigger(request):
    """
    POST /api/sos/
    Triggered automatically by ESP32 when MPU6050 detects crash (>2.5G)
    OR when driver presses the manual SOS button.

    Finds nearest rescue unit, calculates ETA, broadcasts to dashboard.
    """
    try:
        vehicle_id = request.data.get('vehicle_id')
        lat = float(request.data.get('lat'))
        lng = float(request.data.get('lng'))
        trigger = request.data.get('trigger', 'AUTO_IMU')  # AUTO_IMU or MANUAL_BUTTON

        vehicle, _ = Vehicle.objects.get_or_create(vehicle_id=vehicle_id)

        # Find nearest rescue unit
        rescue_units = [{
            'name':          u.name,
            'lat':           u.location.y,
            'lng':           u.location.x,
            'avg_speed_kmh': u.avg_speed_kmh,
        } for u in RescueUnit.objects.all()]

        eta_result = calculate_rescue_eta(lat, lng, rescue_units)

        # Find the actual RescueUnit model instance
        rescue_unit = RescueUnit.objects.filter(
            name=eta_result['nearest_unit']
        ).first()

        # Save SOS alert to DB
        sos = SOSAlert.objects.create(
            vehicle     = vehicle,
            location    = Point(lng, lat, srid=4326),
            trigger     = trigger,
            status      = 'ACTIVE',
            rescue_unit = rescue_unit,
            eta_minutes = eta_result['eta_minutes'],
        )

        # Broadcast SOS to rescue dashboard
        sos_payload = {
            'sos_id':       sos.id,
            'vehicle_id':   vehicle_id,
            'lat':          lat,
            'lng':          lng,
            'trigger':      trigger,
            'nearest_unit': eta_result['nearest_unit'],
            'distance_km':  eta_result['distance_km'],
            'eta_minutes':  eta_result['eta_minutes'],
            'triggered_at': sos.triggered_at.isoformat(),
        }

        async_to_sync(channel_layer.group_send)(
            'rescue_coordination',
            {'type': 'sos_alert', 'payload': sos_payload}
        )

        # ── Fire multi-channel emergency alerts (SMS + WhatsApp + siren) ──
        # Runs async via Celery so ESP32 response is not delayed
        from .alerts import dispatch_emergency_alerts, get_rescue_contacts
        contacts = get_rescue_contacts(rescue_unit.pk) if rescue_unit else {'phones':[],'whatsapp':[]}
        dispatch_emergency_alerts.delay({
            **sos_payload,
            'rescue_phones':    contacts['phones'],
            'rescue_whatsapp':  contacts['whatsapp'],
        })

        logger.critical(f"SOS ALERT: {vehicle_id} at ({lat}, {lng}) — ETA {eta_result['eta_minutes']} min")
        return Response(sos_payload, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"SOS trigger error: {e}")
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ─── ENDPOINT 3: Black Spots (Leaflet.js fetches these for map overlay) ───────
@api_view(['GET'])
def black_spots(request):
    """GET /api/blackspots/ — returns all black spot zones as GeoJSON"""
    spots = BlackSpot.objects.all()
    serializer = BlackSpotSerializer(spots, many=True)
    return Response(serializer.data)


# ─── ENDPOINT 4: Rescue Units ────────────────────────────────────────────────
@api_view(['GET'])
def rescue_units(request):
    """GET /api/rescue-units/ — returns all rescue unit locations"""
    units = RescueUnit.objects.all()
    serializer = RescueUnitSerializer(units, many=True)
    return Response(serializer.data)


# ─── ENDPOINT 5: Active SOS Alerts ───────────────────────────────────────────
@api_view(['GET'])
def active_sos(request):
    """GET /api/sos/active/ — returns all active SOS alerts for dashboard"""
    alerts = SOSAlert.objects.filter(status='ACTIVE').select_related('vehicle', 'rescue_unit')
    serializer = SOSAlertSerializer(alerts, many=True)
    return Response(serializer.data)


# ─── ENDPOINT 6: Vehicle list ────────────────────────────────────────────────
@api_view(['GET'])
def vehicle_list(request):
    """GET /api/vehicles/ — returns all registered vehicles"""
    from .serializers import VehicleSerializer
    vehicles = Vehicle.objects.filter(is_active=True)
    serializer = VehicleSerializer(vehicles, many=True)
    return Response(serializer.data)
