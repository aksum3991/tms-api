# Generated by Django 5.1.6 on 2025-04-17 13:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_maintenancerequest_maintenance_letter_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="maintenancerequest",
            name="date",
            field=models.DateField(),
        ),
    ]
