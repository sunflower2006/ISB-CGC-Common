# -*- coding: utf-8 -*-
# Generated by Django 1.9.6 on 2016-07-15 20:03
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_auto_20160715_1256'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userauthorizeddatasets',
            name='nih_user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
