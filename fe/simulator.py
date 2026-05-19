"""
GHAT-GUARDIAN GPS Simulator
Pretends to be 3 ESP32 devices moving along the real Bangalore → Dharmasthala route.
Use this to test the full backend + dashboard without any hardware.

Run with: python simulator.py
The dashboard will show 3 live cars moving on the real map.
"""

import requests
import time
import math
import random
import threading

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BACKEND_URL  = 'http://localhost:8000/api/telemetry/'  # Change to Replit URL when deployed
UPDATE_RATE  = 1.0   # seconds between updates (matches NEO-M8N GPS output rate)

# ─── REAL ROUTE WAYPOINTS (NH75) ─────────────────────────────────────────────
# Bangalore → Nelamangala → Kunigal → Hassan → Sakleshpur → Shiradi Ghat → Dharmasthala
ROUTE_WAYPOINTS = [
    (12.9716, 77.5946),   # Bangalore
    (13.0200, 77.5200),   # Tumkur Road
    (13.0979, 77.3952),   # Nelamangala
    (13.0600, 77.2000),   # NH75 stretch
    (13.0210, 77.0253),   # Kunigal
    (13.0100, 76.8000),   # Channarayapatna approach
    (13.0050, 76.1000),   # Hassan
    (12.9800, 75.9500),   # Belur approach
    (12.9420, 75.7850),   # Sakleshpur
    (12.8500, 75.7200),   # Ghat road begins
    (12.7800, 75.7000),   # Shiradi Ghat upper
    (12.7500, 75.6800),   # Gundya — deepest ghat section (black spot)
    (12.7200, 75.6500),   # Ghat exit
    (12.8000, 75.5500),   # Ujire
    (12.9579, 75.3750),   # Dharmasthala
]


def interpolate_route(waypoints, total_points=500):
    """
    Generate smooth GPS points along the route by linearly
    interpolating between waypoints.
    Returns list of (lat, lng) tuples.
    """
    route = []
    segments = len(waypoints) - 1
    points_per_segment = total_points // segments

    for i in range(segments):
        lat1, lng1 = waypoints[i]
        lat2, lng2 = waypoints[i + 1]
        for j in range(points_per_segment):
            t = j / points_per_segment
            lat = lat1 + t * (lat2 - lat1)
            lng = lng1 + t * (lng2 - lng1)
            route.append((lat, lng))

    route.append(waypoints[-1])
    return route


def calculate_heading(lat1, lng1, lat2, lng2) -> float:
    """Calculate compass heading between two GPS points (degrees)"""
    d_lng = math.radians(lng2 - lng1)
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    x = math.sin(d_lng) * math.cos(lat2_r)
    y = (math.cos(lat1_r) * math.sin(lat2_r)
         - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(d_lng))
    heading = math.degrees(math.atan2(x, y))
    return (heading + 360) % 360


def simulate_sensors(lat, lng, route_progress) -> dict:
    """
    Generate realistic sensor readings based on position on route.
    Shiradi Ghat section (progress 0.65–0.80) gets fog + lower visibility.
    """
    in_ghat = 0.60 <= route_progress <= 0.82

    return {
        'temperature':    round(random.uniform(18, 28) if not in_ghat else random.uniform(14, 22), 1),
        'humidity':       round(random.uniform(60, 80) if not in_ghat else random.uniform(80, 95), 1),
        'ambient_light':  round(random.uniform(400, 800) if not in_ghat else random.uniform(100, 300), 0),
        'fog_visibility': round(random.uniform(75, 95) if not in_ghat else random.uniform(20, 55), 1),
    }


class VehicleSimulator(threading.Thread):
    """
    Simulates one ESP32 vehicle moving along the route.
    Runs in its own thread so multiple vehicles move simultaneously.
    """

    def __init__(self, vehicle_id: str, start_offset: int = 0, speed_kmh: float = 38):
        super().__init__(daemon=True)
        self.vehicle_id  = vehicle_id
        self.speed_kmh   = speed_kmh
        self.route       = interpolate_route(ROUTE_WAYPOINTS)
        self.position    = start_offset % len(self.route)
        self.running     = True

    def run(self):
        print(f"[{self.vehicle_id}] Starting simulation at route position {self.position}")

        while self.running:
            current_pos = self.position
            next_pos    = (current_pos + 1) % len(self.route)

            lat, lng    = self.route[current_pos]
            lat2, lng2  = self.route[next_pos]
            heading     = calculate_heading(lat, lng, lat2, lng2)

            # Add tiny GPS noise to simulate real sensor jitter
            lat += random.gauss(0, 0.00003)
            lng += random.gauss(0, 0.00003)

            # Speed varies — slower in ghat, faster on highway
            progress = current_pos / len(self.route)
            in_ghat  = 0.60 <= progress <= 0.82
            speed    = self.speed_kmh * (0.6 if in_ghat else 1.0)
            speed   += random.gauss(0, 3)  # natural speed variation
            speed    = max(5, speed)

            sensors = simulate_sensors(lat, lng, progress)

            payload = {
                'vehicle_id':    self.vehicle_id,
                'lat':           round(lat, 6),
                'lng':           round(lng, 6),
                'speed':         round(speed, 1),
                'heading':       round(heading, 1),
                'sos_active':    False,
                'v2v_alert':     None,
                **sensors,
            }

            try:
                resp = requests.post(BACKEND_URL, json=payload, timeout=2)
                status_icon = '✓' if resp.status_code == 201 else '✗'
                print(f"[{self.vehicle_id}] {status_icon} ({lat:.4f}, {lng:.4f}) "
                      f"speed={speed:.0f}km/h fog={sensors['fog_visibility']}%")
            except requests.exceptions.RequestException as e:
                print(f"[{self.vehicle_id}] ✗ Backend unreachable: {e}")

            self.position = next_pos
            time.sleep(UPDATE_RATE)

        print(f"[{self.vehicle_id}] Simulation stopped")


if __name__ == '__main__':
    print("=" * 55)
    print("  GHAT-GUARDIAN GPS Simulator")
    print("  Simulating 3 vehicles on Bangalore → Dharmasthala")
    print(f"  Sending to: {BACKEND_URL}")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    # Start 3 vehicles at different positions on the route
    vehicles = [
        VehicleSimulator('GG-001', start_offset=0,   speed_kmh=40),  # At Bangalore
        VehicleSimulator('GG-002', start_offset=150, speed_kmh=36),  # Mid-route
        VehicleSimulator('GG-003', start_offset=300, speed_kmh=32),  # In Ghat section
    ]

    for v in vehicles:
        v.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping all simulators...")
        for v in vehicles:
            v.running = False
