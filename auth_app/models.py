from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils.timezone import now
from .managers import CustomUserManager

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    department_manager = models.OneToOneField(
        "User", 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="managed_department",
    )

    def __str__(self):
        return self.name


class User(AbstractBaseUser, PermissionsMixin):
    EMPLOYEE = 1
    DEPARTMENT_MANAGER = 2
    FINANCE_MANAGER = 3
    TRANSPORT_MANAGER = 4
    CEO = 5
    DRIVER = 6
    SYSTEM_ADMIN = 7
    GENERAL_SYSTEM=8
    BUDGET_MANAGER =9 

    ROLE_CHOICES = (
        (EMPLOYEE, 'Employee'),
        (DEPARTMENT_MANAGER, 'Department Manager'),
        (FINANCE_MANAGER, 'Finance Manager'),
        (TRANSPORT_MANAGER, 'Transport Manager'),
        (CEO, 'CEO'),
        (DRIVER, 'Driver'),
        (SYSTEM_ADMIN, 'System Admin'),
        (GENERAL_SYSTEM,'General System Excuter'),
        (BUDGET_MANAGER,'Budget Manager')
    )

    id = models.AutoField(primary_key=True, editable=False)
    full_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15)
    role = models.PositiveSmallIntegerField(choices=ROLE_CHOICES,default=1)
    is_active = models.BooleanField(default=False) 
    is_deleted=models.BooleanField(default=False) 
    is_pending = models.BooleanField(default=True)  
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="employees")
    

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.full_name
    
    def deactivate(self):
        self.is_active = False
        self.is_deleted = True
        self.save()

    def activate(self):
        self.is_active = True
        self.is_deleted = False
        self.save()

    def save(self, *args, **kwargs):
        if self.role == self.DEPARTMENT_MANAGER and self.department:
            existing_department = Department.objects.filter(department_manager=self).exclude(id=self.department.id).first()

            if existing_department:
                raise ValueError(f"{self.full_name} is already managing the department '{existing_department.name}'.")

            # Assign the user as the department manager only if there's no conflict
            self.department.department_manager = self
            self.department.save()

        elif self.department and self.department.department_manager == self and self.role != self.DEPARTMENT_MANAGER:
            self.department.department_manager = None
            self.department.save()

        super().save(*args, **kwargs)
    
class UserStatusHistory(models.Model):
    STATUS_CHOICES = (
        ("approve", "Approved"),
        ("reject", "Rejected"),
    )
    user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name="status_history",null=True,blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    rejection_message = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)    
  
    def __str__(self):
        return self.status