from django.contrib import admin
from .models import Factory, FactoryFillTransaction, Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['product_code', 'name', 'unit_price', 'stock_quantity', 'empty_stock_quantity', 'opening_full_quantity', 'opening_empty_quantity', 'is_quantity_only', 'is_filling_only', 'created_at']
    list_filter = ['is_quantity_only', 'is_filling_only', 'created_at']
    search_fields = ['product_code', 'name']
    readonly_fields = ['product_code', 'created_at', 'updated_at']
    fieldsets = (
        ('Basic Information', {
            'fields': ('product_code', 'name', 'unit_price')
        }),
        ('Stock Management', {
            'fields': ('stock_quantity', 'empty_stock_quantity', 'opening_full_quantity', 'opening_empty_quantity', 'unit_weight_kg', 'stock_weight_kg', 'minimum_stock')
        }),
        ('Product Type', {
            'fields': ('is_quantity_only', 'is_filling_only'),
            'description': 'Check "Quantity Only" for products sold directly to customers (not exchanged). Check "Filling Only" for LPG refill products where the customer brings a cylinder for gas filling.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Factory)
class FactoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'mobile', 'created_at']
    search_fields = ['name', 'mobile']


@admin.register(FactoryFillTransaction)
class FactoryFillTransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_date', 'factory', 'product', 'empty_sent', 'full_received', 'created_by']
    list_filter = ['factory', 'transaction_date']
    search_fields = ['factory__name', 'product__name']
    readonly_fields = ['created_at', 'created_by']
