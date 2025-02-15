# trades/models.py

from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Alias(models.Model):
    """
    Aliases for items, linking a shorter name to a full name + optional image.
    """
    full_name = models.CharField(max_length=200, unique=False)
    short_name = models.CharField(max_length=100, blank=True)
    image_path = models.CharField(max_length=300, blank=True)
    image_file = models.ImageField(upload_to='aliases/', blank=True, null=True)

    def __str__(self):
        return f"{self.short_name} -> {self.full_name}"


class Item(models.Model):
    name = models.CharField(max_length=200, unique=True)

    def __str__(self):
        return self.name


class Transaction(models.Model):
    BUY = 'Buy'
    SELL = 'Sell'
    TYPE_CHOICES = [
        (BUY, 'Buy'),
        (SELL, 'Sell'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    trans_type = models.CharField(max_length=4, choices=TYPE_CHOICES, default=BUY)
    price = models.FloatField()
    quantity = models.FloatField()
    date_of_holding = models.DateField(default=timezone.now)
    realised_profit = models.FloatField(default=0.0)
    cumulative_profit = models.FloatField(default=0.0)

    # Add an index to speed up queries by user & date
    class Meta:
        indexes = [
            models.Index(fields=['user', 'date_of_holding']),
        ]

    def __str__(self):
        return f"{self.item.name} {self.trans_type} {self.quantity} @ {self.price}"


class AccumulationPrice(models.Model):
    item = models.OneToOneField(Item, on_delete=models.CASCADE)
    accumulation_price = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.item.name} Acc. Price = {self.accumulation_price}"


class TargetSellPrice(models.Model):
    item = models.OneToOneField(Item, on_delete=models.CASCADE)
    target_sell_price = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.item.name} Target Sell = {self.target_sell_price}"


class Membership(models.Model):
    account_name = models.CharField(max_length=100, unique=True)
    membership_status = models.CharField(max_length=10, default="No")  # "Yes"/"No"
    membership_end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.account_name} -> {self.membership_status}"


class WealthData(models.Model):
    account_name = models.CharField(max_length=100)
    year = models.IntegerField(default=2024)
    january = models.CharField(max_length=50, blank=True)
    february = models.CharField(max_length=50, blank=True)
    march = models.CharField(max_length=50, blank=True)
    april = models.CharField(max_length=50, blank=True)
    may = models.CharField(max_length=50, blank=True)
    june = models.CharField(max_length=50, blank=True)
    july = models.CharField(max_length=50, blank=True)
    august = models.CharField(max_length=50, blank=True)
    september = models.CharField(max_length=50, blank=True)
    october = models.CharField(max_length=50, blank=True)
    november = models.CharField(max_length=50, blank=True)
    december = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.account_name} {self.year}"


class Watchlist(models.Model):
    BUY = 'Buy'
    SELL = 'Sell'
    CHOICES = [
        (BUY, 'Buy'),
        (SELL, 'Sell'),
    ]
    name = models.CharField(max_length=200)
    desired_price = models.FloatField(default=0.0)
    date_added = models.DateField(default=timezone.now)
    buy_or_sell = models.CharField(max_length=4, choices=CHOICES, default=BUY)
    account_name = models.CharField(max_length=100, blank=True)
    wished_quantity = models.FloatField(default=0.0)
    total_value = models.FloatField(default=0.0)
    current_holding = models.FloatField(default=0.0)

    membership_status = models.CharField(max_length=10, default="", blank=True)
    membership_end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} -> {self.buy_or_sell} @ {self.desired_price}"


# --- New model for user banning functionality ---
class UserBan(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="ban_info")
    ban_until = models.DateTimeField(null=True, blank=True)
    permanent = models.BooleanField(default=False)

    def is_banned(self):
        if self.permanent:
            return True
        if self.ban_until and timezone.now() < self.ban_until:
            return True
        return False

    def remaining_ban_duration(self):
        if self.permanent:
            return "permanently"
        elif self.ban_until:
            delta = self.ban_until - timezone.now()
            return str(delta).split('.')[0]  # remove microseconds
        return ""
