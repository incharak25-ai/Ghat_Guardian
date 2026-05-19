"""
GHAT-GUARDIAN API Views
REST endpoints that the ESP32 calls every second.
After saving data, broadcasts to WebSocket via Redis channel layer.
"""

import json
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
from .serializers import (TelemetrySerializer, SOSAlertSerializer,
                          BlackSpotSerializer, RescueUnitSerializer)
from .ml_engine import calculate_overall_risk, calculate_rescue_eta

logger = logging.getLogger(__name__)
channel_layer = get_channel_layer()


def process_telemetry_data(data: dict) -> dict:
    """
    Core processing function — called by both REST API and WebSocket consumer.
    1. Validates incoming data
    2. Runs ML risk engine
    3. Saves to PostGIS
    4. Broadcasts to rescue dashboard via Redis
    Returns the broadcast payload.
    """
    vehicle_id = data.get('vehicle_id', 'UNKNOWN')
    lat = float(data.get('lat', 0))
    lng = float(data.get('lng', 0))

    # ── Find nearby vehicles for TTC calculation ──────────────────────────
    current_point = Point(lng, lat, srid=4326)
    nearby_qs = (VehicleTelemetry.objects
                 .filter(timestamp__gte=timezone.now() - timezone.timedelta(seconds=5))
                 .exclude(vehicle__vehicle_id=vehicle_id)
                 .filter(location__distance_lte=(current_point, Distance(m=1000))))

    nearby_vehicles = [{
        'vehicle_id': t.vehicle.vehicle_id,
        'lat':    t.location.y,
        'lng':    t.location.x,
        'speed':   t.speed,
        'heading': t.heading,
    } for t in nearby_qs]

    # ── Run ML risk engine ────────────────────────────────────────────────
    risk_result = calculate_overall_risk(
        telemetry_data={
            'lat':            lat,
            'lng':            lng,
            'speed':          float(data.get('speed', 0)),
            'heading':        float(data.get('heading', 0)),
            'fog_visibility': data.get('fog_visibility'),
        },
        nearby_vehicles=nearby_vehicles
    )

    # ── Check if vehicle is in a Black Spot zone ──────────────────────────
    in_black_spot = BlackSpot.objects.filter(
        zone__contains=current_point
    ).first()

    if in_black_spot:
        if risk_result['risk_level'] in ['LOW', 'MEDIUM']:
            risk_result['risk_level'] = 'HIGH'
        risk_result['warning'] = risk_result['warning'] or in_black_spot.warning_msg

    # ── Get or create vehicle ─────────────────────────────────────────────
    vehicle, _ = Vehicle.objects.get_or_create(vehicle_id=vehicle_id)

    # ── Save to PostGIS ───────────────────────────────────────────────────
    telemetry = VehicleTelemetry.objects.create(
        vehicle       = vehicle,
        location      = current_point,
        speed         = float(data.get('speed', 0)),
        heading       = float(data.get('heading', 0)),
        temperature   = data.get('temperature'),
        humidity      = data.get('humidity'),
        ambient_light = data.get('ambient_light'),
        fog_visibility = data.get('fog_visibility'),
        risk_level    = risk_result['risk_level'],
        warning       = risk_result['warning'],
        sos_active    = bool(data.get('sos_active', False)),
        v2v_alert     = data.get('v2v_alert'),
    )

    # ── Build broadcast payload for dashboard ─────────────────────────────
    payload = {
        'vehicle_id':    vehicle_id,
        'lat':           lat,
        'lng':           lng,
        'speed':         telemetry.speed,
        'heading':       telemetry.heading,
        'risk_level':    telemetry.risk_level,
        'warning':       telemetry.warning,
        'fog_visibility': telemetry.fog_visibility,
        'temperature':   telemetry.temperature,
        'humidity':      telemetry.humidity,
        'ambient_light': telemetry.ambient_light,
        'sos_active':    telemetry.sos_active,
        'v2v_alert':     telemetry.v2v_alert,
        'ttc_seconds':   risk_result.get('ttc_result', {}).get('ttc_seconds') if risk_result.get('ttc_result') else None,
        'nearby_count':  len(nearby_vehicles),
        'in_black_spot': in_black_spot.name if in_black_spot else None,
        'timestamp':     telemetry.timestamp.isoformat(),
    }

    # ── Broadcast to rescue dashboard via Redis ───────────────────────────
    async_to_sync(channel_layer.group_send)(
        'rescue_coordination',
        {'type': 'telemetry_update', 'payload': payload}
    )

    # ── If V2V alert exists, broadcast to V2V panel ───────────────────────
    if data.get('v2v_alert'):
        async_to_sync(channel_layer.group_send)(
            'rescue_coordination',
            {'type': 'v2v_alert', 'payload': {
                'from_vehicle': vehicle_id,
                'alert':        data['v2v_alert'],
                'timestamp':    telemetry.timestamp.isoformat(),
            }}
        )

    return payload


# ─── ENDPOINT 1: Telemetry (ESP32 calls this every second) ───────────────────
@api_view(['POST'])
def telemetry_ingest(request):
    """
    POST /api/telemetry/
    Called by ESP32 every second with GPS + sensor data.
    Also accepts data from the Python simulator during testing.

    Expected JSON:
    {
        "vehicle_id": "GG-001",
        "lat": 12.9716, "lng": 77.5946,
        "speed": 42, "heading": 195,
        "temperature": 24.5, "humidity": 78,
        "ambient_light": 620, "fog_visibility": 85,
        "sos_active": false, "v2v_alert": null
    }
    """
    try:
        payload = process_telemetry_data(request.data)
        return Response({'status': 'ok', 'risk_level': payload['risk_level']},
                        status=status.HTTP_201_CREATED)
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
