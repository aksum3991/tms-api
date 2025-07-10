from rest_framework import serializers
from .models import Department, User, UserStatusHistory
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer



class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['full_name', 'email', 'phone_number', 'role', 'department','password','confirm_password']

    def validate(self,data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not much")
        
        role = data.get("role")
        department = data.get("department")

        if role != User.SYSTEM_ADMIN and not department:
            raise serializers.ValidationError({"department": "This field is required for non-admin users."})

        return data
    
    def create(self, validated_data):
        validated_data.pop('confirm_password')
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.status = "Pending"  
        user.save()
        return user
       


class AdminApproveSerializer(serializers.ModelSerializer):
    rejection_message = serializers.CharField(write_only=True,required=False)
    class Meta:
        model = User
        fields = ['is_active', 'is_pending','rejection_message']

        def update(self, instance, validated_data):
            action = "approved" if validated_data.get("is_active") else "rejected"
            rejection_message = validated_data.get("rejection_message", "")

            UserStatusHistory.objects.create(
                user=instance,
                status=action,
                rejection_message=rejection_message if action == "rejected" else None
            )

            instance.is_pending = True
            instance.is_active = validated_data.get("is_active")
            instance.save()
            return instance    
class UserDetailSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, 
        required=False,
        allow_blank=True,
        min_length=8,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ['id', 'full_name', 'email', 'phone_number', 'role', 'department', 'signature_image', 'is_active', 'is_pending', 'created_at', 'updated_at', 'password']
        read_only_fields = ['id', 'is_active', 'is_pending', 'created_at', 'updated_at']

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:  # Only update if password was provided
            instance.set_password(password)  # This hashes the password
        return super().update(instance, validated_data)

class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'full_name','role']


class UserStatusHistorySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = UserStatusHistory
        fields = ['id', 'user_email', 'user_full_name', 'status', 'rejection_message', 'timestamp']




class DepartmentSerializer(serializers.ModelSerializer):
    department_manager = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.DEPARTMENT_MANAGER), allow_null=True, required=False
    )

    class Meta:
        model = Department
        fields = ["id", "name", "department_manager"]
    def validate_department_manager(self, value):
        """
        Ensure the assigned user is a department manager and is not already assigned to another department.
        Prevent replacing an existing manager without explicitly removing them first.
        """
        if value:
            if value.role != User.DEPARTMENT_MANAGER:
                raise serializers.ValidationError("The selected user must be a department manager.")

            # Check if the user is already managing another department
            if Department.objects.filter(department_manager=value).exclude(id=self.instance.id if self.instance else None).exists():
                raise serializers.ValidationError("This user is already assigned as a department manager to another department.")

            # Check if the department already has a manager and prevent reassignment
            if self.instance and self.instance.department_manager and self.instance.department_manager != value:
                raise serializers.ValidationError("This department already has a manager. Remove the current manager first.")

        return value

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def get_token(self, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['role'] = user.role  # Ensure 'role' is a field in your User model
        return token