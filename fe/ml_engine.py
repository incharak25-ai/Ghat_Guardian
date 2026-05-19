"""
GHAT-GUARDIAN ML Engine
Patent Claim 2: Edge-computed Time-to-Collision using Haversine formula
Patent Claim 3: Auto SOS with ETA calculation

This module is called by consumers.py every time a GPS packet arrives.
All calculations are pure Python/NumPy — no heavy model loading needed.
"""

import math
import numpy as np
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance


# ─── CONSTANTS ───────────────────────────────────────────────────────────────
EARTH_RADIUS_M    = 6_371_000   # metres
COLLISION_DIST_M  = 150         # warn if two vehicles within 150m
TTC_WARN_SECONDS  = 10          # warn if collision predicted within 10 seconds
FOG_WARN_THRESHOLD = 40         # % visibility below which fog warning fires
CRASH_G_THRESHOLD  = 2.5        # G-force threshold from MPU6050


# ─── 1. HAVERSINE DISTANCE ───────────────────────────────────────────────────
def haversine_distance(lat1, lng1, lat2, lng2) -> float:
    """
    Calculate great-circle distance between two GPS coordinates in metres.
    Uses the Haversine formula — accounts for Earth's curvature.
    Critical for accuracy in mountain terrain where flat-Earth math fails.

    Args:
        lat1, lng1: First point (degrees)
        lat2, lng2: Second point (degrees)
    Returns:
        Distance in metres
    """
    phi1    = math.radians(lat1)
    phi2    = math.radians(lat2)
    d_phi   = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    # Haversine formula
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


# ─── 2. VELOCITY VECTOR DECOMPOSITION ────────────────────────────────────────
def velocity_vector(speed_kmh: float, heading_deg: float) -> tuple:
    """
    Decompose speed + heading into North/East velocity components (m/s).
    Used to project a vehicle's future position for TTC calculation.

    Args:
        speed_kmh:   Vehicle speed in km/h
        heading_deg: Compass heading in degrees (0=North, 90=East)
    Returns:
        (v_north, v_east) in m/s
    """
    speed_ms  = speed_kmh / 3.6
    heading_r = math.radians(heading_deg)
    v_north   = speed_ms * math.cos(heading_r)
    v_east    = speed_ms * math.sin(heading_r)
    return v_north, v_east


# ─── 3. TIME-TO-COLLISION (PATENT CLAIM 2) ───────────────────────────────────
def calculate_ttc(vehicle_a: dict, vehicle_b: dict) -> dict:
    """
    Calculate Time-to-Collision between two approaching vehicles.
    Projects both vehicles forward in 0.5s steps and checks distance.

    This is the core of Patent Claim 2:
    'Edge-computed TTC using Haversine-formula velocity vectors'

    Args:
        vehicle_a: {'lat', 'lng', 'speed', 'heading', 'vehicle_id'}
        vehicle_b: {'lat', 'lng', 'speed', 'heading', 'vehicle_id'}
    Returns:
        {
            'ttc_seconds': float or None,
            'current_distance_m': float,
            'risk_level': str,
            'warning': str
        }
    """
    current_dist = haversine_distance(
        vehicle_a['lat'], vehicle_a['lng'],
        vehicle_b['lat'], vehicle_b['lng']
    )

    # Only calculate TTC if vehicles are within 1km of each other
    if current_dist > 1000:
        return {
            'ttc_seconds': None,
            'current_distance_m': current_dist,
            'risk_level': 'LOW',
            'warning': ''
        }

    # Decompose velocity vectors for both vehicles
    vn_a, ve_a = velocity_vector(vehicle_a['speed'], vehicle_a['heading'])
    vn_b, ve_b = velocity_vector(vehicle_b['speed'], vehicle_b['heading'])

    # Project positions forward in 0.5s timesteps up to 30 seconds
    lat_a, lng_a = vehicle_a['lat'], vehicle_a['lng']
    lat_b, lng_b = vehicle_b['lat'], vehicle_b['lng']

    # Convert m/s to degrees/s for position update
    # 1 degree latitude ≈ 111,320 metres
    DEG_PER_M_LAT = 1 / 111_320

    for step in range(1, 61):  # 60 steps × 0.5s = 30 seconds lookahead
        dt = 0.5  # seconds per step

        # Update positions
        lat_a += vn_a * dt * DEG_PER_M_LAT
        lng_a += ve_a * dt * DEG_PER_M_LAT / math.cos(math.radians(lat_a))
        lat_b += vn_b * dt * DEG_PER_M_LAT
        lng_b += ve_b * dt * DEG_PER_M_LAT / math.cos(math.radians(lat_b))

        projected_dist = haversine_distance(lat_a, lng_a, lat_b, lng_b)

        if projected_dist <= COLLISION_DIST_M:
            ttc = step * dt  # seconds until collision

            # Assign risk level based on TTC
            if ttc <= 3:
                risk = 'CRITICAL'
                warning = f'COLLISION IMMINENT — {ttc:.1f}s — BRAKE NOW'
            elif ttc <= 6:
                risk = 'HIGH'
                warning = f'Collision risk in {ttc:.1f}s — Slow down immediately'
            elif ttc <= TTC_WARN_SECONDS:
                risk = 'MEDIUM'
                warning = f'Vehicle approaching — {ttc:.1f}s to collision'
            else:
                risk = 'LOW'
                warning = 'Monitor oncoming vehicle'

            return {
                'ttc_seconds': ttc,
                'current_distance_m': current_dist,
                'risk_level': risk,
                'warning': warning
            }

    # No collision predicted in 30 second window
    return {
        'ttc_seconds': None,
        'current_distance_m': current_dist,
        'risk_level': 'LOW',
        'warning': ''
    }


# ─── 4. FOG / VISIBILITY RISK ────────────────────────────────────────────────
def calculate_fog_risk(fog_visibility: float, speed_kmh: float) -> dict:
    """
    Calculate risk level from fog visibility (Laser+LDR sensor reading).
    Combines visibility % with current speed to assess stopping distance.

    Args:
        fog_visibility: % visibility from Laser+LDR sensor (0-100)
        speed_kmh:      Current vehicle speed
    Returns:
        {'risk_level': str, 'warning': str}
    """
    if fog_visibility is None:
        return {'risk_level': 'LOW', 'warning': ''}

    # Stopping distance at current speed (simplified: d = v²/2a, a=5m/s²)
    speed_ms = speed_kmh / 3.6
    stopping_dist_m = (speed_ms ** 2) / (2 * 5)

    # Visibility distance in metres (assume max visible range = 200m at 100%)
    visibility_dist_m = (fog_visibility / 100) * 200

    if fog_visibility < 20 or visibility_dist_m < stopping_dist_m:
        return {'risk_level': 'CRITICAL', 'warning': 'Dense Fog — Pull over immediately'}
    elif fog_visibility < 40:
        return {'risk_level': 'HIGH',     'warning': 'Low Visibility — Reduce speed, use fog lights'}
    elif fog_visibility < 60:
        return {'risk_level': 'MEDIUM',   'warning': 'Moderate fog ahead — Caution'}
    else:
        return {'risk_level': 'LOW',      'warning': ''}


# ─── 5. OVERALL RISK SCORING ─────────────────────────────────────────────────
RISK_ORDER = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

def calculate_overall_risk(telemetry_data: dict, nearby_vehicles: list) -> dict:
    """
    Combine all risk factors into a single risk level for the dashboard.
    Takes the highest risk from: TTC + fog + black spot + speed.

    Args:
        telemetry_data:  Dict of incoming sensor values
        nearby_vehicles: List of other vehicle dicts within 1km
    Returns:
        {'risk_level': str, 'warning': str, 'ttc_result': dict}
    """
    risks = []

    # 1. TTC risk — check against all nearby vehicles
    ttc_result = None
    for other in nearby_vehicles:
        result = calculate_ttc(telemetry_data, other)
        risks.append(result['risk_level'])
        if ttc_result is None or (
            result['ttc_seconds'] and
            (ttc_result['ttc_seconds'] is None or result['ttc_seconds'] < ttc_result['ttc_seconds'])
        ):
            ttc_result = result

    # 2. Fog risk
    fog_risk = calculate_fog_risk(
        telemetry_data.get('fog_visibility'),
        telemetry_data.get('speed', 0)
    )
    risks.append(fog_risk['risk_level'])

    # 3. Speed risk on mountain road
    speed = telemetry_data.get('speed', 0)
    if speed > 60:
        risks.append('HIGH')
    elif speed > 45:
        risks.append('MEDIUM')

    # Take the highest risk level
    final_risk = max(risks, key=lambda r: RISK_ORDER.index(r)) if risks else 'LOW'

    # Build warning message from highest-priority risk
    warning = ''
    if ttc_result and ttc_result.get('warning'):
        warning = ttc_result['warning']
    elif fog_risk['warning']:
        warning = fog_risk['warning']
    elif speed > 60:
        warning = 'Reduce speed — Mountain road speed limit 40 km/h'

    return {
        'risk_level': final_risk,
        'warning': warning,
        'ttc_result': ttc_result
    }


# ─── 6. SOS ETA CALCULATION (PATENT CLAIM 3) ─────────────────────────────────
def calculate_rescue_eta(crash_lat: float, crash_lng: float, rescue_units: list) -> dict:
    """
    Find the nearest rescue unit and calculate ETA to crash site.
    Patent Claim 3: 'Auto SOS dispatch with ETA calculation'

    Args:
        crash_lat, crash_lng: Crash GPS coordinates
        rescue_units: List of {'name', 'lat', 'lng', 'avg_speed_kmh'}
    Returns:
        {'nearest_unit': str, 'distance_km': float, 'eta_minutes': int}
    """
    if not rescue_units:
        return {'nearest_unit': 'Unknown', 'distance_km': 0, 'eta_minutes': 30}

    nearest = None
    min_dist = float('inf')

    for unit in rescue_units:
        dist = haversine_distance(crash_lat, crash_lng, unit['lat'], unit['lng'])
        if dist < min_dist:
            min_dist = dist
            nearest = unit

    dist_km  = min_dist / 1000
    # ETA = distance ÷ speed (accounting for mountain road factor of 0.6)
    eta_hrs  = dist_km / (nearest['avg_speed_kmh'] * 0.6)
    eta_min  = int(eta_hrs * 60)

    return {
        'nearest_unit':  nearest['name'],
        'distance_km':   round(dist_km, 2),
        'eta_minutes':   max(eta_min, 1)  # Minimum 1 minute
    }
