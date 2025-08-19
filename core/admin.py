from django.contrib import admin
from .models import (
    Vehicle,
    MonthlyKilometerLog,
    CouponRequest,
    TransportRequest,
    HighCostTransportRequest,
    Notification,
    TransportRequestActionLog,
    MaintenanceRequest,
    RefuelingRequest,
    ServiceRequest,
    OTPCode,
)

admin.site.register(Vehicle)
admin.site.register(MonthlyKilometerLog)
admin.site.register(CouponRequest)
admin.site.register(TransportRequest)
admin.site.register(HighCostTransportRequest)
admin.site.register(Notification)
admin.site.register(TransportRequestActionLog)
admin.site.register(MaintenanceRequest)
admin.site.register(RefuelingRequest)
admin.site.register(ServiceRequest)
admin.site.register(OTPCode)