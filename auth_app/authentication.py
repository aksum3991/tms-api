from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

class CustomJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None  

        user, token = result
        if user.is_deleted:
            raise AuthenticationFailed("Your account is deactivated. Contact admin.")

        return user, token