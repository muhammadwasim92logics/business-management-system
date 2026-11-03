from django.contrib import admin
from .models import FBRProductMapping, FBRInvoice, FBRInvoiceItem

@admin.register(FBRProductMapping)
class FBRProductMappingAdmin(admin.ModelAdmin):
    list_display = ['product', 'fbr_item_name', 'unit', 'gst_rate', 'is_active']
    list_filter = ['is_active', 'unit']
    search_fields = ['product__name', 'fbr_item_name']


@admin.register(FBRInvoice)
class FBRInvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_no', 'customer', 'invoice_date', 'total_value', 'created_at']
    list_filter = ['invoice_date', 'created_at']
    search_fields = ['invoice_no', 'customer__name']
    readonly_fields = ['total_ex_value', 'total_gst', 'total_value']


@admin.register(FBRInvoiceItem)
class FBRInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'product_name', 'quantity', 'unit', 'total_value']
    search_fields = ['product_name', 'invoice__invoice_no']