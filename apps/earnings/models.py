from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Expense(models.Model):
    """Model to store daily expenses"""
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Expense'
        verbose_name_plural = 'Expenses'
    
    def __str__(self):
        return f"{self.description} - {self.amount} ({self.date})"

class OpeningBalance(models.Model):
    """Cash already on hand when earnings tracking begins."""
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Opening balance - {self.amount} ({self.date})"


class PartnerAccountBalance(models.Model):
    """Daily balance snapshot for each partner bank account."""
    partner_name = models.CharField(max_length=200)
    bank_name = models.CharField(max_length=200)
    account_amount = models.DecimalField(max_digits=15, decimal_places=2)
    description = models.TextField(blank=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-date', 'partner_name', 'bank_name', '-created_at']

    def __str__(self):
        return f"{self.partner_name} - {self.bank_name} - {self.account_amount} ({self.date})"

class DailyEarningSummary(models.Model):
    """Model to store daily earning summary"""
    date = models.DateField(unique=True)
    total_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_purchases = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_cash = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date']
        verbose_name = 'Daily Earning Summary'
        verbose_name_plural = 'Daily Earning Summaries'
    
    def __str__(self):
        return f"Summary for {self.date} - Net: {self.net_cash}"