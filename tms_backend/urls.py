from django.contrib import admin
from django.urls import include, path
from auth_app.urls import urlpatterns as auth_urls
from core.reportviews import TransportReportView
from core.urls import urlpatterns as core_urls
from core.urls2 import urlpatterns as maintenance_urls
from core.urls2 import urlpatterns_refueling as refueling_urls
from core.urls2 import urlpatterns_highcost as highcost_urls
from core.urls2 import urlpatterns_service as service_urls
from core.urls2 import urlpatterns_dashboard as dashboard_urls
from core.urls2 import urlpatterns_coupon as coupon_urls
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

from core.views import AddMonthlyKilometersView, AvailableDriversView, AvailableOrganizationVehiclesListView, AvailableVehiclesListView, MyAssignedVehicleView, MyMonthlyKilometerLogsListView, ReportAPIView, RequestOTPView, UserActionLogDetailView, UserActionLogListView, VehicleMarkAsMaintenanceView, VehicleViewSet, VehiclesAfterMaintenanceListView, VehiclesWithPendingMaintenanceRequestsView

router = DefaultRouter()
router.register(r'vehicles',VehicleViewSet)
urlpatterns = [
    path('admin/', admin.site.urls),
    path('',include(auth_urls)),
    path("transport-requests/",include(core_urls)),
    path('available-drivers/', AvailableDriversView.as_view(), name='available-drivers'),
    path('available-vehicles/', AvailableVehiclesListView.as_view(), name='available-vehicles'), 
    path('organization-available-vehicles/', AvailableOrganizationVehiclesListView.as_view(), name='organization-available-vehicles'),
    path('my-vehicle/', MyAssignedVehicleView.as_view(), name='my-assigned-vehicle'),
    path("maintenance-requests/",include(maintenance_urls)),
    path("refueling_requests/",include(refueling_urls)),
    path("highcost-requests/",include(highcost_urls)),
    path("vehicles/<int:vehicle_id>/add-monthly-kilometers/",AddMonthlyKilometersView.as_view(),name="add-monthly-kilometers"),
    path('vehicles/kilometer-logs/', MyMonthlyKilometerLogsListView.as_view(), name='my-kilometer-logs'),
    path("action-logs/", UserActionLogListView.as_view(), name="user-action-log-list"),
    path("action-logs/<int:pk>/", UserActionLogDetailView.as_view(), name="user-action-log-detail"),
    path('transport-report/', TransportReportView.as_view(), name='transport-report'),
    path('report/', ReportAPIView.as_view(), name='report-api'),
    path("service-requests/", include(service_urls)),
    path("dashboard/",include(dashboard_urls)),
    path("",include(router.urls)),
    path('otp/request/', RequestOTPView.as_view(), name='request-otp'),
    path('coupon-requests/', include(coupon_urls)),
    path('maintained-vehicles/', VehiclesAfterMaintenanceListView.as_view(), name='vehicles-ready-after-maintenance'),
    path('vehicles/under-maintenance/list/', VehiclesWithPendingMaintenanceRequestsView.as_view(), name='vehicles-under-maintenance'),
    path('vehicles/<int:vehicle_id>/mark-as-maintenance/', VehicleMarkAsMaintenanceView.as_view(), name='vehicle-mark-as-maintenance'),
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
