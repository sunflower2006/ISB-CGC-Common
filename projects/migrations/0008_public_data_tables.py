# -*- coding: utf-8 -*-
# Generated by Django 1.9.6 on 2016-12-07 22:26
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0007_auto_20161114_1614'),
    ]

    operations = [
        migrations.CreateModel(
            name='Public_Data_Tables',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data_table', models.CharField(max_length=100)),
                ('samples_table', models.CharField(max_length=100)),
                ('attr_table', models.CharField(max_length=100)),
                ('sample_data_availability_table', models.CharField(max_length=100)),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='projects.Program')),
            ],
        ),
    ]