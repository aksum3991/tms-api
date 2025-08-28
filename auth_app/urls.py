from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from auth_app.views import (
    AdminApprovalView, AdminUserDepartmentUpdateView, ApprovedUsersView, CustomTokenObtainPairView, DeactivateUserView,
    DepartmentEmployeesView, DepartmentViewSet, LogoutView, ReactivateUserView, 
    UserDetailView, UserListView, UserRegistrationView, UserResubmissionView, UserStatusHistoryViewSet
)


router = DefaultRouter()
router.register(r'departments', DepartmentViewSet)
router.register(r'status-history', UserStatusHistoryViewSet)

urlpatterns = [
    path('',include(router.urls)),
    # path("admin/", admin.site.urls),
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/logout/',LogoutView.as_view(),name='logout'),
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('approve/<int:user_id>/', AdminApprovalView.as_view(), name='approve'),
    path('users/', AdminApprovalView.as_view(), name='users'),
    path('users-list/', UserListView.as_view(), name='user-list'),
    path('api/users/me/',UserDetailView.as_view(),name='current-user'),
    path('api/users/', UserDetailView.as_view(), name='user-detail'),
    path("resubmit/<int:user_id>/", UserResubmissionView.as_view(), name="resubmit"),
    path("activate/<int:user_id>/",ReactivateUserView.as_view(),name="activate"),
    path("deactivate/<int:user_id>/",DeactivateUserView.as_view(),name="activate"),
    path("update-role/<int:user_id>/", AdminApprovalView.as_view(), name="update-role"),
    path("update-department/<int:user_id>/", AdminUserDepartmentUpdateView.as_view(), name="update-department"),
    path('approved-users/', ApprovedUsersView.as_view(), name='approved-users'),
    path("departments/<int:department_id>/employees/", DepartmentEmployeesView.as_view(), name="department-employees"),
]
