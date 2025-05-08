from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from auth_app.permissions import IsDepartmentManager, IsTransportManager
from auth_app.serializers import UserDetailSerializer
from core import serializers
from core.models import HighCostTransportRequest, MaintenanceRequest, MonthlyKilometerLog, RefuelingRequest, TransportRequest, Vehicle, Notification
from core.permissions import IsAllowedVehicleUser
from core.serializers import AssignedVehicleSerializer, HighCostTransportRequestDetailSerializer, HighCostTransportRequestSerializer, MaintenanceRequestSerializer, MonthlyKilometerLogSerializer, RefuelingRequestDetailSerializer, RefuelingRequestSerializer, TransportRequestSerializer, NotificationSerializer, VehicleSerializer
from core.services import NotificationService, RefuelingEstimator, log_action
from auth_app.models import User
from django.db.models import Q
from django.core.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView
from django.core.exceptions import PermissionDenied
from rest_framework import serializers  
from rest_framework.exceptions import ValidationError  
from rest_framework.parsers import MultiPartParser, FormParser

import logging

logger = logging.getLogger(__name__)
class MyAssignedVehicleView(APIView):
    permission_classes = [permissions.IsAuthenticated,IsAllowedVehicleUser]

    def get(self, request):
        try:
            vehicle = request.user.assigned_vehicle  # Thanks to related_name='assigned_vehicle'
        except Vehicle.DoesNotExist:
            return Response({"message": "No vehicle assigned to you."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AssignedVehicleSerializer(vehicle)
        return Response(serializer.data, status=status.HTTP_200_OK)

class VehicleViewSet(ModelViewSet):
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [IsTransportManager]

    def update(self, request, *args, **kwargs):
        instance = self.get_object() 
        serializer = self.get_serializer(instance, data=request.data, partial=True)  
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)

class AvailableVehiclesListView(generics.ListAPIView):
    queryset = Vehicle.objects.filter(status=Vehicle.AVAILABLE).select_related("driver")
    serializer_class = VehicleSerializer
    permission_classes = [IsTransportManager]

class AvailableDriversView(APIView):
    permission_classes = [IsTransportManager]

    def get(self, request):
        drivers = User.objects.exclude(role__in=[User.SYSTEM_ADMIN,User.EMPLOYEE])  
        drivers=drivers.filter(assigned_vehicle__isnull=True)
        serializer = UserDetailSerializer(drivers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class HighCostTransportRequestCreateView(generics.CreateAPIView):
    serializer_class = HighCostTransportRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsDepartmentManager]

    def perform_create(self, serializer):
        requester = self.request.user
        highcost_request = serializer.save(requester=requester)
        
        ceo = User.objects.filter(role=User.CEO, is_active=True).first()
        if not ceo:
            raise serializers.ValidationError({"error": "No active CEO found."})

        NotificationService.send_highcost_notification(
            notification_type='new_highcost',
            highcost_request=highcost_request,
            recipient=ceo
        )

class HighCostTransportRequestListView(generics.ListAPIView):
    queryset = HighCostTransportRequest.objects.all()
    serializer_class = HighCostTransportRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == user.CEO:
            return HighCostTransportRequest.objects.filter(status='pending')
        elif user.role == user.TRANSPORT_MANAGER:
            return HighCostTransportRequest.objects.filter(
                Q(status='forwarded', current_approver_role=User.TRANSPORT_MANAGER) | Q(status='approved', vehicle_assigned=False))
        elif user.role == user.GENERAL_SYSTEM:
            return HighCostTransportRequest.objects.filter(status="forwarded",current_approver_role=User.GENERAL_SYSTEM)
        elif user.role == user.BUDGET_MANAGER:
            return HighCostTransportRequest.objects.filter(status="forwarded",current_approver_role=User.BUDGET_MANAGER)
        elif user.role == user.FINANCE_MANAGER:
            # Finance manager sees approved requests
            return HighCostTransportRequest.objects.filter(status='approved')   
        elif user.role == User.DRIVER:
            return HighCostTransportRequest.objects.filter(vehicle__driver=user,status='approved')  # Optional: restrict to approved requests only
        return HighCostTransportRequest.objects.filter(requester=user)

class HighCostTransportRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_next_approver_role(self, current_role):
        role_hierarchy = {
            User.CEO: User.GENERAL_SYSTEM,
            User.GENERAL_SYSTEM: User.TRANSPORT_MANAGER,
            User.TRANSPORT_MANAGER: User.BUDGET_MANAGER
        }
        return role_hierarchy.get(current_role, None)

    def post(self, request, request_id):
        highcost_request = get_object_or_404(HighCostTransportRequest, id=request_id)
        action = request.data.get("action")
        current_role = request.user.role

        if current_role != highcost_request.current_approver_role:
            return Response({"error": "Unauthorized action."}, status=403)

        if action not in ['forward', 'reject', 'approve']:
            return Response({"error": "Invalid action."}, status=400)

        # ========== FORWARD ==========
        if action == 'forward':
            if current_role == User.TRANSPORT_MANAGER:
                if not highcost_request.estimated_distance_km or not highcost_request.fuel_price_per_liter:
                    return Response({
                        "error": "You must estimate distance and fuel price before forwarding."
                    }, status=status.HTTP_400_BAD_REQUEST)
            next_role = self.get_next_approver_role(current_role)
            if not next_role:
                return Response({"error": "No further approver available."}, status=400)

            highcost_request.status = 'forwarded'
            highcost_request.current_approver_role = next_role
            highcost_request.save()

            next_approvers =User.objects.filter(role=next_role, is_active=True) 
            for approver in next_approvers:
                NotificationService.send_highcost_notification(
                    'highcost_forwarded',
                    highcost_request,
                    approver
                )

        # ========== REJECT ==========
        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=400)

            highcost_request.status = 'rejected'
            highcost_request.rejection_message = rejection_message
            highcost_request.save()

            NotificationService.send_highcost_notification(
                'highcost_rejected',
                highcost_request,
                highcost_request.requester,
                rejector=request.user.full_name,
                rejection_reason=rejection_message
            )

        # ========== APPROVE (BUDGET_MANAGER) ==========
        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER and highcost_request.current_approver_role == User.BUDGET_MANAGER:
                highcost_request.status = 'approved'
                highcost_request.save()

                # Notify the requester and stakeholders
                NotificationService.send_highcost_notification(
                    'highcost_approved',
                    highcost_request,
                    highcost_request.requester
                )
                NotificationService.send_highcost_notification(
                    'highcost_approved',
                    highcost_request,
                    User.objects.get(role=User.FINANCE_MANAGER)
                )
                NotificationService.send_highcost_notification(
                    'highcost_approved',
                    highcost_request,
                    User.objects.get(role=User.TRANSPORT_MANAGER)
                )
            else:
                return Response({"error": "Approval not allowed at this stage."}, status=403)

        return Response({"message": f"Request {action}ed successfully."}, status=200)


class HighCostTransportEstimateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, request_id):
        if request.user.role != User.TRANSPORT_MANAGER:
            return Response({"error": "Unauthorized: Only Transport Manager can perform this action."}, status=403)

        highcost_request = get_object_or_404(HighCostTransportRequest, id=request_id)

        distance = request.data.get('estimated_distance_km')
        fuel_price = request.data.get('fuel_price_per_liter')
        estimated_vehicle_id = request.data.get('estimated_vehicle_id')

        if not distance or not fuel_price or not estimated_vehicle_id:
            return Response({"error": "All fields are required: estimated_distance_km, fuel_price_per_liter, estimated_vehicle_id."}, status=400)

        try:
            distance = float(distance)
            fuel_price = float(fuel_price)
        except ValueError:
            return Response({"error": "Distance and fuel price must be numeric."}, status=400)

        # Fetch and validate vehicle
        try:
            vehicle = Vehicle.objects.get(id=estimated_vehicle_id)
            if not vehicle.fuel_efficiency or vehicle.fuel_efficiency <= 0 or vehicle.status != Vehicle.AVAILABLE:
                return Response({
                    "error": "Selected vehicle must be available and have a valid fuel efficiency greater than zero."
                }, status=400)            
        except Vehicle.DoesNotExist:
            return Response({"error": "Invalid vehicle selected."}, status=404)

        try:
            fuel_needed = distance / float(vehicle.fuel_efficiency)
            total_cost = fuel_needed * fuel_price
        except Exception as e:
            return Response({"error": str(e)}, status=400)

        # Save estimation data to request
        highcost_request.estimated_distance_km = distance
        highcost_request.fuel_price_per_liter = fuel_price
        highcost_request.fuel_needed_liters = round(fuel_needed, 2)
        highcost_request.total_cost = round(total_cost, 2)
        highcost_request.estimated_vehicle = vehicle
        highcost_request.save()

        return Response({
            "fuel_needed_liters": round(fuel_needed, 2),
            "total_cost": round(total_cost, 2),
            "estimated_vehicle": vehicle.id
        }, status=200)

class AssignVehicleAfterBudgetApprovalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, request_id):
        highcost_request = get_object_or_404(HighCostTransportRequest, id=request_id)

        if request.user.role != User.TRANSPORT_MANAGER:
            return Response({"error": "Unauthorized"}, status=403)

        if highcost_request.status != 'approved':
            return Response({"error": "Vehicle can only be assigned after budget approval."}, status=400)

        vehicle = highcost_request.estimated_vehicle
        if vehicle.status != Vehicle.AVAILABLE:
            return Response({"error": "Selected vehicle is not available."}, status=400)

        try:
            vehicle.mark_as_in_use()
        except ValidationError as e:
            return Response({"error": str(e)}, status=400)


        # NotificationService.send_highcost_notification(
        #       'assigned', highcost_request, highcost_request.vehicle.driver,
        #         vehicle=f"{highcost_request.vehicle.model} ({highcost_request.vehicle.license_plate})", destination=highcost_request.destination,
        #         date=highcost_request.start_day.strftime('%Y-%m-%d'), start_time=highcost_request.start_time.strftime('%H:%M')
        # )
        # NotificationService.send_highcost_notification(
        #       'assigned', highcost_request, highcost_request.requester,
        #         vehicle=f"{highcost_request.vehicle.model} ({highcost_request.vehicle.license_plate})", destination=highcost_request.destination,
        #         date=highcost_request.start_day.strftime('%Y-%m-%d'), start_time=highcost_request.start_time.strftime('%H:%M')
        # )

        highcost_request.vehicle = vehicle
        highcost_request.vehicle_assigned = True
        highcost_request.save()
        return Response({"message": "Vehicle assigned and status updated successfully."}, status=200)


class HighCostTransportRequestDetailView(generics.RetrieveAPIView):
    queryset = HighCostTransportRequest.objects.all()
    serializer_class = HighCostTransportRequestDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'


class TransportRequestCreateView(generics.CreateAPIView):
    queryset = TransportRequest.objects.all()
    serializer_class = TransportRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def perform_create(self, serializer):
        employee = self.request.user
        department = employee.department  # Get the department of the employee
        
        if not department:
            raise serializers.ValidationError("You are not assigned to any department.")

        department_manager = User.objects.filter(department=department, role=User.DEPARTMENT_MANAGER, is_active=True).first()
        
        if not department_manager:
            raise serializers.ValidationError("No department manager is assigned to your department.")

        transport_request = serializer.save(requester=employee)
        
        # Notify department managers of the employee's department
        # for manager in department_managers:
        NotificationService.create_notification(
            'new_request',
            transport_request,
            department_manager
        )


class TransportRequestListView(generics.ListAPIView):
    queryset = TransportRequest.objects.all()
    serializer_class = TransportRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == user.DEPARTMENT_MANAGER:
            return TransportRequest.objects.filter(status='pending',requester__department=user.department)
        elif user.role == user.TRANSPORT_MANAGER:
            return TransportRequest.objects.filter(status='forwarded',current_approver_role=User.TRANSPORT_MANAGER)
        elif user.role == user.CEO:
            # CEO can see all approved requests
            return TransportRequest.objects.filter(status='forwarded',current_approver_role=User.CEO)
        elif user.role == user.FINANCE_MANAGER:
            # Finance manager sees approved requests
            return TransportRequest.objects.filter(status='forwarded',current_approver_role=User.FINANCE_MANAGER)
        # Regular users see their own requests         
        elif user.role == User.DRIVER:
            return TransportRequest.objects.filter(vehicle__driver=user,status='approved')  # Optional: restrict to approved requests only
        return TransportRequest.objects.filter(requester=user)
    
class MaintenanceRequestCreateView(generics.CreateAPIView):
    serializer_class = MaintenanceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    ALLOWED_ROLES = [
        User.DEPARTMENT_MANAGER,
        User.FINANCE_MANAGER,
        User.TRANSPORT_MANAGER,
        User.CEO,
        User.DRIVER,
        User.GENERAL_SYSTEM,
        User.BUDGET_MANAGER,
    ]

    def perform_create(self, serializer):
        """Override to set requester and their assigned vehicle automatically."""
        user = self.request.user
        if user.role not in self.ALLOWED_ROLES:
            raise serializers.ValidationError({"error": "You are not authorized to submit a refueling request."})
        # if not hasattr(user, 'assigned_vehicle') or user.assigned_vehicle is None:
        #     raise serializers.ValidationError({"error": "You do not have an assigned vehicle."})

        transport_manager = User.objects.filter(role=User.TRANSPORT_MANAGER, is_active=True).first()

        if not transport_manager:
            raise serializers.ValidationError({"error": "No active Transport Manager found."})

        # Save the maintenance request
        maintenance_request = serializer.save(requester=user, requesters_car=user.assigned_vehicle)

        # Now correctly call the notification service with the correct parameters
        NotificationService.send_maintenance_notification(
            notification_type='new_maintenance',
            maintenance_request=maintenance_request,  
            recipient=transport_manager  
        )       


class RefuelingRequestCreateView(generics.CreateAPIView):
    serializer_class = RefuelingRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    ALLOWED_ROLES = [
        User.DEPARTMENT_MANAGER,
        User.FINANCE_MANAGER,
        User.TRANSPORT_MANAGER,
        User.CEO,
        User.DRIVER,
        User.GENERAL_SYSTEM,
        User.BUDGET_MANAGER,
    ]

    def perform_create(self, serializer):
        """Set the requester and default approver before saving."""
        user = self.request.user
        if user.role not in self.ALLOWED_ROLES:
            raise serializers.ValidationError({"error": "You are not authorized to submit a refueling request."})
        if not hasattr(user, 'assigned_vehicle') or user.assigned_vehicle is None:
            raise serializers.ValidationError({"error": "You do not have an assigned vehicle."})
        transport_manager = User.objects.filter(role=User.TRANSPORT_MANAGER, is_active=True).first()

        if not transport_manager:
            raise serializers.ValidationError({"error": "No active Transport Manager found."})
        refueling_request=serializer.save(requester=user,requesters_car=user.assigned_vehicle)
        NotificationService.send_refueling_notification(
            notification_type='new_refueling',
            refueling_request=refueling_request,
            recipient=transport_manager
        )
class RefuelingRequestListView(generics.ListAPIView):
    queryset = RefuelingRequest.objects.all()
    serializer_class = RefuelingRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == user.TRANSPORT_MANAGER:
            return RefuelingRequest.objects.filter(status='pending')
        elif user.role == user.CEO:
            return RefuelingRequest.objects.filter(status='forwarded',current_approver_role=User.CEO)
        elif user.role == user.GENERAL_SYSTEM:
            return RefuelingRequest.objects.filter(status="forwarded",current_approver_role=User.GENERAL_SYSTEM)
        elif user.role == user.BUDGET_MANAGER:
            return RefuelingRequest.objects.filter(status="forwarded",current_approver_role=User.BUDGET_MANAGER)
        elif user.role == user.FINANCE_MANAGER:
            # Finance manager sees approved requests
            return RefuelingRequest.objects.filter(status='approved')
        return RefuelingRequest.objects.filter(requester=user)
    
class RefuelingRequestOwnListView(generics.ListAPIView):
    serializer_class = RefuelingRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return RefuelingRequest.objects.filter(requester=user)
class RefuelingRequestEstimateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, request_id):
        refueling_request = get_object_or_404(RefuelingRequest, id=request_id)
        if request.user.role != User.TRANSPORT_MANAGER:
            return Response({"error": "Unauthorized"}, status=403)

        distance = request.data.get('estimated_distance_km')
        price = request.data.get('fuel_price_per_liter')

        if not distance or not price:
            return Response({"error": "Distance and fuel price are required."}, status=400)

        try:
            distance = float(distance)
            price = float(price)
            fuel_needed, total_cost = RefuelingEstimator.calculate_fuel_cost(
                distance, refueling_request.requesters_car, price
            )
        except Exception as e:
            return Response({"error": str(e)}, status=400)

        refueling_request.estimated_distance_km = distance
        refueling_request.fuel_price_per_liter = price
        refueling_request.fuel_needed_liters = fuel_needed
        refueling_request.total_cost = total_cost
        refueling_request.save()

        return Response({
            "fuel_needed_liters": fuel_needed,
            "total_cost": total_cost
        }, status=200)   
class RefuelingRequestDetailView(RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RefuelingRequestDetailSerializer
    queryset = RefuelingRequest.objects.all()

    def get(self, request, *args, **kwargs):
        refueling_request = self.get_object()

        if request.user.role not in [
            User.TRANSPORT_MANAGER,
            User.GENERAL_SYSTEM,
            User.CEO,
            User.BUDGET_MANAGER,
            User.FINANCE_MANAGER,
            User.DEPARTMENT_MANAGER,
            User.DRIVER,
        ]:
            return Response({"error": "Access denied."}, status=403)

        serializer = self.get_serializer(refueling_request)
        return Response(serializer.data)

class RefuelingRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_next_approver_role(self, current_role):
        """Determine the next approver based on hierarchy."""
        role_hierarchy = {
            User.TRANSPORT_MANAGER: User.GENERAL_SYSTEM,
            User.GENERAL_SYSTEM: User.CEO,
            User.CEO: User.BUDGET_MANAGER,
        }
        return role_hierarchy.get(current_role, None)

    def post(self, request, request_id):
        refueling_request = get_object_or_404(RefuelingRequest, id=request_id)
        action = request.data.get("action")

        if action not in ['forward', 'reject', 'approve']:
            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        current_role = request.user.role
        if current_role != refueling_request.current_approver_role:
            return Response({"error": "You are not authorized to act on this request."}, status=status.HTTP_403_FORBIDDEN)

        # ====== FORWARD ACTION ======
        if action == 'forward':
            if current_role == User.TRANSPORT_MANAGER:
                # Ensure estimation is already completed before forwarding
                if not refueling_request.estimated_distance_km or not refueling_request.fuel_price_per_liter:
                    return Response({
                        "error": "You must estimate distance and fuel price before forwarding."
                    }, status=status.HTTP_400_BAD_REQUEST)
            next_role = self.get_next_approver_role(current_role)
            if not next_role:
                return Response({"error": "No further approver available."}, status=status.HTTP_400_BAD_REQUEST)

            refueling_request.status = 'forwarded'
            refueling_request.current_approver_role = next_role
            # # # Notify the next approver

            next_approvers = User.objects.filter(role=next_role, is_active=True)
            for approver in next_approvers:
                NotificationService.send_refueling_notification(
                    notification_type='refueling_forwarded',
                    refueling_request=refueling_request,
                    recipient=approver
                )
            refueling_request.save()

        # ====== REJECT ACTION ======
        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=status.HTTP_400_BAD_REQUEST)

            refueling_request.status = 'rejected'
            refueling_request.rejection_message = rejection_message
            refueling_request.save()

            # # # Notify requester of rejection
            NotificationService.send_refueling_notification(
                'refueling_rejected', refueling_request, refueling_request.requester,
                rejector=request.user.full_name, rejection_reason=rejection_message
                )
        # ====== APPROVE ACTION ======
        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER and refueling_request.current_approver_role == User.BUDGET_MANAGER:
                # Final approval by Transport Manager after Finance Manager has approved
                refueling_request.status = 'approved'
                refueling_request.save()
                
                finance_manger= User.objects.filter(role=User.FINANCE_MANAGER).first()
                # # # Notify the original requester of approval
                NotificationService.send_refueling_notification(
                    'refueling_approved', refueling_request, refueling_request.requester,
                    approver=request.user.full_name
                )
                NotificationService.send_refueling_notification(
                   'refueling_approved',refueling_request, finance_manger,approver=request.user.full_name
                )
            else:
                return Response({"error": f"{request.user.get_role_display()} cannot approve this request at this stage."}, 
                                status=status.HTTP_403_FORBIDDEN)
        else:
             Response({"error": "Unexpected error occurred."}, status=status.HTTP_400_BAD_REQUEST)
        return  Response({"message": f"Request {action}ed successfully."}, status=status.HTTP_200_OK)
   
class MaintenanceRequestListView(generics.ListAPIView):
    queryset = MaintenanceRequest.objects.all()
    serializer_class = MaintenanceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == User.TRANSPORT_MANAGER:
            return MaintenanceRequest.objects.filter(status='pending', current_approver_role=User.TRANSPORT_MANAGER)
        elif user.role == User.GENERAL_SYSTEM:
            return MaintenanceRequest.objects.filter(status='forwarded', current_approver_role=User.GENERAL_SYSTEM)
        elif user.role == User.CEO:
            return MaintenanceRequest.objects.filter(status='forwarded', current_approver_role=User.CEO)
        elif user.role == User.BUDGET_MANAGER:
            return MaintenanceRequest.objects.filter(status='forwarded', current_approver_role=User.BUDGET_MANAGER)
        elif user.role == User.FINANCE_MANAGER:
            return MaintenanceRequest.objects.filter(status='approved')
        return MaintenanceRequest.objects.none()
    
class MaintenanceRequestOwnListView(generics.ListAPIView):
    serializer_class = MaintenanceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return MaintenanceRequest.objects.filter(requester=user)

class MaintenanceRequestDetailView(generics.RetrieveAPIView):
    queryset = MaintenanceRequest.objects.all()
    serializer_class = MaintenanceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        request_id = self.kwargs.get("pk")
        obj = get_object_or_404(MaintenanceRequest, id=request_id)

        user = self.request.user

        allowed_roles = [
            User.TRANSPORT_MANAGER,
            User.GENERAL_SYSTEM,
            User.CEO,
            User.BUDGET_MANAGER,
            User.FINANCE_MANAGER
        ]

        if user != obj.requester and user.role not in allowed_roles:
            raise PermissionDenied("You do not have permission to view this maintenance request.")

        return obj
    
class MaintenanceRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_next_approver_role(self, current_role):
        """Define approver hierarchy."""
        role_hierarchy = {
            User.TRANSPORT_MANAGER: User.GENERAL_SYSTEM,
            User.GENERAL_SYSTEM: User.CEO,
            User.CEO: User.BUDGET_MANAGER,
        }
        return role_hierarchy.get(current_role, None)

    def post(self, request, request_id):
        maintenance_request = get_object_or_404(MaintenanceRequest, id=request_id)
        action = request.data.get("action")

        if action not in ['forward', 'reject', 'approve']:
            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        current_role = request.user.role

        if current_role != maintenance_request.current_approver_role:
            return Response({"error": "You are not authorized to act on this request."}, status=status.HTTP_403_FORBIDDEN)

        # ===== FORWARD LOGIC =====
        if action == 'forward':
            # General System MUST submit files and cost before forwarding
            if current_role == User.GENERAL_SYSTEM:
                missing = []

                if not maintenance_request.maintenance_letter:
                    missing.append('maintenance_letter')
                if not maintenance_request.receipt_file:
                    missing.append('receipt_file')
                if maintenance_request.maintenance_total_cost is None:
                    missing.append('maintenance_total_cost')

                if missing:
                    return Response(
                        {"error": f"The following files must be submitted before forwarding: {', '.join(missing)}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            next_role = self.get_next_approver_role(current_role)
            if not next_role:
                return Response({"error": "No further approver available."}, status=status.HTTP_400_BAD_REQUEST)

            maintenance_request.status = 'forwarded'
            maintenance_request.current_approver_role = next_role
            maintenance_request.save()

            # Notify next approver(s)
            next_approvers = User.objects.filter(role=next_role, is_active=True)
            for approver in next_approvers:
                NotificationService.send_maintenance_notification(
                    'maintenance_forwarded', maintenance_request, approver
                )

            return Response({"message": "Request forwarded successfully."}, status=status.HTTP_200_OK)

        # ===== REJECT LOGIC =====
        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=status.HTTP_400_BAD_REQUEST)

            maintenance_request.status = 'rejected'
            maintenance_request.rejection_message = rejection_message
            maintenance_request.save()

            NotificationService.send_maintenance_notification(
                'maintenance_rejected', maintenance_request, maintenance_request.requester,
                rejector=request.user.full_name, rejection_reason=rejection_message
            )

            return Response({"message": "Request rejected successfully."}, status=status.HTTP_200_OK)

        # ===== APPROVE LOGIC =====
        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER:
                # Final approval
                maintenance_request.status = 'approved'
                maintenance_request.save()

                # Notify requester
                NotificationService.send_maintenance_notification(
                    'maintenance_approved', maintenance_request, maintenance_request.requester,
                    approver=request.user.full_name
                )

                # Notify finance manager
                finance_managers = User.objects.filter(role=User.FINANCE_MANAGER, is_active=True)
                for fm in finance_managers:
                    NotificationService.send_maintenance_notification(
                        'maintenance_approved', maintenance_request, recipient=fm
                    )

                return Response({"message": "Request approved successfully and finance notified."}, status=status.HTTP_200_OK)

            else:
                return Response({
                    "error": f"{request.user.get_role_display()} cannot approve this request at this stage."
                }, status=status.HTTP_403_FORBIDDEN)

        return Response({"error": "Unexpected action or failure."}, status=status.HTTP_400_BAD_REQUEST)


class MaintenanceFileSubmissionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request, request_id):
        if request.user.role != User.GENERAL_SYSTEM:
            return Response({"error": "Only General System can perform this action."}, status=status.HTTP_403_FORBIDDEN)

        maintenance_request = get_object_or_404(MaintenanceRequest, id=request_id)

        if maintenance_request.current_approver_role != User.GENERAL_SYSTEM:
            return Response(
                {"error": "This request is not currently under General System review."},
                status=status.HTTP_400_BAD_REQUEST
            )

        letter_file = request.FILES.get('maintenance_letter_file')
        receipt_file = request.FILES.get('maintenance_receipt_file')
        total_cost = request.data.get('maintenance_total_cost')

        if not letter_file or not receipt_file or not total_cost:
            return Response(
                {"error": "All fields (letter file, receipt file, and total cost) are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        maintenance_request.maintenance_letter = letter_file
        maintenance_request.receipt_file = receipt_file
        maintenance_request.maintenance_total_cost = total_cost
        maintenance_request.save()

        return Response({"message": "Maintenance files and cost submitted successfully."}, status=status.HTTP_200_OK)


class TransportRequestActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_next_approver_role(self, current_role):
        """Determine the next approver based on hierarchy."""
        role_hierarchy = {
            User.DEPARTMENT_MANAGER: User.TRANSPORT_MANAGER,
            User.TRANSPORT_MANAGER: User.CEO,
            User.CEO: User.FINANCE_MANAGER,
            User.FINANCE_MANAGER: User.TRANSPORT_MANAGER,
        }
        return role_hierarchy.get(current_role, None)  
    def post(self, request, request_id):
        transport_request = get_object_or_404(TransportRequest, id=request_id)
        action = request.data.get("action")

        if action not in ['forward', 'reject', 'approve']:
            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        if request.user.role == User.DEPARTMENT_MANAGER and transport_request.requester.department != request.user.department:
            return Response(
                {"error": "You can only manage requests from employees in your department."},
                status=status.HTTP_403_FORBIDDEN
            )

        current_role = request.user.role
        if current_role != transport_request.current_approver_role:
            return Response({"error": "You are not authorized to act on this request."}, status=status.HTTP_403_FORBIDDEN)

        if action == 'forward':
            next_role = self.get_next_approver_role(current_role)
            if not next_role:
                return Response({"error": "No further approver available."}, status=status.HTTP_400_BAD_REQUEST)

            transport_request.status = 'forwarded'
            transport_request.current_approver_role = next_role

            # Notify the next approver
            next_approvers = User.objects.filter(role=next_role, is_active=True)
            for approver in next_approvers:
                NotificationService.create_notification('forwarded', transport_request, approver)
            log_action(transport_request, request.user, 'forwarded')

        elif action == 'reject':
            transport_request.status = 'rejected'
            transport_request.rejection_message = request.data.get("rejection_message", "")

            # Notify requester of rejection
            NotificationService.create_notification(
                'rejected', transport_request, transport_request.requester, rejector=request.user.full_name
            )
            log_action(transport_request, request.user, 'rejected', remarks=transport_request.rejection_message)

        elif action == 'approve' and current_role == User.TRANSPORT_MANAGER:
            vehicle_id = request.data.get("vehicle_id")
            vehicle = Vehicle.objects.select_related("driver").filter(id=vehicle_id).first()

            if not vehicle:
                return Response({"error": "Invalid vehicle ID."}, status=status.HTTP_400_BAD_REQUEST)
            
            if vehicle.status != Vehicle.AVAILABLE:
                return Response({"error":"Vehicle is not available"})

            if not vehicle.driver:
                return Response({"error": "Selected vehicle does not have an assigned driver."}, status=status.HTTP_400_BAD_REQUEST)

            # Notify requester and driver
            NotificationService.create_notification(
                'approved', transport_request, transport_request.requester,
                approver=request.user.full_name, vehicle=f"{vehicle.model} ({vehicle.license_plate})",
                driver=vehicle.driver.full_name, destination=transport_request.destination,
                date=transport_request.start_day.strftime('%Y-%m-%d'), start_time=transport_request.start_time.strftime('%H:%M')
            )

            NotificationService.create_notification(
                'assigned', transport_request, vehicle.driver,
                vehicle=f"{vehicle.model} ({vehicle.license_plate})", destination=transport_request.destination,
                date=transport_request.start_day.strftime('%Y-%m-%d'), start_time=transport_request.start_time.strftime('%H:%M')
            )

            transport_request.vehicle = vehicle
            transport_request.status = 'approved'
            vehicle.mark_as_in_use()
            log_action(transport_request, request.user, 'approved', remarks=f"Vehicle: {vehicle.license_plate}")

        else:
            return Response({"error": f"{current_role} cannot perform {action}."}, status=status.HTTP_403_FORBIDDEN)

        transport_request.save()
        return Response({"message": f"Request {action}ed successfully."}, status=status.HTTP_200_OK)

class TransportRequestHistoryView(generics.ListAPIView):
    serializer_class = TransportRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return TransportRequest.objects.filter(action_logs__action_by=user).distinct()

class TripCompletionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, request_id):
        if 'highcost-requests' in request.path:
            trip_request = get_object_or_404(HighCostTransportRequest, id=request_id)
        else:
            trip_request = get_object_or_404(TransportRequest, id=request_id)

        # Validate vehicle and driver
        if not trip_request.vehicle:
            return Response({"error": "Vehicle not assigned yet."}, status=400)

        if trip_request.vehicle.driver != request.user:
            return Response({"error": "Only the assigned driver can complete this trip."}, status=403)

        trip_request.trip_completed=True
        trip_request.vehicle.mark_as_available()
        trip_request.save()
        # # Notify transport manager
        transport_manager = User.objects.filter(role=User.TRANSPORT_MANAGER).first()
        if transport_manager:
           NotificationService.send_trip_completion_notification(
                transport_request=trip_request,
                recipient=transport_manager,
                completer=request.user.full_name
            )

        return Response({"message": "Trip successfully marked as completed."}, status=200)

class NotificationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """
        Get user's notifications with pagination
        """
        unread_only = request.query_params.get('unread_only', 'false').lower() == 'true'
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))

        notifications = NotificationService.get_user_notifications(
            request.user.id, 
            unread_only=unread_only,
            page=page,
            page_size=page_size
        )

        serializer = NotificationSerializer(notifications, many=True)
        return Response({
            'results': serializer.data,
            'unread_count': NotificationService.get_unread_count(request.user.id)
        })


class NotificationMarkReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, notification_id):
        """
        Mark a notification as read
        """
        try:
            notification = Notification.objects.get(
                id=notification_id,
                recipient=request.user
            )
            notification.mark_as_read()
            return Response(status=status.HTTP_200_OK)
        except Notification.DoesNotExist:
            return Response(
                {"error": "Notification not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class NotificationMarkAllReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        Mark all notifications as read for the current user
        """
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response(status=status.HTTP_200_OK)


class NotificationUnreadCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """
        Get count of unread notifications
        """
        count = NotificationService.get_unread_count(request.user.id)
        return Response({'unread_count': count})
       
class AddMonthlyKilometersView(generics.CreateAPIView):
    serializer_class = MonthlyKilometerLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        vehicle_id = self.kwargs.get('vehicle_id')
        vehicle = get_object_or_404(Vehicle, id=vehicle_id)

        kilometers = serializer.validated_data['kilometers_driven']
        month = serializer.validated_data['month']

        # Save the log
        MonthlyKilometerLog.objects.create(
            vehicle=vehicle,
            kilometers_driven=kilometers,
            month=month,
            recorded_by=self.request.user
        )

        # Update vehicle total kilometers
        vehicle.total_kilometers += kilometers
        vehicle.save()

        # Check service threshold
        if (vehicle.total_kilometers - vehicle.last_service_kilometers) >= 5000:
            self.send_service_notification(vehicle)
              
        transport_managers = User.objects.filter(role=User.TRANSPORT_MANAGER, is_active=True)
        general_systems = User.objects.filter(role=User.GENERAL_SYSTEM, is_active=True)
        driver = vehicle.driver  # or vehicle.assigned_driver depending on your model

        if not driver:
            raise ValueError("Vehicle has no assigned driver.")

        recipients = list(transport_managers) + list(general_systems) + [driver]

        NotificationService.send_service_notification(
            vehicle=vehicle,
            recipients=recipients
        )