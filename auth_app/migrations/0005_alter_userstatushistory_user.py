# Generated by Django 5.1.5 on 2025-01-29 08:55

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("auth_app", "0003_alter_userstatushistory_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userstatushistory",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="status_history",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
