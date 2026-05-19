"""
GHAT-GUARDIAN WebSocket Consumer
The real-time heart of the system.
Receives GPS telemetry → runs ML engine → broadcasts to dashboard.

Flow:
  ESP32 HTTP POST → views.py → consumer notified via Redis
  Dashboard connects WebSocket → receives live updates every second
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.utils import timezone

from .models import VehicleTelemetry, Vehicle, SOSAlert, RescueUnit, BlackSpot
from .ml_engine import calculate_overall_risk, calculate_rescue_eta

logger = logging.getLogger(__name__)

# All rescue hub dashboards join this group — they all see every vehicle
RESCUE_GROUP = 'rescue_coordination'


class TelemetryConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for the rescue hub dashboard.
    Connects via: ws://your-replit-url/ws/telemetry/

    On connect: joins rescue_coordination group
    On message: (not used — dashboard is read-only)
    On group message: forwards live telemetry to the dashboard browser
    """

    async def connect(self):
        """Dashboard browser connects — add to rescue group"""
        await self.channel_layer.group_add(RESCUE_GROUP, self.channel_name)
        await self.accept()
        logger.info(f"Dashboard connected: {self.channel_name}")

        # Send current state of all active vehicles immediately on connect
        snapshot = await self.get_vehicle_snapshot()
        await self.send(text_data=json.dumps({
            'type':     'snapshot',
            'vehicles': snapshot,
            'timestamp': timezone.now().isoformat(),
        }))

    async def disconnect(self, close_code):
        """Dashboard browser disconnects"""
        await self.channel_layer.group_discard(RESCUE_GROUP, self.channel_name)
        logger.info(f"Dashboard disconnected: {self.channel_name}")

    async def receive(self, text_data):
        """
        Dashboard can send filter commands (e.g. filter by state/route).
        Not used for telemetry — ESP32 sends via REST API, not WebSocket.
        """
        try:
            data = json.loads(text_data)
            if data.get('type') == 'filter':
                # Future: filter vehicles by route or state
                pass
        except json.JSONDecodeError:
            pass

    # ── Group message handlers (called by channel layer) ─────────────────────

    async def telemetry_update(self, event):
        """
        Receives a telemetry update from the Redis channel layer
        and forwards it to the connected dashboard browser.
        Called by: views.py after saving a new GPS packet from ESP32.
        """
        await self.send(text_data=json.dumps({
            'type':    'telemetry',
            'payload': event['payload'],
        }))

    async def sos_alert(self, event):
        """
        Receives an SOS alert from the Redis channel layer.
        Triggers the SOS Alert Panel on the dashboard.
        """
        await self.send(text_data=json.dumps({
            'type':    'sos',
            'payload': event['payload'],
        }))

    async def v2v_alert(self, event):
        """
        Receives a V2V collision alert.
        Triggers the V2V Message Panel on the dashboard.
        """
        await self.send(text_data=json.dumps({
            'type':    'v2v',
            'payload': event['payload'],
        }))

    # ── Database helpers (sync → async bridge) ───────────────────────────────

    @database_sync_to_async
    def get_vehicle_snapshot(self):
        """
        Get the latest telemetry for all active vehicles.
        Called once when a new dashboard connects to show current state.
        """
        snapshot = []
        vehicles = Vehicle.objects.filter(is_active=True)
        for vehicle in vehicles:
            latest = (VehicleTelemetry.objects
                      .filter(vehicle=vehicle)
                      .order_by('-timestamp')
                      .first())
            if latest:
                snapshot.append({
                    'vehicle_id':    vehicle.vehicle_id,
                    'lat':           latest.location.y,
                    'lng':           latest.location.x,
                    'speed':         latest.speed,
                    'heading':       latest.heading,
                    'risk_level':    latest.risk_level,
                    'warning':       latest.warning,
                    'fog_visibility': latest.fog_visibility,
                    'temperature':   latest.temperature,
                    'humidity':      latest.humidity,
                    'sos_active':    latest.sos_active,
                    'timestamp':     latest.timestamp.isoformat(),
                })
        return snapshot


class VehicleConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for the ESP32 / driver mobile app.
    Each vehicle gets its own group: vehicle_{vehicle_id}
    Connects via: ws://your-replit-url/ws/vehicle/{vehicle_id}/

    Used to push collision warnings and risk alerts back to the vehicle.
    """

    async def connect(self):
        self.vehicle_id = self.scope['url_route']['kwargs']['vehicle_id']
        self.vehicle_group = f'vehicle_{self.vehicle_id}'

        await self.channel_layer.group_add(self.vehicle_group, self.channel_name)
        await self.channel_layer.group_add(RESCUE_GROUP, self.channel_name)
        await self.accept()
        logger.info(f"Vehicle {self.vehicle_id} connected")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.vehicle_group, self.channel_name)
        await self.channel_layer.group_discard(RESCUE_GROUP, self.channel_name)

    async def receive(self, text_data):
        """
        Receive telemetry from the driver app (alternative to REST API).
        Processes and broadcasts to rescue dashboard.
        """
        try:
            data = json.loads(text_data)
            data['vehicle_id'] = self.vehicle_id
            await self.process_and_broadcast(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Invalid telemetry from {self.vehicle_id}: {e}")

    async def collision_warning(self, event):
        """Push collision warning back to this vehicle's app"""
        await self.send(text_data=json.dumps({
            'type':    'collision_warning',
            'payload': event['payload'],
        }))

    async def telemetry_update(self, event):
        """Forward nearby vehicle updates to driver app"""
        await self.send(text_data=json.dumps({
            'type':    'telemetry',
            'payload': event['payload'],
        }))

    @database_sync_to_async
    def process_and_broadcast(self, data):
        """Save telemetry and trigger ML engine — called from receive()"""
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        from .views import process_telemetry_data
        process_telemetry_data(data)
