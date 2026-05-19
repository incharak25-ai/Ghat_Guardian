"""
GHAT-GUARDIAN Serializers
Converts model instances to/from JSON for the REST API.
The ESP32 sends JSON → serializer validates → saves to PostGIS.
"""

from rest_framework import serializers
from django.contrib.gis.geos import Point
from .models import Vehicle, VehicleTelemetry, BlackSpot, SOSAlert, RescueUnit


class TelemetrySerializer(serializers.ModelSerializer):
    """
    Handles incoming GPS packets from the ESP32.
    ESP32 sends flat lat/lng — we convert to PostGIS Point here.
    """
    # ESP32 sends these as flat fields, not a GeoJSON object
    lat = serializers.FloatField(write_only=True)
    lng = serializers.FloatField(write_only=True)

    # Read-only output fields for the dashboard
    vehicle_id   = serializers.CharField(source='vehicle.vehicle_id', read_only=True)
    latitude     = serializers.FloatField(source='lat', read_only=True)
    longitude    = serializers.FloatField(source='lng', read_only=True)

    class Meta:
        model = VehicleTelemetry
        fields = [
            'id', 'vehicle_id', 'lat', 'lng', 'latitude', 'longitude',
            'speed', 'heading',
            'temperature', 'humidity', 'ambient_light', 'fog_visibility',
            'risk_level', 'warning',
            'sos_active', 'v2v_alert',
            'timestamp',
        ]
        read_only_fields = ['id', 'timestamp']

    def validate(self, data):
        """Validate coordinate bounds for India"""
        lat = data.get('lat')
        lng = data.get('lng')
        if lat and not (6.0 <= lat <= 37.0):
            raise serializers.ValidationError("Latitude out of India bounds")
        if lng and not (68.0 <= lng <= 97.0):
            raise serializers.ValidationError("Longitude out of India bounds")
        return data

    def create(self, validated_data):
        """Convert flat lat/lng to PostGIS Point before saving"""
        lat = validated_data.pop('lat')
        lng = validated_data.pop('lng')
        # Point(longitude, latitude) — note the order!
        validated_data['location'] = Point(lng, lat, srid=4326)

        # Get or create vehicle by vehicle_id
        vehicle_id = self.context['request'].data.get('vehicle_id', 'UNKNOWN')
        vehicle, _ = Vehicle.objects.get_or_create(vehicle_id=vehicle_id)
        validated_data['vehicle'] = vehicle

        return super().create(validated_data)


class SOSAlertSerializer(serializers.ModelSerializer):
    """Serializer for SOS alerts — used by the SOS Alert Panel"""
    vehicle_id   = serializers.CharField(source='vehicle.vehicle_id', read_only=True)
    lat          = serializers.FloatField(write_only=True)
    lng          = serializers.FloatField(write_only=True)
    latitude     = serializers.FloatField(source='location.y', read_only=True)
    longitude    = serializers.FloatField(source='location.x', read_only=True)
    rescue_unit_name = serializers.CharField(source='rescue_unit.name', read_only=True)

    class Meta:
        model = SOSAlert
        fields = [
            'id', 'vehicle_id', 'lat', 'lng', 'latitude', 'longitude',
            'trigger', 'status', 'rescue_unit_name', 'eta_minutes',
            'triggered_at', 'resolved_at',
        ]
        read_only_fields = ['id', 'triggered_at', 'status', 'eta_minutes']

    def create(self, validated_data):
        lat = validated_data.pop('lat')
        lng = validated_data.pop('lng')
        validated_data['location'] = Point(lng, lat, srid=4326)
        vehicle_id = self.context['request'].data.get('vehicle_id')
        vehicle, _ = Vehicle.objects.get_or_create(vehicle_id=vehicle_id)
        validated_data['vehicle'] = vehicle
        return super().create(validated_data)


class BlackSpotSerializer(serializers.ModelSerializer):
    """Serializer for black spot zones — sent to Leaflet.js as GeoJSON polygons"""
    class Meta:
        model = BlackSpot
        fields = ['id', 'name', 'description', 'zone', 'risk_level', 'warning_msg']


class RescueUnitSerializer(serializers.ModelSerializer):
    """Serializer for rescue units — used by Rescue Information Panel"""
    latitude  = serializers.FloatField(source='location.y', read_only=True)
    longitude = serializers.FloatField(source='location.x', read_only=True)

    class Meta:
        model = RescueUnit
        fields = ['id', 'name', 'latitude', 'longitude', 'contact', 'avg_speed_kmh']


class VehicleSerializer(serializers.ModelSerializer):
    """Basic vehicle info serializer"""
    class Meta:
        model = Vehicle
        fields = ['vehicle_id', 'driver_name', 'route', 'is_active', 'registered_at']
