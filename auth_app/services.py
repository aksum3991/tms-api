from django.core.mail import send_mail
from rest_framework.pagination import PageNumberPagination

def send_approval_email(user):
    subject = "Registration Approved"
    redirect_link=f"http://localhost:8000/api/login/"
    message = (
        f"Dear {user.full_name},\n\n"
        "Your registration has been approved. You can now log in using the link below:\n" 
        f"{redirect_link}.\n\n"
        "Best regards,\nAdmin Team"
    )
    from_email = 'mebrhit765@gmail.com'  
    recipient_list = [user.email]
    send_mail(subject, message, from_email, recipient_list)

def send_rejection_email(user, rejection_message):
    subject = "Registration Rejected"
    resubmit_link = f"http://localhost:8000/resubmit/{user.id}"  
    message = (
        f"Dear {user.full_name},\n\n"
        "Your registration was rejected for the following reason:\n\n"
        f"{rejection_message}\n\n"
        "Please review and correct your details using the link below:\n"
        f"{resubmit_link}\n\n"
        "Best regards,\nAdmin Team"
    )
    from_email = 'mebrhit765@gmail.com'  
    recipient_list = [user.email]
    send_mail(subject, message, from_email, recipient_list)



# def create_registration_notification(user):
#     email=[user.email]
#     message = f"A new user registration request has been made for",email ,"."
#     Notification.objects.create(
#         user=user,  
#         message=message
#     )

# def create_resubmission_notification(user):
#     message = f"User {user.email} has resubmitted their registration."
#     Notification.objects.create(
#         user=user,  
#         message=message
    # )

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100