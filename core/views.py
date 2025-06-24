from datetime import datetime
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from auth_app.permissions import IsDepartmentManager, IsTransportManager
from auth_app.serializers import UserDetailSerializer
from core import serializers
from core.mixins import OTPVerificationMixin, SignatureVerificationMixin
from core.models import ActionLog, CouponRequest, HighCostTransportRequest, MaintenanceRequest, MonthlyKilometerLog, RefuelingRequest, ServiceRequest, TransportRequest, Vehicle, Notification
from core.otp_manager import OTPManager
from core.permissions import IsAllowedVehicleUser
from core.serializers import ActionLogListSerializer, AssignedVehicleSerializer, CouponRequestSerializer, HighCostTransportRequestDetailSerializer, HighCostTransportRequestSerializer, MaintenanceRequestSerializer, MonthlyKilometerLogSerializer, RefuelingRequestDetailSerializer, RefuelingRequestSerializer, ReportFilterSerializer, ServiceRequestDetailSerializer, ServiceRequestSerializer, TransportRequestSerializer, NotificationSerializer, VehicleSerializer
from core.services import NotificationService, RefuelingEstimator, compare_signatures, log_action, send_sms
from auth_app.models import User
from django.db.models import Q, F, OuterRef,Subquery,Exists
from django.core.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView
from django.core.exceptions import PermissionDenied
from rest_framework import serializers  
from rest_framework.exceptions import ValidationError  
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone

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
class AvailableOrganizationVehiclesListView(generics.ListAPIView):
    queryset = Vehicle.objects.filter(source=Vehicle.ORGANIZATION_OWNED, status=Vehicle.AVAILABLE,driver__role=User.DRIVER).select_related("driver")
    serializer_class = VehicleSerializer
    permission_classes = [IsTransportManager]

    # def get_queryset(self):
    #     return Vehicle.objects.filter(source=Vehicle.ORGANIZATION_OWNED, status=Vehicle.AVAILABLE,driver__role=User.DRIVER).select_related("driver")   

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

class HighCostTransportRequestActionView(SignatureVerificationMixin,OTPVerificationMixin,APIView): 
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
        
        # otp_code = request.data.get("otp_code")
        # if not otp_code:
        #     return Response({"error": "OTP code is required."}, status=status.HTTP_400_BAD_REQUEST)
        # otp_error = self.verify_otp(request.user, otp_code, request)
        # if otp_error:
        #     return otp_error
        # error_response = self.verify_signature(request)
        # if error_response:
        #     return error_response
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
            # log_action(request_obj=highcost_request,user=request.user,action="forwarded",remarks=request.data.get("remarks"))

            next_approvers =User.objects.filter(role=next_role, is_active=True) 
            for approver in next_approvers:
                NotificationService.send_highcost_notification(
                    'highcost_forwarded',
                    highcost_request,
                    approver
                )
                employee_names = list(
                    highcost_request.employees.exclude(id=highcost_request.requester_id)
                    .values_list('full_name', flat=True)
                )

                # Format the names into a string
                if employee_names:
                    group_info = " With Employees: " + ", ".join(employee_names) + "."
                else:
                    group_info = ""

                
                if approver.phone_number:
                    sms_message = (
                        f"High-cost transport request {highcost_request.destination} has been forwarded for your approval. here is the list of employees: {group_info}."
                    )
                    try:
                        send_sms(approver.phone_number, sms_message)
                    except Exception as e:
                        logger.error(f"Failed to send SMS to {approver.full_name}: {e}")

        # ========== REJECT ==========
        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=400)

            highcost_request.status = 'rejected'
            highcost_request.rejection_message = rejection_message
            highcost_request.save()
            log_action(request_obj=highcost_request,user=request.user,action="rejected",remarks=highcost_request.rejection_message)


            NotificationService.send_highcost_notification(
                'highcost_rejected',
                highcost_request,
                highcost_request.requester,
                rejector=request.user.full_name,
                rejection_reason=rejection_message
            )
            if highcost_request.requester.phone_number:
                sms_message = (
                    f"Your high-cost transport request {highcost_request.destination} was rejected by {request.user.full_name}. "
                    f"Reason: {rejection_message}"
                )
                try:
                    send_sms(highcost_request.requester.phone_number, sms_message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {highcost_request.requester.full_name}: {e}")
        # ========== APPROVE (BUDGET_MANAGER) ==========
        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER and highcost_request.current_approver_role == User.BUDGET_MANAGER:
                highcost_request.status = 'approved'
                highcost_request.save()
                log_action(request_obj=highcost_request,user=request.user,action="approved",remarks=request.data.get("remarks"))

                approver = request.user.full_name
                finance_manager = User.objects.get(role=User.FINANCE_MANAGER)
                transport_manager = User.objects.get(role=User.TRANSPORT_MANAGER)
                # Notify the requester and stakeholders
                NotificationService.send_highcost_notification(
                    'highcost_approved',
                    highcost_request,
                    highcost_request.requester,
                    approver=approver
                )
                NotificationService.send_highcost_notification(
                    'highcost_approved',
                    highcost_request,
                    finance_manager,
                    approver=approver
                )
                NotificationService.send_highcost_notification(
                    'highcost_approved',
                    highcost_request,
                    transport_manager,
                    approver=approver
                )

                for user in [highcost_request.requester, finance_manager, transport_manager]:
                    if user.phone_number:
                        sms_message = (
                            f"High-cost transport request {highcost_request.destination} has been approved by {approver}."
                        )
                        try:
                            send_sms(user.phone_number, sms_message)
                        except Exception as e:
                            logger.error(f"Failed to send SMS to {user.full_name}: {e}")
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

        highcost_request.vehicle = vehicle
        highcost_request.vehicle_assigned = True
        highcost_request.save()

        driver = vehicle.driver
        vehicle_str = f"{vehicle.model} ({vehicle.license_plate})"
        # Notify driver
        NotificationService.send_highcost_notification(
            'assigned',
            highcost_request,
            driver,
            vehicle=vehicle_str,
            destination=highcost_request.destination,
            date=highcost_request.start_day.strftime('%Y-%m-%d'),
            start_time=highcost_request.start_time.strftime('%H:%M'),
            passengers=", ".join([e.full_name for e in highcost_request.employees.all()])
        )

        NotificationService.send_highcost_notification(
            'highcost_vehicle_assigned',
            highcost_request,
            highcost_request.requester,
            vehicle=vehicle_str,
            driver=driver.full_name,
            driver_phone=driver.phone_number,  
            destination=highcost_request.destination,
            date=highcost_request.start_day.strftime('%Y-%m-%d'),
            start_time=highcost_request.start_time.strftime('%H:%M')
        )
        employee_names = list(
                    highcost_request.employees.exclude(id=highcost_request.requester_id)
                    .values_list('full_name', flat=True)
                )

                # Format the names into a string
        if employee_names:
            group_info = " With Employees: " + ", ".join(employee_names) + "."
        else:
            group_info = ""
        try:
            message = (
                f"You are assigned for transport request to {highcost_request.destination} on "
                f"{highcost_request.start_day.strftime('%Y-%m-%d')} at {highcost_request.start_time.strftime('%H:%M')} "
                f"with vehicle {vehicle.model} ({vehicle.license_plate}).{group_info}"
            )
            send_sms(vehicle.driver.phone_number, message)
        except Exception as sms_error:
                logger.error(f"Failed to send SMS to driver {vehicle.driver.full_name}: {sms_error}")
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

class RefuelingRequestActionView(SignatureVerificationMixin,OTPVerificationMixin,APIView):
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
        # error_response = self.verify_signature(request)
        # if error_response:
        #     return error_response
        # otp_code = request.data.get("otp_code")
        # if not otp_code:
        #     return Response({"error": "OTP code is required."}, status=status.HTTP_400_BAD_REQUEST)
        # otp_error = self.verify_otp(request.user, otp_code, request)
        # if otp_error:
        #     return otp_error
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
            #     if approver.phone_number:
            #         sms_message = (
            #             f"Refueling request for vehicle with license plate: {refueling_request.requesters_car.license_plate} "
            #             f"has been forwarded for your approval."
            #         )
            #         try:
            #             send_sms(approver.phone_number, sms_message)
            #         except Exception as e:
            #             logger.error(f"Failed to send SMS to {approver.full_name}: {e}")

            refueling_request.save()
            # log_action(request_obj=refueling_request,user=request.user,action="forwarded",remarks=request.data.get('remarks'))


        # ====== REJECT ACTION ======
        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=status.HTTP_400_BAD_REQUEST)

            refueling_request.status = 'rejected'
            refueling_request.rejection_message = rejection_message
            refueling_request.save()
            log_action(request_obj=refueling_request,user=request.user,action="rejected",remarks=rejection_message)

            # # # Notify requester of rejection
            NotificationService.send_refueling_notification(
                'refueling_rejected', refueling_request, refueling_request.requester,
                rejector=request.user.full_name, rejection_reason=rejection_message
                )
            if refueling_request.requester.phone_number:
                sms_message = (
                    f"Your refueling request for {refueling_request.requesters_car.license_plate} "
                    f"was rejected by {request.user.full_name}. Reason: {rejection_message}"
                )
                try:
                    send_sms(refueling_request.requester.phone_number, sms_message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {refueling_request.requester.full_name}: {e}")
        # ====== APPROVE ACTION ======
        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER and refueling_request.current_approver_role == User.BUDGET_MANAGER:
                # Final approval by Transport Manager after Finance Manager has approved
                refueling_request.status = 'approved'
                refueling_request.save()
                log_action(request_obj=refueling_request,user=request.user,action="approved",remarks=request.data.get("remarks"))
                
                finance_manger= User.objects.filter(role=User.FINANCE_MANAGER).first()
                # # # Notify the original requester of approval
                NotificationService.send_refueling_notification(
                    'refueling_approved', refueling_request, refueling_request.requester,
                    approver=request.user.full_name
                )
                NotificationService.send_refueling_notification(
                   'refueling_approved',refueling_request, finance_manger,approver=request.user.full_name
                )
                for user in [refueling_request.requester, finance_manger]:
                    if user and user.phone_number:
                        sms_message = (
                            f"Refueling request for vehicle with license plate: {refueling_request.requesters_car.license_plate} "
                            f"has been approved by {request.user.full_name}."
                        )
                        try:
                            send_sms(user.phone_number, sms_message)
                        except Exception as e:
                            logger.error(f"Failed to send SMS to {user.full_name}: {e}")
            else:
                return Response({"error": f"{request.user.get_role_display()} cannot approve this request at this stage."}, 
                                status=status.HTTP_403_FORBIDDEN)
        else:
            return Response({"error": "Unexpected error occurred."}, status=status.HTTP_400_BAD_REQUEST)
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

class MaintenanceRequestActionView(SignatureVerificationMixin,OTPVerificationMixin,APIView):
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
        # error_response = self.verify_signature(request)
        # if error_response:
        #     return error_response
        # otp_code = request.data.get("otp_code")
        # if not otp_code:
        #     return Response({"error": "OTP code is required."}, status=status.HTTP_400_BAD_REQUEST)
        # otp_error = self.verify_otp(request.user, otp_code, request)
        # if otp_error:
        #     return otp_error
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
            if current_role == User.TRANSPORT_MANAGER:
                maintenance_request.requesters_car.mark_as_maintenance()
            next_role = self.get_next_approver_role(current_role)
            if not next_role:
                return Response({"error": "No further approver available."}, status=status.HTTP_400_BAD_REQUEST)

            maintenance_request.status = 'forwarded'
            maintenance_request.current_approver_role = next_role
            maintenance_request.save()
            # log_action(request_obj=maintenance_request,user=request.user,action="forwarded",remarks=request.data.get("remarks"))

            # Notify next approver(s)
            next_approvers = User.objects.filter(role=next_role, is_active=True)
            for approver in next_approvers:
                NotificationService.send_maintenance_notification(
                    'maintenance_forwarded', maintenance_request, approver
                )
                if approver.phone_number:
                    sms_message = (
                        f"Maintenance request for vehicle with license plate: {maintenance_request.requesters_car.license_plate} "
                        f"has been forwarded for your approval."
                    )
                    try:
                        send_sms(approver.phone_number, sms_message)
                    except Exception as e:
                        logger.error(f"Failed to send SMS to {approver.full_name}: {e}")
            return Response({"message": "Request forwarded successfully."}, status=status.HTTP_200_OK)

        # ===== REJECT LOGIC =====
        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=status.HTTP_400_BAD_REQUEST)

            maintenance_request.status = 'rejected'
            maintenance_request.rejection_message = rejection_message
            maintenance_request.save()
            log_action(request_obj=maintenance_request,user=request.user,action="rejected",remarks=maintenance_request.rejection_message)

            NotificationService.send_maintenance_notification(
                'maintenance_rejected', maintenance_request, maintenance_request.requester,
                rejector=request.user.full_name, rejection_reason=rejection_message
            )
            if maintenance_request.requester.phone_number:
                sms_message = (
                    f"Your maintenance request for vehicle {maintenance_request.requesters_car.license_plate} "
                    f"was rejected by {request.user.full_name}. Reason: {rejection_message}"
                )
                try:
                    send_sms(maintenance_request.requester.phone_number, sms_message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {maintenance_request.requester.full_name}: {e}")
            return Response({"message": "Request rejected successfully."}, status=status.HTTP_200_OK)

        # ===== APPROVE LOGIC =====
        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER:
                # Final approval
                maintenance_request.status = 'approved'
                # maintenance_request.requesters_car.mark_as_maintenance() 
                maintenance_request.save()
                log_action(request_obj=maintenance_request,user=request.user,action="approved",remarks=request.data.get("remarks"))
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
                recipients = [maintenance_request.requester] + list(finance_managers)
                for user in recipients:
                    if user and user.phone_number:
                        sms_message = (
                            f"Maintenance request for vehicle with license plate: {maintenance_request.requesters_car.license_plate} "
                            f"has been approved by {request.user.full_name}."
                        )
                        try:
                            send_sms(user.phone_number, sms_message)
                        except Exception as e:
                            logger.error(f"Failed to send SMS to {user.full_name}: {e}")

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


class TransportRequestActionView(SignatureVerificationMixin,OTPVerificationMixin,APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_next_approver_role(self, current_role):
        """Determine the next approver based on hierarchy."""
        role_hierarchy = {
            User.DEPARTMENT_MANAGER: User.TRANSPORT_MANAGER,
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
                if approver.phone_number:
                    sms_message = (
                        f"Transport request by requester {transport_request.requester.full_name} to {transport_request.destination} has been forwarded for your approval."
                    )
                    try:
                        send_sms(approver.phone_number, sms_message)
                    except Exception as e:
                        logger.error(f"Failed to send SMS to {approver.full_name}: {e}")

            # log_action(request_obj=transport_request,user=request.user,action="forwarded",remarks=request.data.get("remarks"))

        elif action == 'reject':
            transport_request.status = 'rejected'
            transport_request.rejection_message = request.data.get("rejection_message", "")

            # Notify requester of rejection
            NotificationService.create_notification(
                'rejected', transport_request, transport_request.requester, rejector=request.user.full_name
            )
            if transport_request.requester.phone_number:
                sms_message = (
                    f"Your transport request by requester {transport_request.requester.full_name} to {transport_request.destination} was rejected by {request.user.full_name}."
                )
                try:
                    send_sms(transport_request.requester.phone_number, sms_message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {transport_request.requester.full_name}: {e}")
            log_action(request_obj=transport_request,user=request.user,action="rejected",remarks=transport_request.rejection_message)

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
            log_action(request_obj=transport_request,user=request.user,action="approved",remarks=f"Vehicle: {vehicle.license_plate}")
            try:
                # Get employee full names
                employee_names = list(
                    transport_request.employees.exclude(id=transport_request.requester_id)
                    .values_list('full_name', flat=True)
                )
                group_info = " With Employees: " + ", ".join(employee_names) + "." if employee_names else ""

                # Message for driver
                driver_message = (
                    f"You are assigned for a transport request to {transport_request.destination} on "
                    f"{transport_request.start_day.strftime('%Y-%m-%d')} at {transport_request.start_time.strftime('%H:%M')} "
                    f"with vehicle {vehicle.model} ({vehicle.license_plate}).{group_info}"
                )
                send_sms(vehicle.driver.phone_number, driver_message)

                # Message for requester
                requester_message = (
                    f"Your transport request to {transport_request.destination} has been approved by {request.user.full_name}. "
                    f"You can now communicate with the assigned driver: {vehicle.driver.full_name}, Phone: {vehicle.driver.phone_number}."
                )
                if transport_request.requester.phone_number:
                    send_sms(transport_request.requester.phone_number, requester_message)
            except Exception as sms_error:
                logger.error(f"Failed to send SMS: {sms_error}")
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
            if transport_manager.phone_number:
                sms_message = (
                    f"Trip to {trip_request.destination} with vehicle {trip_request.vehicle.model} ({trip_request.vehicle.license_plate}) "
                    f"has been completed by {request.user.full_name}."
                )
                try:
                    send_sms(transport_manager.phone_number, sms_message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {transport_manager.full_name}: {e}")
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

        if vehicle.driver != self.request.user:
            raise PermissionDenied("You are not authorized to add kilometers for this vehicle.")    

        kilometers = serializer.validated_data['kilometers_driven']
        now = timezone.now()
        month = now.strftime('%Y-%m')
        month_display = now.strftime('%B %Y')
        # Validation: Prevent duplicate entry for the same vehicle and month
        if MonthlyKilometerLog.objects.filter(vehicle=vehicle, month=month).exists():
            raise serializers.ValidationError(
                f"Kilometers for {month_display} already recorded for this vehicle."
            )
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

        transport_managers = User.objects.filter(role=User.TRANSPORT_MANAGER, is_active=True)
        general_systems = User.objects.filter(role=User.GENERAL_SYSTEM, is_active=True)
        driver = vehicle.driver  # or vehicle.assigned_driver depending on your model

        if not driver:
            raise ValueError("Vehicle has no assigned driver.")

        recipients = list(transport_managers) + list(general_systems) + [driver]
        # Check service threshold
        if (vehicle.total_kilometers - vehicle.last_service_kilometers) >= 5000:
            NotificationService.send_service_notification(
                vehicle=vehicle,
                recipients=recipients
            )

class CouponRequestCreateView(generics.CreateAPIView):
    serializer_class = CouponRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

class CouponRequestListView(generics.ListAPIView):
    serializer_class = CouponRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == User.TRANSPORT_MANAGER:
            # Transport manager sees all, newest first
            return CouponRequest.objects.all().order_by('-created_at')
        else:
            # Requester sees only their own
            return CouponRequest.objects.filter(requester=user).order_by('-created_at')
    
class MyMonthlyKilometerLogsListView(generics.ListAPIView):
    serializer_class = MonthlyKilometerLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return MonthlyKilometerLog.objects.filter(
            recorded_by=self.request.user
        ).order_by('-created_at')

class UserActionLogDetailView(generics.RetrieveAPIView):
    serializer_class = ActionLogListSerializer  # You can use the same serializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ActionLog.objects.filter(action_by=self.request.user)


class UserActionLogListView(generics.ListAPIView):
    serializer_class = ActionLogListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ActionLog.objects.filter(action_by=self.request.user).order_by('-timestamp')

class ReportAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTransportManager]

    def get(self, request):
        request_type_filter = request.query_params.get("request_type")
        month_filter = request.query_params.get("month")  # format: YYYY-MM    

        # Parse the month filter
        month_start = None
        month_end = None
        if month_filter:
            try:
                month_start = datetime.strptime(month_filter, "%Y-%m")
                # Handle end of month by next month - 1 day
                if month_start.month == 12:
                    month_end = datetime(month_start.year + 1, 1, 1)
                else:
                    month_end = datetime(month_start.year, month_start.month + 1, 1)
            except ValueError:
                return Response({"error": "Invalid month format. Use YYYY-MM."}, status=400)

        vehicles = Vehicle.objects.all()
        vehicle_reports = []

        for vehicle in vehicles:
            vehicle_data = {
                "vehicle": f"{vehicle.model} {vehicle.license_plate}",
                "requests": [],
                "request_counts": {
                    "Transport": 0,
                    "HighCost": 0,
                    "Maintenance": 0,
                    "Refueling": 0,
                },
                "total_cost": 0.0,
            }

            def apply_filters(qs, model_name):
                if month_start and hasattr(qs.model, "created_at"):
                    qs = qs.filter(created_at__gte=month_start, created_at__lt=month_end)
                if request_type_filter and request_type_filter != model_name:
                    return qs.none()
                return qs

            # Apply filters
            transport_requests = apply_filters(
                TransportRequest.objects.filter(vehicle=vehicle), "Transport"
            )
            highcost_requests = apply_filters(
                HighCostTransportRequest.objects.filter(vehicle=vehicle), "HighCost"
            )
            maintenance_requests = apply_filters(
                MaintenanceRequest.objects.filter(requesters_car=vehicle), "Maintenance"
            )
            refueling_requests = apply_filters(
                RefuelingRequest.objects.filter(requesters_car=vehicle), "Refueling"
            )

            # Count requests
            vehicle_data["request_counts"]["Transport"] = transport_requests.count()
            vehicle_data["request_counts"]["HighCost"] = highcost_requests.count()
            vehicle_data["request_counts"]["Maintenance"] = maintenance_requests.count()
            vehicle_data["request_counts"]["Refueling"] = refueling_requests.count()

            # Append requests with count info
            for req in transport_requests:
                vehicle_data["requests"].append({
                    "plate": vehicle.license_plate,
                    "driver": req.vehicle.driver.full_name if req.vehicle.driver else None,
                    "kilometers": getattr(req, "estimated_distance", None),
                    "fuel_liters": None,
                    "cost": None,
                    "request_type": "Transport",
                    "request_type_count": transport_requests.count(),
                })

            for req in highcost_requests:
                cost = float(req.total_cost or 0)
                vehicle_data["requests"].append({
                    "plate": vehicle.license_plate,
                    "driver": req.vehicle.driver.full_name if req.vehicle.driver else None,
                    "kilometers": req.estimated_distance_km,
                    "fuel_liters": req.fuel_needed_liters,
                    "cost": req.total_cost,
                    "request_type": "HighCost",
                    "request_type_count": highcost_requests.count(),
                })
                vehicle_data["total_cost"] += cost

            for req in maintenance_requests:
                cost = float(req.maintenance_total_cost or 0)
                vehicle_data["requests"].append({
                    "plate": vehicle.license_plate,
                    "driver": req.requesters_car.driver.full_name if req.requesters_car.driver else None,
                    "kilometers": None,
                    "fuel_liters": None,
                    "cost": req.maintenance_total_cost,
                    "request_type": "Maintenance",
                    "request_type_count": maintenance_requests.count(),
                })
                vehicle_data["total_cost"] += cost

            for req in refueling_requests:
                cost = float(req.total_cost or 0)
                vehicle_data["requests"].append({
                    "plate": vehicle.license_plate,
                    "driver": req.requesters_car.driver.full_name if req.requesters_car.driver else None,
                    "kilometers": req.estimated_distance_km,
                    "fuel_liters": req.fuel_needed_liters,
                    "cost": req.total_cost,
                    "request_type": "Refueling",
                    "request_type_count": refueling_requests.count(),
                })
                vehicle_data["total_cost"] += cost

            vehicle_reports.append(vehicle_data)

        paginator = PageNumberPagination()
        paginated = paginator.paginate_queryset(vehicle_reports, request)
        return paginator.get_paginated_response({"vehicles": paginated})

class VehiclesDueForServiceView(generics.ListAPIView):
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != User.TRANSPORT_MANAGER:
            raise PermissionDenied("Only transport managers can view this list.")
        return Vehicle.objects.filter(
            total_kilometers__gte=F('last_service_kilometers') + 5000
        )

class ServiceRequestListView(generics.ListAPIView):
    queryset = ServiceRequest.objects.all()
    serializer_class = ServiceRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == user.GENERAL_SYSTEM:
            return ServiceRequest.objects.filter(status='pending', current_approver_role=User.GENERAL_SYSTEM)
        elif user.role == user.CEO:
            return ServiceRequest.objects.filter(status='forwarded',current_approver_role=User.CEO)
        elif user.role == user.BUDGET_MANAGER:
            return ServiceRequest.objects.filter(status='forwarded', current_approver_role=User.BUDGET_MANAGER)
        elif user.role == user.FINANCE_MANAGER:

            return ServiceRequest.objects.filter(status='approved')
        return ServiceRequest.objects.none()

class ServiceRequestActionView(SignatureVerificationMixin,OTPVerificationMixin,APIView):
    permission_classes = [permissions.IsAuthenticated]
   
    def get_next_approver_role(self, current_role):
        role_hierarchy = {
            User.GENERAL_SYSTEM: User.CEO,
            User.CEO: User.BUDGET_MANAGER,
        }
        return role_hierarchy.get(current_role, None)

    def post(self, request, request_id):
        service_request = get_object_or_404(ServiceRequest, id=request_id)
        action = request.data.get("action")

        if action not in ['forward', 'reject', 'approve']:
            return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

        
        current_role = request.user.role

        if current_role != service_request.current_approver_role:
            return Response({"error": "You are not authorized to act on this request."}, status=status.HTTP_403_FORBIDDEN)
        # error_response = self.verify_signature(request)
        # if error_response:
        #     return error_response
        # otp_code = request.data.get("otp_code")
        # if not otp_code:
        #     return Response({"error": "OTP code is required."}, status=status.HTTP_400_BAD_REQUEST)
        # otp_error = self.verify_otp(request.user, otp_code, request)
        # if otp_error:
        #     return otp_error
        if action == 'forward':
            if current_role == User.GENERAL_SYSTEM:
                missing = []
                if not service_request.service_letter:
                    missing.append('service_letter')
                if not service_request.receipt_file:
                    missing.append('receipt_file')
                if service_request.service_total_cost is None:
                    missing.append('service_total_cost')

                if missing:
                    return Response(
                        {"error": f"The following files must be submitted before forwarding: {', '.join(missing)}"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            next_role = self.get_next_approver_role(current_role)
            if not next_role:
                return Response({"error": "No further approver available."}, status=status.HTTP_400_BAD_REQUEST)

            service_request.status = 'forwarded'
            service_request.current_approver_role = next_role
            service_request.save()
            # log_action(request_obj=service_request, user=request.user, action="forwarded", remarks=request.data.get("remarks"))
            next_approvers = User.objects.filter(role=next_role, is_active=True)
            for approver in next_approvers:
                # NotificationService.send_service_notification('service_forwarded', service_request, approver)
                if approver.phone_number:
                    sms_message = (
                        f"Service request for vehicle with license plate: {service_request.vehicle.license_plate} "
                        f"has been forwarded for your approval."
                    )
                    try:
                        send_sms(approver.phone_number, sms_message)
                    except Exception as e:
                        logger.error(f"Failed to send SMS to {approver.full_name}: {e}")
            # next_approvers = User.objects.filter(role=next_role, is_active=True)
            # for approver in next_approvers:
            #     NotificationService.send_service_notification('service_forwarded', service_request, approver)

            return Response({"message": "Request forwarded successfully."}, status=status.HTTP_200_OK)

        elif action == 'reject':
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response({"error": "Rejection message is required."}, status=status.HTTP_400_BAD_REQUEST)

            service_request.status = 'rejected'
            service_request.rejection_reason = rejection_message
            service_request.save()
            log_action(request_obj=service_request, user=request.user, action="rejected", remarks=rejection_message)
            driver = service_request.vehicle.driver
            if driver and driver.phone_number:
                sms_message = (
                    f"Service request for vehicle with license plate: {service_request.vehicle.license_plate} "
                    f"has been rejected by {request.user.full_name}. Reason: {rejection_message}"
                )
                try:
                    send_sms(driver.phone_number, sms_message)
                except Exception as e:
                    logger.error(f"Failed to send SMS to {driver.full_name}: {e}")
            # NotificationService.send_service_notification(
            #     'service_rejected', service_request, service_request.created_by,
            #     rejector=request.user.get_full_name(), rejection_reason=rejection_message
            # )

            return Response({"message": "Request rejected successfully."}, status=status.HTTP_200_OK)

        elif action == 'approve':
            if current_role == User.BUDGET_MANAGER:
                service_request.status = 'approved'
                service_request.save()
                log_action(request_obj=service_request, user=request.user, action="approved", remarks=request.data.get("remarks"))
                finance_managers = User.objects.filter(role=User.FINANCE_MANAGER, is_active=True)
                driver = service_request.vehicle.driver
                recipients = [driver] + list(finance_managers)
                for user in recipients:
                    if user and user.phone_number:
                        sms_message = (
                            f"Service request for vehicle with license plate: {service_request.vehicle.license_plate} "
                            f"has been approved by {request.user.full_name}."
                        )
                        try:
                            send_sms(user.phone_number, sms_message)
                        except Exception as e:
                            logger.error(f"Failed to send SMS to {user.full_name}: {e}")
                # NotificationService.send_service_notification(
                #     'service_approved', service_request, service_request.created_by,
                #     approver=request.user.get_full_name()
                # )

                # for fm in finance_managers:
                #     NotificationService.send_service_notification('service_approved', service_request, recipient=fm)

                return Response({"message": "Request approved successfully and finance notified."}, status=status.HTTP_200_OK)

            else:
                return Response({
                    "error": f"{request.user.get_role_display()} cannot approve this request at this stage."
                }, status=status.HTTP_403_FORBIDDEN)

        return Response({"error": "Unexpected action or failure."}, status=status.HTTP_400_BAD_REQUEST)
    
class ServiceFileSubmissionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def patch(self, request, request_id):
        service_request = get_object_or_404(ServiceRequest, id=request_id)

        if request.user.role != User.GENERAL_SYSTEM:
            return Response({"error": "Only General System can perform this action."}, status=status.HTTP_403_FORBIDDEN)

        # Handle file uploads
        service_letter = request.FILES.get("service_letter")
        receipt_file = request.FILES.get("receipt_file")
        total_cost = request.data.get("service_total_cost")

        if not service_letter or not receipt_file or not total_cost:
            return Response({"error": "All fields are required."}, status=status.HTTP_400_BAD_REQUEST)

        service_request.service_letter = service_letter
        service_request.receipt_file = receipt_file
        service_request.service_total_cost = total_cost
        service_request.save()

        return Response({"message": "Files submitted successfully."}, status=status.HTTP_200_OK)

class TransportManagerServiceUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, vehicle_id):
        if request.user.role != User.TRANSPORT_MANAGER:
            raise PermissionDenied("Only transport managers can perform this action.")

        vehicle = get_object_or_404(Vehicle, id=vehicle_id)
        
        if (vehicle.total_kilometers - vehicle.last_service_kilometers) < 5000:
            return Response({'detail': 'Vehicle does not meet the 5000 km threshold.'}, status=400)

        # Update service-related info
        vehicle.last_service_kilometers = vehicle.total_kilometers
        vehicle.mark_as_service()

        # Auto-create service request
        ServiceRequest.objects.create(
            vehicle=vehicle,
            current_approver_role=User.GENERAL_SYSTEM
        )

        return Response({'detail': 'Vehicle marked as service and request created.'}, status=200)

class ServicedVehiclesListView(generics.ListAPIView):
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != User.TRANSPORT_MANAGER:
            raise PermissionDenied("Only transport managers can access this list.")

        # Subquery to get the status of the latest service request for each vehicle
        latest_request_status = ServiceRequest.objects.filter(
            vehicle=OuterRef('pk')
        ).order_by('-created_at').values('status')[:1]

        # Only include vehicles whose latest service request is approved or rejected
        # AND whose current status is 'service'
        return Vehicle.objects.annotate(
            latest_status=Subquery(latest_request_status)
        ).filter(
            latest_status__in=['approved', 'rejected'],
            status=Vehicle.SERVICE  # Make sure this matches your model's constant
        )

class MarkServicedVehicleAvailableView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, vehicle_id):
        if request.user.role != User.TRANSPORT_MANAGER:
            raise PermissionDenied("Only transport managers can perform this action.")

        vehicle = get_object_or_404(Vehicle, id=vehicle_id)

        try:
            latest_service_request = ServiceRequest.objects.filter(vehicle=vehicle).latest('created_at')
        except ServiceRequest.DoesNotExist:
            return Response({'error': 'No service request found for this vehicle.'}, status=status.HTTP_404_NOT_FOUND)

        if latest_service_request.status not in ['approved', 'rejected']:
            return Response({
                'error': 'Vehicle cannot be marked as available until the service request is approved or rejected.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if vehicle.status == 'available':
            return Response({'detail': 'Vehicle is already marked as available.'}, status=status.HTTP_200_OK)

        vehicle.status = 'available'
        vehicle.save()

        # Optionally log this or trigger notification here

        return Response({'detail': 'Vehicle status updated to available.'}, status=status.HTTP_200_OK)

class ServiceRequestDetailView(RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ServiceRequestDetailSerializer
    queryset = ServiceRequest.objects.all()

    def get(self, request, *args, **kwargs):
        service_request = self.get_object()

        if request.user.role not in [
            User.TRANSPORT_MANAGER,
            User.GENERAL_SYSTEM,
            User.CEO,
            User.BUDGET_MANAGER,
            User.FINANCE_MANAGER,
            User.DRIVER,
        ]:
            return Response({"error": "Access denied."}, status=403)

        serializer = self.get_serializer(service_request)
        return Response(serializer.data)
    
class RequestOTPView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.phone_number:
            return Response({"error": "User does not have a phone number."}, status=400)
        try:
            OTPManager.generate_otp(user)
        except PermissionError as e:
            return Response({"error": str(e)}, status=429)
        return Response({"message": "OTP sent to your phone."}, status=200)
    
class VehiclesAfterMaintenanceListView(generics.ListAPIView):
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.role != User.TRANSPORT_MANAGER:
            raise PermissionDenied("Only transport managers can view this list.")

        # Subquery: Does an approved maintenance request exist for this vehicle?
        approved_maintenance_exists = MaintenanceRequest.objects.filter(
            requesters_car=OuterRef('pk'),
            status='approved'
        )

        return Vehicle.objects.annotate(
            has_approved_maintenance=Exists(approved_maintenance_exists)
        ).filter(
            has_approved_maintenance=True,
            status=Vehicle.MAINTENANCE
        )

class MarkMaintenancedVehicleAvailableView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, vehicle_id):
        if request.user.role != User.TRANSPORT_MANAGER:
            raise PermissionDenied("Only transport managers can perform this action.")

        vehicle = get_object_or_404(Vehicle, id=vehicle_id)

        # Check if there is any approved maintenance request for this vehicle
        has_approved_maintenance = MaintenanceRequest.objects.filter(
            requesters_car=vehicle,
            status='approved'
        ).exists()

        if not has_approved_maintenance:
            return Response({
                'error': 'Vehicle cannot be marked as available until at least one maintenance request is approved.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if vehicle.status == Vehicle.AVAILABLE:
            return Response({'detail': 'Vehicle is already marked as available.'}, status=status.HTTP_200_OK)

        vehicle.status = Vehicle.AVAILABLE
        vehicle.save()

        # Optionally log this or trigger notification here

        return Response({'detail': 'Vehicle status updated to available.'}, status=status.HTTP_200_OK)