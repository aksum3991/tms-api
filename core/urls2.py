from django.urls import path

from core.reportviews import DashboardOverviewAPIView, MonthlyRequestTrendsAPIView, RecentVehicleRequestsAPIView, RequestTypeDistributionAPIView
from core.views import (
    AssignVehicleAfterBudgetApprovalView,
    CouponRequestCreateView,
    CouponRequestListView,
    HighCostTransportEstimateView,
    HighCostTransportRequestActionView,
    HighCostTransportRequestCreateView,
    HighCostTransportRequestDetailView,
    HighCostTransportRequestListView,
    MaintenanceFileSubmissionView,
    MaintenanceRequestActionView,
    MaintenanceRequestCreateView,
    MaintenanceRequestDetailView,
    MaintenanceRequestListView,
    MaintenanceRequestOwnListView,
    MarkServicedVehicleAvailableView,
    RefuelingRequestActionView,
    RefuelingRequestCreateView,
    RefuelingRequestDetailView,
    RefuelingRequestEstimateView,
    RefuelingRequestListView,
    RefuelingRequestOwnListView,
    ServiceFileSubmissionView,
    ServiceRequestActionView,
    ServiceRequestDetailView,
    ServiceRequestListView,
    ServicedVehiclesListView,
    TransportManagerServiceUpdateView,
    TripCompletionView,
    VehiclesDueForServiceView,
)

urlpatterns = [
   path('create/', MaintenanceRequestCreateView.as_view(), name='create-maintenance-request'),
   path('list/',MaintenanceRequestListView.as_view(), name= "list-maintenance-request"),
   path('<int:pk>/',MaintenanceRequestDetailView.as_view(),name="maintenance-request-detail"),
   path('<int:request_id>/action/',MaintenanceRequestActionView.as_view(),name="maintenance-request-action"),
   path('<int:request_id>/submit-files/', MaintenanceFileSubmissionView.as_view(), name='submit-maintenance-files'),
   path('my/',MaintenanceRequestOwnListView.as_view(),name="maintenance-request-own")
]

urlpatterns_refueling = [
   path('create/', RefuelingRequestCreateView.as_view(), name='create-refueling-request'),
   path('list/',RefuelingRequestListView.as_view(), name= "list-refueling-request"),
   path('<int:pk>/',RefuelingRequestDetailView.as_view(),name="refueling-request-detail"),
   path('<int:request_id>/estimate/',RefuelingRequestEstimateView.as_view(),name="estimate-refueling-request"),
   path('<int:request_id>/action/',RefuelingRequestActionView.as_view(),name="refueling-request-action"),
   path('my/',RefuelingRequestOwnListView.as_view(),name="refueling-request-own"),
]

urlpatterns_highcost = [
   path('create/', HighCostTransportRequestCreateView.as_view(), name='highcost-request-create'),
   path('list/',HighCostTransportRequestListView.as_view(),name="list-highcost-request"),
   path('<int:id>/', HighCostTransportRequestDetailView.as_view(), name='highcost-request-detail'),
   path('<int:request_id>/estimate/',HighCostTransportEstimateView.as_view(),name="estimate-highcost-request"),
   path('<int:request_id>/action/',HighCostTransportRequestActionView.as_view(),name="highcost-request-action"),
   path('<int:request_id>/assign-vehicle/', AssignVehicleAfterBudgetApprovalView.as_view(),name='highcost-request-vehicle-assign'),
   path('<int:request_id>/complete-trip/', TripCompletionView.as_view(), name='complete-trip-highcost-request')
]

urlpatterns_service=[
    path("<int:request_id>/action/",ServiceRequestActionView.as_view(),name="service-request-action"),
    path("<int:request_id>/submit-files/",ServiceFileSubmissionView.as_view(),name="service-request-file-submission"),
    path("<int:vehicle_id>/mark-service/",TransportManagerServiceUpdateView.as_view(),name="service-request-transport-manager-update"),
    path('list/',ServiceRequestListView.as_view(), name="service-request-list"),
    path("vehicles_list/",VehiclesDueForServiceView.as_view(), name="vehicles-due-for-service"),
    path('serviced-vehicles/', ServicedVehiclesListView.as_view(), name='serviced-vehicles-list'),
    path('<int:vehicle_id>/mark-available/', MarkServicedVehicleAvailableView.as_view(), name='mark-vehicle-available'),
    path('<int:pk>/',ServiceRequestDetailView.as_view(),name="service-request-detail"),
]

urlpatterns_dashboard = [
    path('recent-vehicles/', RecentVehicleRequestsAPIView.as_view(), name='dashboard-recent-vehicles'),
    path('overview/', DashboardOverviewAPIView.as_view(), name='dashboard-overview'),
    path('monthly-trends/', MonthlyRequestTrendsAPIView.as_view(), name='dashboard-monthly-trends'),
    path('type-distribution/', RequestTypeDistributionAPIView.as_view(), name='dashboard-type-distribution'),
]

urlpatterns_coupon = [
    path('create/', CouponRequestCreateView.as_view(), name='coupon-request-create'),
    path('list/', CouponRequestListView.as_view(), name='coupon-request-list'),
]