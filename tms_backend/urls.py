from django.contrib import admin
from django.urls import include, path
from auth_app.urls import urlpatterns as auth_urls
from core.urls import urlpatterns as core_urls
from core.urls2 import urlpatterns as maintenance_urls
from core.urls2 import urlpatterns_refueling as refueling_urls
from core.urls2 import urlpatterns_highcost as highcost_urls
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

from core.views import AddMonthlyKilometersView, AvailableDriversView, AvailableOrganizationVehiclesListView, AvailableVehiclesListView, MyAssignedVehicleView, UserActionLogDetailView, UserActionLogListView, VehicleViewSet

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
    path("action-logs/", UserActionLogListView.as_view(), name="user-action-log-list"),
    path("action-logs/<int:pk>/", UserActionLogDetailView.as_view(), name="user-action-log-detail"),


    path("",include(router.urls))
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
