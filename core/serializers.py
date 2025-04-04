from rest_framework import serializers

from auth_app.models import User
from django.utils.timezone import now 
from auth_app.serializers import UserDetailSerializer
from core.models import MaintenanceRequest, RefuelingRequest, TransportRequest, Vehicle, Notification

class TransportRequestSerializer(serializers.ModelSerializer):
    requester = serializers.ReadOnlyField(source='requester.get_full_name')
    employees = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.EMPLOYEE), many=True)

    class Meta:
        model = TransportRequest
        fields = '__all__'

    def validate(self, data):
        """
        Ensure return_day is not before start_day.
        """
        start_day = data.get("start_day")
        return_day = data.get("return_day")

        if start_day and start_day < now().date():
            raise serializers.ValidationError({"start_day": "Start date cannot be in the past."})
        
        if return_day and start_day and return_day < start_day:
            raise serializers.ValidationError({"return_day": "Return date cannot be before the start date."})

        return data
    
    def create(self, validated_data):
        """
        Automatically assigns the currently logged-in user as the requester
        and correctly handles ManyToMany relationships.
        """
        request = self.context.get("request")
        
        employees = validated_data.pop("employees", [])  # Extract employees list

        if request and request.user.is_authenticated:
            validated_data["requester"] = request.user

        transport_request = TransportRequest.objects.create(**validated_data)  
        transport_request.employees.set(employees)  
        
        return transport_request
          
class VehicleSerializer(serializers.ModelSerializer):
    driver_name = serializers.CharField(source="driver.full_name", read_only=True)  # Fetch driver's full name
    driver = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.exclude(role__in=[User.SYSTEM_ADMIN,User.EMPLOYEE]),  # Ensure only drivers are selectable
        required=False,  # Optional field
        allow_null=True
    )
    class Meta:
        model = Vehicle
        fields = '__all__'

    def validate_driver(self, value):
        """
        Ensure the assigned user is a driver and is not already assigned to another vehicle.
        """
        if value and Vehicle.objects.filter(driver=value).exists():
            raise serializers.ValidationError("This driver is already assigned to another vehicle.")
        return value

class AssignedVehicleSerializer(serializers.ModelSerializer):
    driver_name = serializers.CharField(source="driver.full_name", read_only=True)
    class Meta:
        model = Vehicle
        fields = ['id','driver_name', 'license_plate', 'model', 'capacity', 'status', 'source', 'rental_company']


class NotificationSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(source='recipient.full_name', read_only=True)
    
    class Meta:
        model = Notification
        fields = [
            'id', 'recipient_name', 'notification_type', 'title', 
            'message', 'is_read', 'action_required', 'priority', 
            'metadata', 'created_at'
        ]
        read_only_fields = fields



class MaintenanceRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    requesters_car_name = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceRequest
        fields = ['id', 'requester','requester_name', 'requesters_car', 'requesters_car_name', 'date', 'reason', 'status', 'current_approver_role']
        read_only_fields = ['requester','requester_name','requesters_car', 'requesters_car_name', 'status', 'current_approver_role']


    def get_requester_name(self, obj):
        """Return the full name of the requester instead of their ID."""
        return obj.requester.full_name if obj.requester else "Unknown"

    def get_requesters_car_name(self, obj):
        """Return the vehicle model and license plate instead of the car ID."""
        if obj.requesters_car:
            return f"{obj.requesters_car.model} ({obj.requesters_car.license_plate})"
        return "No Assigned Vehicle"
    def validate(self, data):
        """Ensure the user has an assigned vehicle."""
        user = self.context['request'].user
        if not hasattr(user, 'assigned_vehicle') or user.assigned_vehicle is None:
            raise serializers.ValidationError("You do not have an assigned vehicle.")
        return data

    def create(self, validated_data):
        """Automatically set requester, car, and default statuses."""
        user = self.context['request'].user
        validated_data['requester'] = user
        validated_data['requesters_car'] = user.assigned_vehicle
        validated_data['status'] = 'pending'
        validated_data['current_approver_role'] = user.TRANSPORT_MANAGER  # Default approver
        return super().create(validated_data)

class RefuelingRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    requesters_car_name = serializers.SerializerMethodField()
    class Meta:
        model = RefuelingRequest
        fields = ["id", "requester","requester_name", "requesters_car", 'requesters_car_name',"destination", "status", "current_approver_role", "created_at"]
        read_only_fields = ['id','requester','requester_name','requesters_car', 'requesters_car_name', 'status', 'current_approver_role','created_at']
    
    def get_requester_name(self, obj):
        """Return the full name of the requester instead of their ID."""
        return obj.requester.full_name if obj.requester else "Unknown"

    def get_requesters_car_name(self, obj):
        """Return the vehicle model and license plate instead of the car ID."""
        if obj.requesters_car:
            return f"{obj.requesters_car.model} ({obj.requesters_car.license_plate})"
        return "No Assigned Vehicle"
    
    def validate(self, data):
        """Ensure the user has an assigned vehicle."""
        user = self.context['request'].user
        if not hasattr(user, 'assigned_vehicle') or user.assigned_vehicle is None:
            raise serializers.ValidationError("You do not have an assigned vehicle.")
        return data
