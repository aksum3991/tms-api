from django.utils.translation import gettext as _
from django.utils import timezone
from datetime import timedelta
from auth_app.models import User
from core.models import MaintenanceRequest, TransportRequest, Notification


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
        }
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
        print(kwargs)
        passengers = list(transport_request.employees.all())
        print("Passengers: ", passengers)
        passengers_str = ", ".join([p.full_name for p in passengers]) if passengers else "No additional passengers"       
        print(type(passengers_str))
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
       
        print("Notification message kwargs:", message_kwargs)
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
