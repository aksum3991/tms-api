from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, viewsets
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.tokens import RefreshToken,AccessToken
from rest_framework.pagination import PageNumberPagination

from auth_app.permissions import IsSystemAdmin
from auth_app.services import StandardResultsSetPagination, send_approval_email, send_rejection_email
from .models import Department, User, UserStatusHistory
from .serializers import DepartmentSerializer, UserDetailSerializer, UserRegistrationSerializer, AdminApproveSerializer, UserStatusHistorySerializer

class UserRegistrationView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Your registration is in progress. Check your email for updates."
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        if request.user.id != user_id:
            return Response({"error": "You are not authorized to view this user's details."}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            user = User.objects.get(id=user_id)
            serializer = UserDetailSerializer(user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, user_id):
        if request.user.id != user_id:
            return Response({"error": "You are not authorized to delete this user."}, status=status.HTTP_403_FORBIDDEN)
        
        try:
            user = User.objects.get(id=user_id)
            user.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, user_id):
        if request.user.id != user_id:
            return Response({"error": "You are not authorized to update this user."}, status=status.HTTP_403_FORBIDDEN)

        try:
            user = User.objects.get(id=user_id)
            serializer = UserDetailSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)


class AdminApprovalView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSystemAdmin]

    def get(self,request):
        pending_users = User.objects.filter(is_pending=True)

        paginator = PageNumberPagination()
        paginator.page_size = 10  
        paginated_users = paginator.paginate_queryset(pending_users, request)
        serializer = UserDetailSerializer(paginated_users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)  

    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id, is_pending=True)
        except User.DoesNotExist:
            return Response(
                {"error": "No pending user found with this ID."},
                status=status.HTTP_404_NOT_FOUND,
            )

        action = request.data.get("action")
        if action not in dict(UserStatusHistory.STATUS_CHOICES):
            return Response(
                {"error": "Invalid action. Please specify 'approve' or 'reject'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request_data = {
            "is_active": action == UserStatusHistory.STATUS_CHOICES[0][0],
            "is_pending": False,
        }

        if action == UserStatusHistory.STATUS_CHOICES[1][0]:
            rejection_message = request.data.get("rejection_message", "").strip()
            if not rejection_message:
                return Response(
                    {"error": "Rejection message is required for rejection."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            request_data["rejection_message"] = rejection_message

        serializer = AdminApproveSerializer(user, data=request_data, partial=True)
        if serializer.is_valid():
            UserStatusHistory.objects.create(
                user=user,
                status=action,
                rejection_message=rejection_message if action == UserStatusHistory.STATUS_CHOICES[1][0] else None,
            )

            try:
                if action == UserStatusHistory.STATUS_CHOICES[0][0]:
                    send_approval_email(user)
                elif action == UserStatusHistory.STATUS_CHOICES[1][0]:
                    send_rejection_email(user, rejection_message)
                serializer.save()
            except Exception as e:
                return Response(
                    {
                        "error": (
                            f"User {action}d, but email could not be sent. "
                            f"Error: {str(e)}"
                        )
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(
                {"message": f"User {action}d successfully, and email sent."},
                status=status.HTTP_200_OK,
            )
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, user_id):
       
        user = get_object_or_404(User, id=user_id)

        try:
            new_role = int(request.data.get("role"))
        except (TypeError, ValueError):
            return Response(
                {"error": "Invalid role format. Role must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_roles = {choice[0] for choice in User.ROLE_CHOICES}
        if new_role not in valid_roles:
            return Response(
                {"error": "Invalid role. Please provide a valid role."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.role == User.SYSTEM_ADMIN:
            return Response(
                {"error": "System Admin role cannot be changed."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if user.role == new_role:
            return Response(
                {"message": f"User is already assigned the role {user.get_role_display()}."},
                status=status.HTTP_200_OK,
            )

        user.role = new_role
        user.save()

        return Response(
            {"message": f"User role updated to {user.get_role_display()} successfully."},
            status=status.HTTP_200_OK,
        )
    
      
class UserResubmissionView(APIView):
    permission_classes = [permissions.AllowAny]
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            serializer = UserDetailSerializer(user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found or access denied."}, status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found or access denied."}, status=status.HTTP_404_NOT_FOUND)

        serializer = UserDetailSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            user.is_pending = True  
            user.save()

            return Response({"message": "Your details have been updated and sent for review."}, status=status.HTTP_200_OK)

        return Response({"message": "Here is the error detail", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    


class DeactivateUserView(APIView):
    permission_classes = [IsSystemAdmin]  

    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.deactivate()
            return Response({"message": "User deactivated successfully."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

class ReactivateUserView(APIView):
    permission_classes = [IsSystemAdmin]  

    def post(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.activate()
            return Response({"message": "User reactivated successfully."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        

class UserStatusHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserStatusHistory.objects.all().order_by('-timestamp')
    serializer_class = UserStatusHistorySerializer
    permission_classes = [permissions.IsAuthenticated] 
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == user.SYSTEM_ADMIN:
            return UserStatusHistory.objects.all().order_by('-timestamp')
        return UserStatusHistory.objects.filter(user=user).order_by('-timestamp')


        
class DepartmentViewSet(ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [permissions.IsAuthenticated]

class ApprovedUsersView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSystemAdmin]
    
    def get(self, request):
        approved_users = User.objects.filter(is_active=True, is_pending=False)
        paginator = PageNumberPagination()
        paginator.page_size = 10
        paginated_users = paginator.paginate_queryset(approved_users, request)
        serializer = UserDetailSerializer(paginated_users, many=True)
        
        if not approved_users.exists():
            return Response({"message": "No approved users found."}, status=status.HTTP_204_NO_CONTENT)

        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminNotificationsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSystemAdmin]

    def get(self, request):
        pending_users = User.objects.filter(is_pending=True)
        pending_count = pending_users.count()

        if pending_count == 0:
            return Response({"message": "No new registration requests."}, status=status.HTTP_204_NO_CONTENT)

        serializer = UserDetailSerializer(pending_users, many=True)
        return Response({
            "new_registration_requests": pending_count,
            "pending_users": serializer.data
        }, status=status.HTTP_200_OK)

# class LogoutView(APIView):
#     permission_classes = [permissions.IsAuthenticated]

#     def post(self, request):
#         try:
#             refresh_token = request.data.get("refresh")
#             if not refresh_token:
#                 return Response({"error": "Refresh token is required"}, status=status.HTTP_400_BAD_REQUEST)

#             refresh = RefreshToken(refresh_token)  
#             refresh.blacklist()

#             auth_header = request.headers.get("Authorization")
#             if auth_header and auth_header.startswith("Bearer "):  
#                 access_token = auth_header.split(" ")[1]
#                 try:  
#                     access = AccessToken(access_token)
#                     access.blacklist()
#                 except Exception as e:
#                     print(f"Error blacklisting access token: {e}") 
                   
#             return Response({"message": "Successfully logged out"}, status=status.HTTP_200_OK)

#         except Exception as e:
#             print(f"Logout error: {e}")  
#             return Response({"error": "An error occurred during logout"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        