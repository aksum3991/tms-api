from datetime import datetime
from rest_framework import serializers
from auth_app.models import User
from django.utils.timezone import now 
from auth_app.serializers import UserDetailSerializer
from core.models import ActionLog,CouponRequest, HighCostTransportRequest, MaintenanceRequest, MonthlyKilometerLog, RefuelingRequest, ServiceRequest, TransportRequest, Vehicle, Notification
from rest_framework import serializers
from django.utils import timezone
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
    driver_name = serializers.SerializerMethodField()
    driver = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.exclude(role__in=[User.SYSTEM_ADMIN,User.EMPLOYEE]),  # Ensure only drivers are selectable
        required=False,  # Optional field
        allow_null=True
    )
    class Meta:
        model = Vehicle
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']  # Make these fields read-only

    def get_driver_name(self, obj):
        """Get the driver's name if a driver is assigned"""
        if obj.driver:
            return obj.driver.full_name
        return None

    def validate(self, data):
        # Check for rental company if source is rented
        source = data.get('source', getattr(self.instance, 'source', None))
        rental_company = data.get('rental_company', getattr(self.instance, 'rental_company', None))
        department = data.get('department', getattr(self.instance, 'department', None))
        drivers_location = data.get('drivers_location', getattr(self.instance, 'drivers_location', None))

        if source == Vehicle.RENTED and not rental_company:
            raise serializers.ValidationError({"rental_company": "Rental company is required for rented vehicles."})
        
        # Department logic
        if source == Vehicle.RENTED:
            if department:
                raise serializers.ValidationError({"department": "Department should not be set for rented vehicles."})
        elif source == Vehicle.ORGANIZATION_OWNED:
            if not department:
                raise serializers.ValidationError({"department": "Department is required for organization owned vehicles."})

        # Drivers location logic
        if source == Vehicle.RENTED:
            # drivers_location is optional, no error if missing
            pass
        elif source == Vehicle.ORGANIZATION_OWNED:
            if drivers_location:
                raise serializers.ValidationError({"drivers_location": "Drivers location should not be set for organization owned vehicles."})

        return data

class AssignedVehicleSerializer(serializers.ModelSerializer):
    driver_name = serializers.SerializerMethodField()
    
    class Meta:
        model = Vehicle
        fields = ['id', 'driver', 'driver_name', 'license_plate', 'model', 'capacity', 'status', 'source', 'rental_company',
                  'motor_number', 'chassis_number', 'libre_number']

    def get_driver_name(self, obj):
        """Return the driver's full name if assigned"""
        if obj.driver:
            return obj.driver.full_name
        return None

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
        fields = [
            'id', 'requester', 'requester_name', 'requesters_car', 'requesters_car_name',
            'date', 'reason', 'status', 'current_approver_role', 'rejection_message',
            'maintenance_total_cost', 'maintenance_letter', 'receipt_file'
        ]
        read_only_fields = [
            'requester', 'requester_name', 'requesters_car', 'requesters_car_name',
            'status', 'current_approver_role'
        ]

    def get_requester_name(self, obj):
        return obj.requester.full_name if obj.requester else "Unknown"

    def get_requesters_car_name(self, obj):
        return f"{obj.requesters_car.model} ({obj.requesters_car.license_plate})" if obj.requesters_car else "N/A"

    def validate(self, data):

        user = self.context['request'].user
        date = data.get('date')
        if date and date < now().date():
            raise serializers.ValidationError({"date": "Date cannot be in the past."})

        if self.instance and user.role == User.GENERAL_SYSTEM:
            if not data.get('maintenance_letter') or not data.get('receipt_file') or not data.get('maintenance_total_cost'):
                raise serializers.ValidationError("Maintenance letter, receipt, and total cost are required at this stage.")

        return data

    def create(self, validated_data):
        user = self.context['request'].user
        vehicle=user.vehicle.first()
        validated_data['requester'] = user
        validated_data['requesters_car'] = vehicle
        validated_data['status'] = 'pending'
        validated_data['current_approver_role'] = User.TRANSPORT_MANAGER
        return super().create(validated_data)

class RefuelingRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    requesters_car_name = serializers.SerializerMethodField()
    requesters_car = serializers.PrimaryKeyRelatedField(
        queryset=Vehicle.objects.all(),  # We'll restrict in validate()
        required=True
    )
    
    class Meta:
        model = RefuelingRequest
        fields = [
            "id", "requester", "requester_name", "requesters_car", "requesters_car_name",
            "destination", "status", "current_approver_role", "created_at"
        ]
        read_only_fields = [
            'id', 'requester', 'requester_name', 'requesters_car_name',
            'status', 'current_approver_role', 'created_at'
        ]
    
    def get_requester_name(self, obj):
        """Return the full name of the requester instead of their ID."""
        return obj.requester.full_name if obj.requester else "Unknown"

    def get_requesters_car_name(self, obj):
        """Return the vehicle model and license plate instead of the car ID."""
        if obj.requesters_car:
            return f"{obj.requesters_car.model} ({obj.requesters_car.license_plate})"
        return "No Assigned Vehicle"
   
    def validate(self, data):
        """Ensure the selected vehicle is assigned to the user."""
        user = self.context['request'].user
        vehicle = data.get('requesters_car')
        # Only allow vehicles assigned to this user
        if not Vehicle.objects.filter(id=vehicle.id, driver=user).exists():
            raise serializers.ValidationError("You can only request refueling for vehicles assigned to you.")
        return data

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['requester'] = user
        return super().create(validated_data)
    
class RefuelingRequestDetailSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    requesters_car_name = serializers.SerializerMethodField()
    fuel_type = serializers.SerializerMethodField()
    fuel_efficiency = serializers.SerializerMethodField() 
    class Meta:
        model = RefuelingRequest
        fields = [
            "id", "requester", "requester_name", "requesters_car", "requesters_car_name",
            "destination", "date", "estimated_distance_km", "fuel_price_per_liter",
            "fuel_needed_liters", "total_cost", "status", "current_approver_role", "created_at" ,'fuel_type', 'fuel_efficiency'
        ]
        read_only_fields = fields

    def get_requester_name(self, obj):
        return obj.requester.full_name if obj.requester else "Unknown"

    def get_requesters_car_name(self, obj):
        if obj.requesters_car:
            return f"{obj.requesters_car.model} ({obj.requesters_car.license_plate})"
        return "No Assigned Vehicle"
    def get_fuel_type(self,obj):
        if obj.requesters_car and obj.requesters_car.fuel_type:
            return obj.requesters_car.get_fuel_type_display()
        return "Unknown"
    def get_fuel_efficiency(self, obj):
        if obj.requesters_car and obj.requesters_car.fuel_efficiency is not None:
            return f"{obj.requesters_car.fuel_efficiency} km/L"
        return "No fuel efficiency provided for the selected vehicle"

class HighCostTransportRequestSerializer(serializers.ModelSerializer):
    employees = serializers.PrimaryKeyRelatedField(many=True,queryset=User.objects.filter(role=User.EMPLOYEE))
    requester = serializers.ReadOnlyField(source='requester.get_full_name')
    employee_list_file = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = HighCostTransportRequest
        fields = [
            'id','requester','start_day','return_day','start_time','destination','reason','employees','employee_list_file','vehicle','status','current_approver_role','rejection_message','created_at','updated_at'
        ]
    def validate(self, data):
        """
        Ensure return_day is not before start_day.
        """
        start_day = data.get("start_day")
        return_day = data.get("return_day")
        employees = data.get('employees', None)
        employee_list_file = data.get('employee_list_file', None)

        if start_day and start_day < now().date():
            raise serializers.ValidationError({"start_day": "Start date cannot be in the past."})
        
        if return_day and start_day and return_day < start_day:
            raise serializers.ValidationError({"return_day": "Return date cannot be before the start date."})
        if not employees and not employee_list_file:
            raise serializers.ValidationError(
                "You must provide either a list of employees or upload an employee list file."
            )
        return data
    
    def create(self, validated_data): 
        employees = validated_data.pop('employees',[])
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data["requester"] = request.user

        high_cost_request = HighCostTransportRequest.objects.create(**validated_data)
        high_cost_request.employees.set(employees)
        return high_cost_request

# serializers.py
class HighCostTransportRequestDetailSerializer(serializers.ModelSerializer):
    requester = serializers.SerializerMethodField()
    employees = serializers.SerializerMethodField()
    vehicle = serializers.StringRelatedField()
    estimated_vehicle = serializers.StringRelatedField()

    class Meta:
        model = HighCostTransportRequest
        fields = '__all__'

    def get_requester(self, obj):
        return obj.requester.full_name or obj.requester.email

    def get_employees(self, obj):
        return [user.full_name or user.email for user in obj.employees.all()]

class MonthlyKilometerLogSerializer(serializers.ModelSerializer):
    kilometers_driven = serializers.IntegerField(min_value=1)
    vehicle = serializers.SerializerMethodField(read_only=True)  # optional: for display
    recorded_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = MonthlyKilometerLog
        fields = ['id','vehicle', 'kilometers_driven','recorded_by', 'created_at']
    def get_vehicle(self, obj):
        if obj.vehicle:
            return f"Model: {obj.vehicle.model} - License Plate: {obj.vehicle.license_plate}"
        return ""



class CouponRequestSerializer(serializers.ModelSerializer):
    month = serializers.CharField() 
    vehicle_name = serializers.SerializerMethodField(read_only=True)
    requester_name = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = CouponRequest
        fields = ['id', 'vehicle','vehicle_name', 'requester','requester_name','month', 'created_at']
        read_only_fields = ['vehicle', 'month', 'requester', 'created_at']

    def get_vehicle_name(self, obj):
        # Customize as needed, e.g., model and license plate only
        if obj.vehicle.exists():
            vehicle=obj.vehicle.first()
            return f"Model: {vehicle.model} - License Plate: {vehicle.license_plate}"
        return ""

    def get_requester_name(self, obj):
        return obj.requester.full_name
    def validate(self, attrs):
        user = self.context['request'].user
        allowed_roles = [
            user.DEPARTMENT_MANAGER, user.FINANCE_MANAGER, user.TRANSPORT_MANAGER,
            user.CEO, user.DRIVER, user.GENERAL_SYSTEM, user.BUDGET_MANAGER
        ]
        if user.role not in allowed_roles:
            raise serializers.ValidationError("You are not allowed to send a coupon request.")
        vehicles = user.vehicle.all()   
        if not vehicles.exists():
            raise serializers.ValidationError("No vehicle assigned to your account.")
        # Automatically get the user's assigned vehicle
        vehicle = vehicles.first()
        month = attrs.get('month')
        try:
            # This will raise ValueError if the format is wrong
            datetime.strptime(month, '%Y-%m')
        except Exception:
            raise serializers.ValidationError({"month": "month must be in 'YYYY-MM' format."})
        now = timezone.now()
        current_month = now.strftime('%Y-%m')
        if month != current_month:
            raise serializers.ValidationError({"month": "You can only request for the current month."})

        month_display = datetime.strptime(month, '%Y-%m').strftime('%B %Y')


        # Check if kilometer log exists for this vehicle and month
        if not MonthlyKilometerLog.objects.filter(vehicle=vehicle, month=month).exists():
            raise serializers.ValidationError(
                f"Monthly kilometer log for {month_display} not found for your vehicle. Please log kilometers first."
            )
        attrs['vehicle'] = vehicle
        attrs['requester'] = user
        return attrs

    def create(self, validated_data):
        return CouponRequest.objects.create(**validated_data)   

class ActionLogListSerializer(serializers.ModelSerializer):
    request_type = serializers.CharField(source='content_type.model')
    request_id = serializers.IntegerField(source='object_id')
    role_display = serializers.CharField(source='get_approver_role_display')
    action_by = serializers.StringRelatedField()
    request_object = serializers.SerializerMethodField()

    class Meta:
        model = ActionLog
        fields = [
            'id',
            'request_type',
            'request_id',
            'action',
            'action_by',
            'status_at_time',
            'approver_role',
            'role_display',
            'remarks',
            'timestamp',
            'request_object',
        ]
    def get_request_object(self, obj):
        serializer_map = {
            'transportrequest': TransportRequestSerializer,
            'highcosttransportrequest': HighCostTransportRequestSerializer,
            'refuelingrequest': RefuelingRequestDetailSerializer,
            'maintenancerequest': MaintenanceRequestSerializer,
        }

        model_name = obj.content_type.model  # e.g., 'transportrequest'
        serializer_class = serializer_map.get(model_name)

        if serializer_class and obj.request_object:
            return serializer_class(obj.request_object).data
        return None

class ReportFilterSerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    request_type = serializers.ChoiceField(
        choices=['transport', 'highcost', 'maintenance', 'refueling'],
        required=False
    )
    status = serializers.CharField(required=False)

class ServiceRequestSerializer(serializers.ModelSerializer):
    vehicle = serializers.StringRelatedField()

    class Meta:
        model = ServiceRequest
        fields = ['id','vehicle','status','rejection_reason','current_approver_role','created_at','updated_at']
        read_only_fields = ['status','current_approver_role','created_at','updated_at',]  

class ServiceRequestDetailSerializer(serializers.ModelSerializer):
    vehicle = serializers.StringRelatedField()

    class Meta:
        model = ServiceRequest
        fields = '__all__'
        read_only_fields = ['status', 'current_approver_role', 'created_at', 'updated_at'] 