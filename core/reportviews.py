from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from core.models import ActionLog, HighCostTransportRequest, MaintenanceRequest, MonthlyKilometerLog, RefuelingRequest, ServiceRequest, TransportRequest, Vehicle, Notification
from django.db.models.functions import TruncMonth
from django.db.models import Count
from datetime import datetime
from auth_app.permissions import  IsTransportManager
from itertools import chain
from operator import attrgetter


class RequestTypeDistributionAPIView(APIView): # used for pie chart
    permission_classes = [permissions.IsAuthenticated, IsTransportManager]

    def get(self, request):
        current_year = datetime.now().year
        refueling_count = RefuelingRequest.objects.filter(created_at__year=current_year).count()
        maintenance_count = MaintenanceRequest.objects.filter(created_at__year=current_year).count()
        high_cost_count = HighCostTransportRequest.objects.filter(created_at__year=current_year).count()
        service_count = ServiceRequest.objects.filter(created_at__year=current_year).count()
        total = refueling_count + maintenance_count + high_cost_count + service_count

        data = {
            "refueling": round((refueling_count / total) * 100, 2) if total else 0,
            "maintenance": round((maintenance_count / total) * 100, 2) if total else 0,
            "high_cost": round((high_cost_count / total) * 100, 2) if total else 0,
            "service": round((service_count / total) * 100, 2) if total else 0,
        }
        return Response(data)


from calendar import month_name

class MonthlyRequestTrendsAPIView(APIView):  # used for monthly trends bar chart
    permission_classes = [permissions.IsAuthenticated, IsTransportManager]

    def get(self, request):
        current_year = datetime.now().year

        def process_trend(qs):
            result = []
            for entry in qs:
                # entry['month'] is a datetime object or string, parse if needed
                month_dt = entry['month']
                if isinstance(month_dt, str):
                    # Parse string to datetime if needed
                    from dateutil.parser import parse
                    month_dt = parse(month_dt)
                result.append({
                    # "month": month_dt.strftime("%B"),  # Full month name, e.g., "June"
                    "month": month_dt.strftime("%Y-%m"),  # "2025-06"
                    "count": entry['count']
                })
            return result

        trends = {
            "refueling": process_trend(
                RefuelingRequest.objects.filter(created_at__year=current_year)
                .annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(count=Count('id'))
                .order_by('month')
            ),
            "maintenance": process_trend(
                MaintenanceRequest.objects.filter(created_at__year=current_year)
                .annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(count=Count('id'))
                .order_by('month')
            ),
            "high_cost": process_trend(
                HighCostTransportRequest.objects.filter(created_at__year=current_year)
                .annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(count=Count('id'))
                .order_by('month')
            ),
            "service": process_trend(
                ServiceRequest.objects.filter(created_at__year=current_year)
                .annotate(month=TruncMonth('created_at'))
                .values('month')
                .annotate(count=Count('id'))
                .order_by('month')
            ),
        }
        return Response(trends)
class DashboardOverviewAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTransportManager]

    def get(self, request):
        data = {
            "active_vehicles": Vehicle.objects.filter(status=Vehicle.AVAILABLE).count(),
            "under_maintenance": Vehicle.objects.filter(status=Vehicle.MAINTENANCE).count(),
            "under_service": Vehicle.objects.filter(status=Vehicle.SERVICE).count(),
            "total_rental_vehicles": Vehicle.objects.filter(source=Vehicle.RENTED).count(),
            "refueling_requests": RefuelingRequest.objects.count(),
            "maintenance_requests": MaintenanceRequest.objects.count(),
            "high_cost_requests": HighCostTransportRequest.objects.count(),
            "service_requests": ServiceRequest.objects.count(),
        }
        return Response(data)
    


class RecentVehicleRequestsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTransportManager]

    def get(self, request):
        # Get the latest 5 requests from all request types
        refuelings = RefuelingRequest.objects.select_related('requesters_car').order_by('-created_at')[:5]
        maintenances = MaintenanceRequest.objects.select_related('requesters_car').order_by('-created_at')[:5]
        highcosts = HighCostTransportRequest.objects.select_related('vehicle').order_by('-created_at')[:5]
        services = ServiceRequest.objects.select_related('vehicle').order_by('-created_at')[:5]

        # Combine and sort by created_at
        all_requests = list(chain(refuelings, maintenances, highcosts, services))
        all_requests = sorted(all_requests, key=attrgetter('created_at'), reverse=True)[:5]

        results = []
        for req in all_requests:
            if isinstance(req, RefuelingRequest):
                vehicle = req.requesters_car
                req_type = "Refueling Requests"
            elif isinstance(req, MaintenanceRequest):
                vehicle = req.requesters_car
                req_type = "Maintenance Requests"
            elif isinstance(req, HighCostTransportRequest):
                vehicle = req.vehicle
                req_type = "High Cost Requests"
            elif isinstance(req, ServiceRequest):
                vehicle = req.vehicle
                req_type = "Service Requests"
            else:
                continue

            results.append({
                "vehicle": f"{vehicle.model} {vehicle.license_plate}" if vehicle else None,
                "type": req_type,
                "status": req.status,  # You may want to map this to display values
                "date": req.created_at.date().isoformat() if req.created_at else None,
            })

        return Response({"results": results})