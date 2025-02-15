# Generated by Django 5.1.5 on 2025-01-17 09:05

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Alias',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=200)),
                ('short_name', models.CharField(blank=True, max_length=100)),
                ('image_path', models.CharField(blank=True, max_length=300)),
            ],
        ),
        migrations.CreateModel(
            name='Item',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='Membership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_name', models.CharField(max_length=100, unique=True)),
                ('membership_status', models.CharField(default='No', max_length=10)),
                ('membership_end_date', models.DateField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Watchlist',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('desired_price', models.FloatField(default=0.0)),
                ('date_added', models.DateField(default=django.utils.timezone.now)),
                ('buy_or_sell', models.CharField(choices=[('Buy', 'Buy'), ('Sell', 'Sell')], default='Buy', max_length=4)),
                ('account_name', models.CharField(blank=True, max_length=100)),
                ('wished_quantity', models.FloatField(default=0.0)),
                ('total_value', models.FloatField(default=0.0)),
                ('current_holding', models.FloatField(default=0.0)),
                ('membership_status', models.CharField(blank=True, default='', max_length=10)),
                ('membership_end_date', models.DateField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='WealthData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_name', models.CharField(max_length=100)),
                ('year', models.IntegerField(default=2024)),
                ('january', models.CharField(blank=True, max_length=50)),
                ('february', models.CharField(blank=True, max_length=50)),
                ('march', models.CharField(blank=True, max_length=50)),
                ('april', models.CharField(blank=True, max_length=50)),
                ('may', models.CharField(blank=True, max_length=50)),
                ('june', models.CharField(blank=True, max_length=50)),
                ('july', models.CharField(blank=True, max_length=50)),
                ('august', models.CharField(blank=True, max_length=50)),
                ('september', models.CharField(blank=True, max_length=50)),
                ('october', models.CharField(blank=True, max_length=50)),
                ('november', models.CharField(blank=True, max_length=50)),
                ('december', models.CharField(blank=True, max_length=50)),
            ],
        ),
        migrations.CreateModel(
            name='AccumulationPrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('accumulation_price', models.FloatField(default=0.0)),
                ('item', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='trades.item')),
            ],
        ),
        migrations.CreateModel(
            name='TargetSellPrice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_sell_price', models.FloatField(default=0.0)),
                ('item', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='trades.item')),
            ],
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trans_type', models.CharField(choices=[('Buy', 'Buy'), ('Sell', 'Sell')], default='Buy', max_length=4)),
                ('price', models.FloatField()),
                ('quantity', models.FloatField()),
                ('date_of_holding', models.DateField(default=django.utils.timezone.now)),
                ('realised_profit', models.FloatField(default=0.0)),
                ('cumulative_profit', models.FloatField(default=0.0)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='trades.item')),
            ],
        ),
    ]
