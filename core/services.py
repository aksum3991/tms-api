import os
import tempfile
from datetime import timedelta

import cv2
import numpy as np
import requests
import urllib
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.translation import gettext as _
from skimage.metrics import structural_similarity as ssim

from auth_app.models import User
from .models import ActionLog, HighCostTransportRequest, RefuelingRequest, Vehicle
from core.models import MaintenanceRequest, TransportRequest, Notification

import logging
logger = logging.getLogger(__name__)


class NotificationService:
    NOTIFICATION_TEMPLATES = {
        'new_request': {
            'title': _("New Transport Request"),
            'message': _("{requester} has submitted a new transport request to {destination} on {date}"),
            'priority': 'normal'
        },
        'forwarded': {
            'title': _("Transport Request Forwarded"),
            'message': _("Transport request #{request_id} has been forwarded for your approval"),
            'priority': 'normal'
        },
        'approved': {
            'title': _("Transport Request Approved"),
            'message': _("Your transport request #{request_id} has been approved by {approver}. "
                         "Vehicle: {vehicle} | Driver: {driver}. "
                         "Destination: {destination}, Date: {date}, Start Time: {start_time}."),
            'priority': 'normal'
        },
        'rejected': {
            'title': _("Transport Request Rejected"),
            'message': _("Your transport request #{request_id} to {destination} on {date} at {start_time} "
                 "has been rejected by {rejector}.Rejection Reason: {rejection_reason}. "
                 "Passengers: {passengers}."),
            'priority': 'high'
        },
        'assigned': {
            'title': _("Vehicle Assigned"),
            'message':  _("You have been assigned to drive vehicle {vehicle} for transport request #{request_id}. "
                 "Destination: {destination}, Date: {date}, Start Time: {start_time}. "
                 "Passengers: {passengers}. Please be prepared."),
            'priority': 'normal'
        },
        'new_maintenance': {
            'title': _("New Maintenance Request"),
            'message': _("{requester} has submitted a new maintenance request."),
            'priority': 'normal'
        },
        'maintenance_forwarded': {
            'title': _("Maintenance Request Forwarded"),
            'message': _("Maintenance request #{request_id} has been forwarded for your approval."),
            'priority': 'normal'
        },
        'maintenance_approved': {
            'title': _("Maintenance Request Approved"),
            'message': _("Your maintenance request #{request_id} has been approved by {approver}."),
            'priority': 'normal'
        },
        'maintenance_rejected': {
            'title': _("Maintenance Request Rejected"),
            'message': _("Your maintenance request #{request_id} has been rejected by {rejector}. "
                         "Rejection Reason: {rejection_reason}."),
            'priority': 'high'
        },
           'new_refueling': {
            'title': _("New Refueling Request"),
            'message': _("{requester} has submitted a new Refueling request."),
            'priority': 'normal'
        },

        'refueling_forwarded': {
            'title': _("Refueling Request Forwarded"),
            'message': _("Refueling request #{request_id} has been forwarded for your approval."),
            'priority': 'normal'
        },
        'refueling_rejected': {
            'title': _("Refueling Request Rejected"),
            'message': _("Your refueling request #{request_id} has been rejected by {rejector}. "
                        "Rejection Reason: {rejection_reason}."),
            'priority': 'high'
        },
        'refueling_approved': {
            'title': _("Refueling Request Approved"),
            'message': _("Your refueling request #{request_id} has been approved by {approver}."),
            'priority': 'normal'
        },

        'new_highcost': {
        'title': _("New High-Cost Transport Request"),
        'message': _("{requester} has submitted a high-cost transport request to {destination} on {date}."),
        'priority': 'normal'
        },
        'highcost_forwarded': {
            'title': _("High-Cost Transport Request Forwarded"),
            'message': _("High-cost transport request #{request_id} has been forwarded for your approval."),
            'priority': 'normal'
        },
        'highcost_rejected': {
            'title': _("High-Cost Transport Request Rejected"),
            'message': _("Your high-cost transport request #{request_id} to {destination} on {date} at {start_time} "
                        "has been rejected by {rejector}. Rejection Reason: {rejection_reason}. "
                        "Passengers: {passengers}."),
            'priority': 'high'
        },
        'highcost_approved': {
            'title': _("High-Cost Transport Request Approved"),
            'message': _("Your high-cost transport request #{request_id} has been approved by {approver}."),
            'priority': 'normal'
        },
        'highcost_vehicle_assigned': {
            'title': _("Vehicle Assigned to Your Request"),
            'message': _("A vehicle has been assigned to your high-cost transport request #{request_id}. "
                        "Vehicle: {vehicle}. Driver: {driver} (Phone: {driver_phone}). "
                        "Destination: {destination}, Date: {date}, Start Time: {start_time}."),
            'priority': 'normal'
        },
        'service_due': {
            'title': _("Service Due Notification"),
            'message': _("Vehicle {vehicle_model} (Plate: {license_plate}) has reached {kilometer} km. "
                        "It now requires servicing. Please schedule maintenance as soon as possible."),
            'priority': 'high'
        },  
       'trip_completed': {
            'title': "Trip Completed",
            'message': "{completer} has completed the trip to {destination}. Vehicle: {vehicle}.",
            'priority': 'normal',
    },

    }

    @classmethod
    def create_notification(cls, notification_type: str, transport_request: TransportRequest, 
                          recipient: User, **kwargs) -> Notification:
        """
        Create a new notification
        """
        template = cls.NOTIFICATION_TEMPLATES.get(notification_type)
        if not template:
            raise ValueError(f"Invalid notification type: {notification_type}")
        passengers = list(transport_request.employees.all())
        passengers_str = ", ".join([p.full_name for p in passengers]) if passengers else "No additional passengers"       
        message_kwargs = {
        'request_id': transport_request.id,
        'requester': transport_request.requester.full_name,
        'destination': transport_request.destination,
        'date': transport_request.start_day.strftime('%Y-%m-%d'),
        'start_time': transport_request.start_time.strftime('%H:%M'),
        'rejector': kwargs.get('rejector', 'Unknown'),
        'rejection_reason': transport_request.rejection_message,
        'passengers': passengers_str,
        **kwargs
        }
       
        notification = Notification.objects.create(
            recipient=recipient,
            transport_request=transport_request,
            notification_type=notification_type,
            title=template['title'],
            message=template['message'].format(**message_kwargs),
            priority=template['priority'],
            action_required=notification_type not in ['approved', 'rejected'],
            metadata={
                'request_id': transport_request.id,
                'requester_id': transport_request.requester.id,
                'destination': transport_request.destination,
                'date': transport_request.start_day.strftime('%Y-%m-%d'),
                'rejection_reason': transport_request.rejection_message,
                'passengers': passengers_str,
                **kwargs
            }
        )
        return notification
    
    @classmethod
    def send_maintenance_notification(cls, notification_type: str, maintenance_request: MaintenanceRequest, recipient: User, **kwargs):
        """
        Send a notification specifically for maintenance requests without affecting transport request logic.
        """
        template = cls.NOTIFICATION_TEMPLATES.get(notification_type)
        if not template:
            raise ValueError(f"Invalid notification type: {notification_type}")

        request_data = {
            'request_id': maintenance_request.id,
            'requester': maintenance_request.requester.full_name,
            'requesters_car_model':maintenance_request.requesters_car.model,
            'requesters_car_license_plate':maintenance_request.requesters_car.license_plate,
            'rejector': kwargs.get('rejector', 'Unknown'),
            'approver': kwargs.get('approver', 'Unknown'),
            'rejection_reason': maintenance_request.rejection_message or "No reason provided.",
            **kwargs
        }

        notification = Notification.objects.create(
            recipient=recipient,
            maintenance_request=maintenance_request,
            notification_type=notification_type,
            title=template['title'],
            message=template['message'].format(**request_data),
            priority=template['priority'],
            action_required=notification_type not in ['maintenance_approved', 'maintenance_rejected'],
            metadata=request_data
        )

        return notification
    
    @classmethod
    def send_refueling_notification(cls, notification_type: str, refueling_request: RefuelingRequest, recipient: User, **kwargs):
        """
        Send a notification specifically for refueling requests.
        """
        template = cls.NOTIFICATION_TEMPLATES.get(notification_type)
        if not template:
            raise ValueError(f"Invalid notification type: {notification_type}")

        request_data = {
            'request_id': refueling_request.id,
            'requester': refueling_request.requester.full_name,
            'rejector': kwargs.get('rejector', 'Unknown'),
            'approver': kwargs.get('approver', 'Unknown'),
            'rejection_reason': refueling_request.rejection_message or "No reason provided.",
            **kwargs
        }

        notification = Notification.objects.create(
            recipient=recipient,
            refueling_request=refueling_request,
            notification_type=notification_type,
            title=template['title'],
            message=template['message'].format(**request_data),
            priority=template['priority'],
            action_required=notification_type not in ['refueling_approved', 'refueling_rejected'],
            metadata=request_data
        )
        return notification

    @classmethod
    def send_highcost_notification(cls, notification_type: str, highcost_request: HighCostTransportRequest, recipient: User, **kwargs):
            """
            Send a notification specifically for high-cost transport requests.
            """
            template = cls.NOTIFICATION_TEMPLATES.get(notification_type)
            if not template:
                raise ValueError(f"Invalid notification type: {notification_type}")

            passengers = list(highcost_request.employees.all())
            passengers_str = ", ".join([p.full_name for p in passengers]) if passengers else "No additional passengers"

            request_data = {
                'request_id': highcost_request.id,
                'requester': highcost_request.requester.full_name,
                'destination': highcost_request.destination,
                'date': highcost_request.start_day.strftime('%Y-%m-%d'),
                'start_time': highcost_request.start_time.strftime('%H:%M'),
                'rejector': kwargs.get('rejector', 'Unknown'),
                'rejection_reason': highcost_request.rejection_message or "No reason provided.",
                'approver': kwargs.get('approver', 'Unknown'),
                'passengers': passengers_str,
                **kwargs
            }

            notification = Notification.objects.create(
                recipient=recipient,
                highcost_request=highcost_request,
                notification_type=notification_type,
                title=template['title'],
                message=template['message'].format(**request_data),
                priority=template['priority'],
                action_required=notification_type not in ['highcost_approved', 'highcost_rejected'],
                metadata=request_data
            )
            return notification
    @classmethod
    def send_service_notification(cls, vehicle: Vehicle, recipients: list[User], notification_type: str = 'service_due'):
        """
        Send service due notifications to a list of recipients (e.g., driver, transport manager, general system user).

        Args:
            vehicle (Vehicle): The vehicle that requires service.
            recipients (list[User]): List of users to notify.
            notification_type (str): Type of the notification. Defaults to 'service_due'.

        Raises:
            ValueError: If the notification template for the given type is missing.
        """
        template = cls.NOTIFICATION_TEMPLATES.get(notification_type)
        if not template:
            # Log this properly in real applications
            raise ValueError(f"Missing '{notification_type}' template in NOTIFICATION_TEMPLATES.")

        request_data = {
            'vehicle_model': vehicle.model,
            'license_plate': vehicle.license_plate,
            'kilometer': vehicle.total_kilometers
        }

        notifications = [
            Notification(
                recipient=recipient,
                vehicle=vehicle,
                notification_type=notification_type,
                title=template['title'],
                message=template['message'].format(**request_data),
                priority=template['priority'],
                action_required=True,
                metadata=request_data
            ) for recipient in recipients
        ]

        Notification.objects.bulk_create(notifications)

    @classmethod
    def send_trip_completion_notification(cls, transport_request, recipient: User, completer: str):
        """
        Send a trip completion notification (supports both TransportRequest and HighCostTransportRequest).
        """
        template = cls.NOTIFICATION_TEMPLATES.get('trip_completed')
        if not template:
            raise ValueError("Notification template for 'trip_completed' not found.")

        request_data = {
            'request_id': transport_request.id,
            'completer': completer,
            'destination': transport_request.destination,
            'vehicle': transport_request.vehicle.license_plate if transport_request.vehicle else "N/A"
        }

        notification_kwargs = {
            'recipient': recipient,
            'notification_type': 'trip_completed',
            'title': template['title'],
            'message': template['message'].format(**request_data),
            'priority': template['priority'],
            'action_required': False,
            'metadata': request_data,
        }

        # Attach the correct FK field
        if isinstance(transport_request, HighCostTransportRequest):
            notification_kwargs['highcost_request'] = transport_request
        elif isinstance(transport_request, TransportRequest):
            notification_kwargs['transport_request'] = transport_request
        else:
            raise TypeError("Unsupported request type for trip completion notification.")

        return Notification.objects.create(**notification_kwargs)

    @classmethod
    def mark_as_read(cls, notification_id: int) -> None:
        """
        Mark a notification as read
        """
        Notification.objects.filter(id=notification_id).update(is_read=True)

    @classmethod
    def get_user_notifications(cls, user_id: int, unread_only: bool = False, 
                             page: int = 1, page_size: int = 20):
        """
        Get notifications for a user with pagination
        """
        queryset = Notification.objects.filter(recipient_id=user_id)
        if unread_only:
            queryset = queryset.filter(is_read=False)
        
        start = (page - 1) * page_size
        end = start + page_size
        return queryset[start:end]

    @classmethod
    def get_unread_count(cls, user_id: int) -> int:
        """
        Get count of unread notifications for a user
        """
        return Notification.objects.filter(recipient_id=user_id, is_read=False).count()

    @classmethod
    def clean_old_notifications(cls, days: int = 90) -> int:
        """
        Clean notifications older than specified days
        """    
        cutoff_date = timezone.now() - timedelta(days=days)
        return Notification.objects.filter(created_at__lt=cutoff_date).delete()[0]
    
def log_action(request_obj, user, action, remarks=None):
    ActionLog.objects.create(
        content_type=ContentType.objects.get_for_model(request_obj),
        object_id=request_obj.pk,
        request_object=request_obj,
        action_by=user,
        action=action,
        status_at_time=request_obj.status,  # <-- manually extracting status
        approver_role=user.role,
        remarks=remarks,
    )

class RefuelingEstimator:
    @staticmethod
    def calculate_fuel_cost(distance_km, vehicle, price_per_liter):
        if not vehicle.fuel_efficiency:
            raise ValueError("Fuel efficiency must be set.")
        fuel_needed = distance_km / float(vehicle.fuel_efficiency)
        total_cost = fuel_needed * price_per_liter * 2
        return round(fuel_needed, 2), round(total_cost, 2)



def send_sms(phone_number: str, message: str):
    base_url= settings.SMS_URL
    if not base_url:
        raise ValueError("SMS URL is not configured in settings.")
    escaped_message = urllib.parse.quote(message, safe="")
    sms_url = f"{base_url}&phonenumber={phone_number}&message={escaped_message}"

    try:
        response = requests.get(sms_url, timeout=10)
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            return {"status": "error", "message": "Invalid JSON", "raw": response.text}
    except requests.exceptions.RequestException as e:
        logger.error(f"SMS failed for {phone_number}: {e}")
        raise e


def preprocess_signature(img):
    # Binarize
    _, img_bin = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # Find contours
    contours, _ = cv2.findContours(img_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img_bin  # fallback
    # Get bounding box of largest contour
    cnt = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(cnt)
    cropped = img_bin[y:y+h, x:x+w]
    # Deskew (simple angle correction)
    coords = np.column_stack(np.where(cropped > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    (h, w) = cropped.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    deskewed = cv2.warpAffine(cropped, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    # Resize to standard size
    final = cv2.resize(deskewed, (300, 100))
    return final

def compare_signatures(user_signature_path, uploaded_signature_file, threshold=35):
   

    # Read images in grayscale
    img1 = cv2.imread(user_signature_path, 0)
    img2 = cv2.imread(uploaded_signature_file, 0)

    # Add these checks:
    if img1 is None:
        raise ValueError(f"Failed to load stored signature image from {user_signature_path}")
    if img2 is None:
        raise ValueError(f"Failed to load uploaded signature image from {uploaded_signature_file}")
    img1 = preprocess_signature(img1)
    img2 = preprocess_signature(img2)

    # SSIM comparison
    score, _ = ssim(img1, img2, full=True)
    similarity = score * 100  # Convert to percentage

    # --- Optional: Feature-based (ORB) matching ---
    orb = cv2.ORB_create()
    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(des1, des2)
    matches = sorted(matches, key=lambda x: x.distance)
    feature_similarity = len(matches) / max(len(kp1), len(kp2)) * 100 if kp1 and kp2 else 0
    similarity = (similarity + feature_similarity) / 2  # Combine scores if you want

    return similarity, similarity >= threshold 