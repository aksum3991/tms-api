from decimal import Decimal
from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.validators import MinValueValidator
from django.conf import settings
from django.utils import timezone

from auth_app.models import Department


User = get_user_model()


class Vehicle(models.Model):
    
    AVAILABLE = 'available'
    IN_USE = 'in_use'
    SERVICE = 'service'
    MAINTENANCE = 'maintenance'

    VEHICLE_STATUS_CHOICES = [
        (AVAILABLE, 'Available'),
        (IN_USE, 'In Use'),
        (SERVICE, 'In Service'),
        (MAINTENANCE, 'Under Maintenance'),
    ]

    ORGANIZATION_OWNED = 'organization'
    RENTED = 'rented'

    VEHICLE_SOURCE_CHOICES = [
        (ORGANIZATION_OWNED, 'Organization Owned'),
        (RENTED, 'Rented'),
    ]

    NAPHTHA = 'naphtha'
    BENZENE = 'benzene'

    FUEL_TYPE_CHOICES = [
        (NAPHTHA, 'Naphtha'),
        (BENZENE, 'Benzene'),
    ]

    license_plate = models.CharField(max_length=50, unique=True)
    model = models.CharField(max_length=100)
    capacity = models.IntegerField()
    source = models.CharField(max_length=20, choices=VEHICLE_SOURCE_CHOICES, default=ORGANIZATION_OWNED)
    rental_company = models.CharField(max_length=255, blank=True, null=True) 
    status = models.CharField(max_length=20, choices=VEHICLE_STATUS_CHOICES, default=AVAILABLE)
    fuel_type = models.CharField(max_length=10, choices=FUEL_TYPE_CHOICES,default=BENZENE)
    total_kilometers = models.FloatField(default=0.0)  # Lifetime mileage
    last_service_kilometers = models.FloatField(default=0.0)  # km at last service
    motor_number = models.CharField(max_length=100, unique=True,null=True, blank=True)
    chassis_number = models.CharField(max_length=100, unique=True,null=True,blank=True)
    libre_number = models.CharField(max_length=100, unique=True,null=True,blank=True)
    is_active = models.BooleanField(default=True, help_text="Used for activate and deactivate vehicles.")
    is_deleted=models.BooleanField(default=False,help_text="Used for soft delete of vehicles.") 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    fuel_efficiency = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.1'))],
        null=True,blank=True,
        help_text="Distance the vehicle can travel per liter of fuel (km/L)."
    )
    drivers = models.ManyToManyField(
        User, 
        blank=True, 
        related_name='assigned_vehicle'
    )  
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name='vehicles'
    )
    drivers_location = models.CharField(
        max_length=255, null=True, blank=True, help_text="Location of the driver for rented vehicles."
    )

 
    def clean(self):
        if self.source == self.RENTED and not self.rental_company:
            raise ValidationError({"rental_company": "Rental company is required for rented vehicles."})

    def __str__(self):
        return f"{self.model} ({self.license_plate}) - {self.get_source_display()}"
    
    def mark_as_in_use(self):
        """Mark the vehicle as in use when assigned to a transport request."""
        if self.status != self.AVAILABLE:
            raise ValidationError(_("Vehicle must be available to be assigned."))
        self.status = self.IN_USE
        self.save()

    def mark_as_available(self):
        """Mark the vehicle as available when the request is completed."""
        self.status = self.AVAILABLE
        self.save()

    def mark_as_service(self):
        """Mark the vehicle as in service."""
        self.status = self.SERVICE
        self.save()

    def mark_as_maintenance(self):
        """Mark the vehicle as under maintenance."""
        self.status = self.MAINTENANCE
        self.save()

    def deactivate(self):
        self.is_active = False
        self.is_deleted = True
        self.save()
    def activate(self):
        self.is_active = True
        self.is_deleted = False
        self.save()
class MonthlyKilometerLog(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    month = models.CharField(max_length=20)
    kilometers_driven = models.FloatField()
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('vehicle', 'month')
class CouponRequest(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    month = models.CharField(max_length=20)
    requester = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CouponRequest for {self.vehicle.license_plate} by {self.requester.full_name} ({self.month})"

class TransportRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('forwarded', 'Forwarded'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ]
    
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transport_requests')
    start_day = models.DateField()
    return_day = models.DateField()
    start_time = models.TimeField()
    destination = models.CharField(max_length=255)
    reason = models.TextField()
    employees = models.ManyToManyField(User, related_name='travel_group')
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.SET_NULL,related_name="transport_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    current_approver_role = models.PositiveSmallIntegerField(choices=User.ROLE_CHOICES, default=User.DEPARTMENT_MANAGER)
    rejection_message = models.TextField(blank=True, null=True)
    trip_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def __str__(self):
        return f"{self.requester.get_full_name()} - {self.destination} ({self.status})"
       
class HighCostTransportRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('forwarded', 'Forwarded'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ]
    
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='highcost_transport_request')
    start_day = models.DateField()
    return_day = models.DateField()
    start_time = models.TimeField()
    destination = models.CharField(max_length=255)
    reason = models.TextField()
    employees = models.ManyToManyField(User, related_name='highcost_travel_group')
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True,  on_delete=models.SET_NULL,related_name="highcost_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    current_approver_role = models.PositiveSmallIntegerField(choices=User.ROLE_CHOICES, default=User.CEO)
    rejection_message = models.TextField(blank=True, null=True)
    estimated_vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.SET_NULL, related_name='estimated_highcost_requests')
    vehicle_assigned = models.BooleanField(default=False)
    estimated_distance_km = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_price_per_liter = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_needed_liters = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    trip_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    employee_list_file = models.FileField(
        upload_to='highcost_employee_lists/', null=True, blank=True,
        help_text="Upload a file containing the list of employees for this request."
    )


    def __str__(self):
        return f"{self.requester.full_name} - {self.destination} ({self.status})"

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('new_request', 'New Transport Request'),
        ('forwarded', 'Request Forwarded'),
        ('approved', 'Request Approved'),
        ('rejected', 'Request Rejected'),
        ('assigned', 'Vehicle Assigned'),
    )

    PRIORITY_CHOICES = (
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
    )

    recipient = models.ForeignKey('auth_app.User', on_delete=models.CASCADE, related_name='notifications')
    transport_request = models.ForeignKey(TransportRequest, on_delete=models.CASCADE, related_name='notifications', null=True, blank=True)
    maintenance_request = models.ForeignKey("MaintenanceRequest", null=True, blank=True, on_delete=models.CASCADE,related_name='notifications')
    refueling_request=models.ForeignKey("RefuelingRequest",null=True , blank=True, on_delete=models.CASCADE,related_name='notifications')
    highcost_request = models.ForeignKey("HighCostTransportRequest", null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=100, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    action_required = models.BooleanField(default=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['is_read']),
            models.Index(fields=['notification_type']),
        ]

    def __str__(self):
        return f"{self.notification_type} - {self.recipient.full_name}"

    def mark_as_read(self):
        self.is_read = True
        self.save()

class TransportRequestActionLog(models.Model):
    transport_request = models.ForeignKey(TransportRequest, on_delete=models.CASCADE, related_name='action_logs')
    action_by = models.ForeignKey(User, on_delete=models.CASCADE)
    action = models.CharField(
        max_length=20,
        choices=[('forwarded', 'Forwarded'), ('approved', 'Approved'), ('rejected', 'Rejected')]
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action_by.get_full_name()} {self.action} {self.transport_request.destination} on {self.timestamp}"
    
class MaintenanceRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("forwarded", "Forwarded"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    requester = models.ForeignKey(User, on_delete=models.CASCADE)
    requesters_car = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='maintenance_requests')
    reason = models.TextField()
    date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    current_approver_role = models.PositiveSmallIntegerField(choices=User.ROLE_CHOICES, default=User.TRANSPORT_MANAGER)
    rejection_message = models.TextField(blank=True, null=True)
    maintenance_total_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    maintenance_letter = models.FileField(upload_to="maintenance_letters/", null=True, blank=True)
    receipt_file = models.FileField(upload_to="maintenance_receipts/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.requester} - {self.status} - {self.requesters_car}"

class RefuelingRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("forwarded", "Forwarded"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    requester = models.ForeignKey(User, on_delete=models.CASCADE)  
    requesters_car = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='refueling_requests')  
    date = models.DateTimeField(auto_now_add=True)
    destination = models.CharField(max_length=1006)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")  
    current_approver_role = models.PositiveSmallIntegerField(choices=User.ROLE_CHOICES, default=User.TRANSPORT_MANAGER)  
    rejection_message = models.TextField(blank=True, null=True)
    estimated_distance_km = models.FloatField(null=True, blank=True)
    fuel_needed_liters = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_price_per_liter = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  
    updated_at = models.DateTimeField(auto_now=True) 

    def __str__(self):
        return f"{self.requester} - {self.status} - {self.requesters_car.license_plate}"
    
class ServiceRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('forwarded', 'Forwarded'),
        ('rejected', 'Rejected'),
        ('approved', 'Approved'),
    ]

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    rejection_reason = models.TextField(null=True, blank=True)

    service_letter = models.FileField(upload_to='service_letters/', null=True, blank=True)
    receipt_file = models.FileField(upload_to='service_receipts/', null=True, blank=True)
    service_total_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    current_approver_role = models.PositiveSmallIntegerField(choices=User.ROLE_CHOICES, default=User.TRANSPORT_MANAGER)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ServiceRequest {self.id} for Vehicle {self.vehicle.model} - Status: {self.status}"

    
class ActionLog(models.Model):
    ACTION_CHOICES = [
        ('forwarded', 'Forwarded'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    request_object = GenericForeignKey('content_type', 'object_id')

    action_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    status_at_time = models.CharField(max_length=20)  # store the status at the time of action
    approver_role = models.PositiveSmallIntegerField(choices=User.ROLE_CHOICES)
    remarks = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action_by.get_full_name()} {self.action} {self.content_type} #{self.object_id} on {self.timestamp}"

class OTPCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user'], name='unique_otp_per_user')
        ]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def is_locked(self):
        return self.locked_until and timezone.now() < self.locked_until
