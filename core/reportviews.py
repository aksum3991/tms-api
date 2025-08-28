from django.shortcuts import get_object_or_404
from rest_framework import permissions , status
from rest_framework.views import APIView
from rest_framework.response import Response
from core.models import ActionLog, HighCostTransportRequest, MaintenanceRequest, MonthlyKilometerLog, RefuelingRequest, ServiceRequest, TransportRequest, Vehicle, Notification
from django.db.models.functions import TruncMonth
from django.db.models import Count,Sum, Q
from datetime import datetime
from auth_app.permissions import  IsCeo, IsGeneralSystem, IsTransportManager, IsSystemAdmin
from itertools import chain
from operator import attrgetter


class RequestTypeDistributionAPIView(APIView): # used for pie chart
    permission_classes = [permissions.IsAuthenticated, IsTransportManager|IsCeo|IsGeneralSystem|IsSystemAdmin]

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



class MonthlyRequestTrendsAPIView(APIView):  # used for monthly trends bar chart
    permission_classes = [permissions.IsAuthenticated, IsTransportManager|IsCeo |IsGeneralSystem|IsSystemAdmin]

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
    permission_classes = [permissions.IsAuthenticated, IsTransportManager|IsCeo|IsGeneralSystem|IsSystemAdmin]

    def get(self, request):
        data = {
            "active_vehicles": Vehicle.objects.filter(status=Vehicle.AVAILABLE).count(),
            "under_maintenance": Vehicle.objects.filter(status=Vehicle.MAINTENANCE).count(),
            "under_service": Vehicle.objects.filter(status=Vehicle.SERVICE).count(),
            "total_rental_vehicles": Vehicle.objects.filter(source=Vehicle.RENTED).count(),
            "total_organization_owned_vehicles": Vehicle.objects.filter(source=Vehicle.ORGANIZATION_OWNED).count(),   
            "refueling_requests": RefuelingRequest.objects.count(),
            "maintenance_requests": MaintenanceRequest.objects.count(),
            "high_cost_requests": HighCostTransportRequest.objects.count(),
            "service_requests": ServiceRequest.objects.count(),
        }
        return Response(data)
    


class RecentVehicleRequestsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTransportManager |IsCeo |IsGeneralSystem|IsSystemAdmin]

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
    
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.db.models import Sum, Q
from .models import (
    MaintenanceRequest, RefuelingRequest,
    HighCostTransportRequest, ServiceRequest,
    Vehicle
)

class TransportReportView(APIView):
    permission_classes = [permissions.IsAuthenticated,IsTransportManager|IsCeo |IsGeneralSystem|IsSystemAdmin]  # Add IsTransportManager if needed

    def get(self, request):
        request_type = request.GET.get('requesttype', 'all')
        vehicle_id = request.GET.get('vehicle')
        driver_id = request.GET.get('driver')
        month = request.GET.get('month')  # Format: 'YYYY-MM' or 'all'

        model_configs = [
            {
                'label': 'Maintenance',
                'model': MaintenanceRequest,
                'cost_field': 'maintenance_total_cost',
                'vehicle_field': 'requesters_car',
                'driver_field': 'requester',
                'kilometers_field': None,
                'fuel_field': None,
            },
            {
                'label': 'Refueling',
                'model': RefuelingRequest,
                'cost_field': 'total_cost',
                'vehicle_field': 'requesters_car',
                'driver_field': 'requester',
                'kilometers_field': 'estimated_distance_km',
                'fuel_field': 'fuel_needed_liters',
            },
            {
                'label': 'HighCost',
                'model': HighCostTransportRequest,
                'cost_field': 'total_cost',
                'vehicle_field': 'vehicle',
                'driver_field': 'requester',
                'kilometers_field': 'estimated_distance_km',
                'fuel_field': 'fuel_needed_liters',
            },
            {
                'label': 'Service',
                'model': ServiceRequest,
                'cost_field': 'service_total_cost',
                'vehicle_field': 'vehicle',
                'driver_field': None,  # No driver field
                'kilometers_field': None,
                'fuel_field': None,
            },
        ]

        if request_type != 'all':
            model_configs = [cfg for cfg in model_configs if cfg['label'].lower() == request_type.lower()]

        total_requests = 0
        total_cost = 0
        by_type = []
        detailed = []

        for cfg in model_configs:
            filter_q = Q()
            # Vehicle filter
            if vehicle_id and vehicle_id != 'all':
                filter_q &= Q(**{f"{cfg['vehicle_field']}_id": vehicle_id})
            # Driver filter
            if driver_id and driver_id != 'all' and cfg['driver_field']:
                filter_q &= Q(**{f"{cfg['driver_field']}_id": driver_id})
            # Month filter
            if month and month != 'all':
                try:
                    year, month_num = map(int, month.split('-'))
                    filter_q &= Q(created_at__year=year, created_at__month=month_num)
                except Exception:
                    pass

            qs = cfg['model'].objects.filter(filter_q)
            count = qs.count()
            cost = qs.aggregate(total=Sum(cfg['cost_field']))['total'] or 0
            total_requests += count
            total_cost += cost
            by_type.append({
                'type': cfg['label'],
                'requests': count,
                'cost': cost
            })

            for req in qs:
                # Vehicle plate
                vehicle = getattr(req, cfg['vehicle_field'], None)
                plate = getattr(vehicle, 'license_plate', '-') if vehicle else '-'
                # Driver name
                driver = getattr(req, cfg['driver_field'], None) if cfg['driver_field'] else None
                driver_name = getattr(driver, 'full_name', '-') if driver else '-'
                # Kilometers
                kilometers = getattr(req, cfg['kilometers_field'], None) if cfg['kilometers_field'] else None
                # Fuel
                fuel = getattr(req, cfg['fuel_field'], None) if cfg['fuel_field'] else None
                # Cost
                cost_value = getattr(req, cfg['cost_field'], None)
                cost_value = float(cost_value) if cost_value is not None else None

                detailed.append({
                    'year_month': req.created_at.strftime('%Y/%m'),
                    'plate': plate,
                    'driver': driver_name,
                    'request_type': cfg['label'],
                    'request_count': 1,
                    'kilometers': kilometers if kilometers is not None else '-',
                    'fuel': fuel if fuel is not None else '-',
                    'cost': cost_value if cost_value is not None else '-'
                })

        return Response({
            'total_requests': total_requests,
            'total_cost': total_cost,
            'by_type': by_type,
            'detailed': detailed
        }, status=status.HTTP_200_OK)