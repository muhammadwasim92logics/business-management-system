from django.contrib import admin
from .models import Supplier, Purchase

# apps/suppliers/admin.py

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['supplier_code', 'name', 'mobile', 'ntn', 'stn', 'bf_balance']  # Added bf_balance
    search_fields = ['name', 'mobile', 'supplier_code']
    readonly_fields = ['supplier_code', 'created_at', 'updated_at']
    fields = ['name', 'mobile', 'address', 'ntn', 'stn', 'bf_balance', 'notes']  # Added bf_balance


# suppliers/admin.py

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ['purchase_no', 'supplier', 'product', 'purchase_date', 
                    'quantity', 'subtotal_amount', 'sales_tax_amount', 'total_amount']
    list_filter = ['purchase_date', 'supplier', 'product', 'tax_type']
    search_fields = ['purchase_no', 'invoice_no']
    readonly_fields = ['purchase_no', 'subtotal_amount', 'sales_tax_amount', 
                       'total_amount', 'created_at', 'updated_at']
    
    fieldsets = (
        (None, {
            'fields': ('purchase_no', 'supplier', 'product', 'purchase_date')
        }),
        ('Purchase Details', {
            'fields': ('quantity', 'unit_price', 'delivery_charges')
        }),
        ('Tax Information', {
            'fields': ('tax_type', 'sales_tax_rate', 'subtotal_amount', 
                       'sales_tax_amount', 'total_amount')
        }),
        ('Payment', {
            'fields': ('paid_amount', 'payment_type', 'invoice_no', 'description')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )