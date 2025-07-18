# Generated by Django 5.2.3 on 2025-07-14 12:49

import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_vehicle_drivers_location"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicle",
            name="chassis_number",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="vehicle",
            name="fuel_efficiency",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Distance the vehicle can travel per liter of fuel (km/L).",
                max_digits=5,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0.1"))],
            ),
        ),
        migrations.AlterField(
            model_name="vehicle",
            name="libre_number",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="vehicle",
            name="motor_number",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
    ]
