from django.contrib import admin
from .models import Expense, DailyEarningSummary, PartnerAccountBalance

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['description', 'amount', 'date', 'created_by', 'created_at']
    list_filter = ['date', 'created_by']
    search_fields = ['description']
    ordering = ['-date']

@admin.register(DailyEarningSummary)
class DailyEarningSummaryAdmin(admin.ModelAdmin):
    list_display = ['date', 'total_income', 'total_purchases', 'total_expenses', 'net_cash']
    list_filter = ['date']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PartnerAccountBalance)
class PartnerAccountBalanceAdmin(admin.ModelAdmin):
    list_display = ['date', 'partner_name', 'bank_name', 'account_amount', 'description', 'updated_at']
    list_filter = ['date', 'partner_name', 'bank_name']
    search_fields = ['partner_name', 'bank_name', 'description']