# Generated by Django 5.1.6 on 2025-04-15 08:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_alter_refuelingrequest_destination_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="highcosttransportrequest",
            name="current_approver_role",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "Employee"),
                    (2, "Department Manager"),
                    (3, "Finance Manager"),
                    (4, "Transport Manager"),
                    (5, "CEO"),
                    (6, "Driver"),
                    (7, "System Admin"),
                    (8, "General System Excuter"),
                    (9, "Budget Manager"),
                ],
                default=5,
            ),
        ),
        migrations.AlterField(
            model_name="refuelingrequest",
            name="destination",
            field=models.CharField(max_length=1006),
        ),
    ]
