from django.contrib import admin
from django.urls import include, path
from auth_app.urls import urlpatterns as auth_urls
from core.urls import urlpatterns as core_urls
from core.urls2 import urlpatterns as maintenance_urls
from core.urls2 import urlpatterns_refueling as refueling_urls
from core.urls2 import urlpatterns_highcost as highcost_urls
from rest_framework.routers import DefaultRouter

from core.views import AvailableDriversView, AvailableVehiclesListView, MyAssignedVehicleView, VehicleViewSet

router = DefaultRouter()
router.register(r'vehicles',VehicleViewSet)
urlpatterns = [
    path('',include(auth_urls)),
    path("transport-requests/",include(core_urls)),
    path('available-drivers/', AvailableDriversView.as_view(), name='available-drivers'),
    path('available-vehicles/', AvailableVehiclesListView.as_view(), name='available-vehicles'), 
    path('my-vehicle/', MyAssignedVehicleView.as_view(), name='my-assigned-vehicle'),
    path("maintenance-requests/",include(maintenance_urls)),
    path("refueling_requests/",include(refueling_urls)),
    path("highcost-requests/",include(highcost_urls)),

    path("",include(router.urls))
]
