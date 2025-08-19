from django.contrib import admin
from .models import Department, User, UserStatusHistory

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'department_manager')

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'role', 'is_active', 'is_pending')
    list_filter = ('role', 'is_active', 'is_pending')

@admin.register(UserStatusHistory)
class UserStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'timestamp')