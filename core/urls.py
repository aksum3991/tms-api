from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.views import (
    TransportRequestActionView, 
    TransportRequestCreateView, 
    TransportRequestListView,
    NotificationListView, 
    NotificationMarkReadView, 
    NotificationMarkAllReadView,
    NotificationUnreadCountView,
)



urlpatterns = [
   path('create/',TransportRequestCreateView.as_view(),name="create-transport-request"),
   path('list/',TransportRequestListView.as_view(),name="transport-request-list"),
   path('<int:request_id>/action/',TransportRequestActionView.as_view(),name="transport-request-action"),
   # Notification endpoints
   path('notifications/', NotificationListView.as_view(), name='notifications'),
   path('notifications/<int:notification_id>/read/', NotificationMarkReadView.as_view(), name='mark-notification-read'),
   path('notifications/mark-all-read/', NotificationMarkAllReadView.as_view(), name='mark-all-notifications-read'),
   path('notifications/unread-count/', NotificationUnreadCountView.as_view(), name='notification-unread-count'),
]

