"""
GHAT-GUARDIAN Models
PostGIS-enabled models for spatial vehicle tracking.
Every model here maps directly to a panel on the dashboard.
"""

from django.contrib.gis.db import models
from django.utils import timezone


class Vehicle(models.Model):
    """
    Registered vehicle in the Ghat-Guardian network.
    Each ESP32 device corresponds to one Vehicle record.
    """
    vehicle_id   = models.CharField(max_length=20, unique=True)  # e.g. GG-001
    driver_name  = models.CharField(max_length=100, blank=True)
    route        = models.CharField(max_length=200, blank=True)  # e.g. Bangalore → Dharmasthala
    registered_at = models.DateTimeField(auto_now_add=True)
    is_active    = models.BooleanField(default=True)

    def __str__(self):
        return self.vehicle_id


class VehicleTelemetry(models.Model):
    """
    Every GPS update from the ESP32 is stored here.
    PostGIS PointField stores lat/lng for spatial queries.
    ST_DWithin uses this to detect Black Spot proximity.
    """

    # Risk level choices — matches AI/Risk Engine Layer output
    RISK_CHOICES = [
        ('LOW',      'Low'),
        ('MEDIUM',   'Medium'),
        ('HIGH',     'High'),
        ('CRITICAL', 'Critical'),
    ]

    vehicle      = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='telemetry')

    # ── Spatial data (PostGIS) ──────────────────────────────────────────────
    # geography=True uses the Earth's curvature — critical for mountain GPS accuracy
    location     = models.PointField(geography=True)

    # ── Motion data (from NEO-M8N GPS) ─────────────────────────────────────
    speed        = models.FloatField(default=0)    # km/h
    heading      = models.FloatField(default=0)    # degrees (0=North, 90=East)

    # ── Environmental sensors (BME280/DHT22 + LDR + Laser) ─────────────────
    temperature  = models.FloatField(null=True, blank=True)   # Celsius
    humidity     = models.FloatField(null=True, blank=True)   # %
    ambient_light = models.FloatField(null=True, blank=True)  # LDR lux value
    fog_visibility = models.FloatField(null=True, blank=True) # % visibility (Laser+LDR)

    # ── AI Risk Engine output ───────────────────────────────────────────────
    risk_level   = models.CharField(max_length=10, choices=RISK_CHOICES, default='LOW')
    warning      = models.CharField(max_length=200, blank=True)  # e.g. "Sharp Turn Ahead"

    # ── Status flags ────────────────────────────────────────────────────────
    sos_active   = models.BooleanField(default=False)
    v2v_alert    = models.CharField(max_length=200, blank=True, null=True)

    # ── Timestamp ───────────────────────────────────────────────────────────
    timestamp    = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            # Spatial index — makes ST_DWithin fast even with millions of rows
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.vehicle.vehicle_id} @ {self.timestamp:%H:%M:%S}"

    @property
    def lat(self):
        return self.location.y

    @property
    def lng(self):
        return self.location.x


class BlackSpot(models.Model):
    """
    Known high-risk zones on the route.
    Stored as PostGIS polygons — ST_DWithin checks if a vehicle enters.
    Pre-loaded with Shiradi Ghat blind curves and steep descent zones.
    """
    name         = models.CharField(max_length=200)
    description  = models.TextField(blank=True)

    # Polygon defines the danger zone boundary
    zone         = models.PolygonField(geography=True)

    risk_level   = models.CharField(max_length=10, default='HIGH')
    warning_msg  = models.CharField(max_length=200, default='Caution: High Risk Zone')
    created_at   = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class SOSAlert(models.Model):
    """
    Created automatically when MPU6050 detects crash (>2.5G)
    or when driver presses the manual SOS button.
    Powers the SOS Alert Panel on the dashboard.
    """
    STATUS_CHOICES = [
        ('ACTIVE',   'Active'),
        ('DISPATCHED', 'Rescue Dispatched'),
        ('RESOLVED', 'Resolved'),
    ]

    vehicle      = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='sos_alerts')
    location     = models.PointField(geography=True)   # Exact crash coordinates

    trigger      = models.CharField(max_length=50, default='AUTO_IMU')  # AUTO_IMU or MANUAL_BUTTON
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    # Populated when rescue is dispatched
    rescue_unit  = models.ForeignKey('RescueUnit', null=True, blank=True, on_delete=models.SET_NULL)
    eta_minutes  = models.IntegerField(null=True, blank=True)

    triggered_at = models.DateTimeField(default=timezone.now)
    resolved_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-triggered_at']

    def __str__(self):
        return f"SOS — {self.vehicle.vehicle_id} @ {self.triggered_at:%H:%M:%S}"


class RescueUnit(models.Model):
    """
    Registered rescue teams at bases along the route.
    Used to calculate nearest unit and ETA when SOS fires.
    """
    name         = models.CharField(max_length=200)   # e.g. "Sakleshpur Fire Station"
    location     = models.PointField(geography=True)
    contact      = models.CharField(max_length=20, blank=True)
    avg_speed_kmh = models.FloatField(default=40)     # Average road speed for ETA

    def __str__(self):
        return self.name
