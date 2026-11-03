from django.db import models
from django.contrib.auth.models import User
from apps.customers.models import Customer
from apps.products.models import Product
from apps.deliveries.models import Delivery


class FBRCustomerSetting(models.Model):
    """Store FBR-specific settings for each customer (STN, NTN, Invoice Number)"""
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='fbr_setting')
    invoice_number = models.CharField(max_length=50, blank=True, null=True, help_text="Starting invoice number for this customer")
    row_invoice_numbers = models.JSONField(default=dict, blank=True, help_text="Per-row invoice number overrides keyed by row identifier")
    stn = models.CharField(max_length=50, blank=True, null=True, help_text="Sales Tax Number")
    ntn = models.CharField(max_length=50, blank=True, null=True, help_text="National Tax Number")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'fbr_customer_settings'
        verbose_name = 'FBR Customer Setting'
        verbose_name_plural = 'FBR Customer Settings'
    
    def __str__(self):
        return f"FBR Settings - {self.customer.name}"


class FBRProductMapping(models.Model):
    """Map internal products to FBR invoice items"""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='fbr_mappings')
    fbr_item_name = models.CharField(max_length=100, help_text="Name shown on FBR invoice")
    unit = models.CharField(max_length=20, default='KG', choices=[
        ('KG', 'KG'),
        ('M3', 'M3'),
        ('LTR', 'LTR'),
        ('NOS', 'NOS'),
    ])
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.00, help_text="GST percentage")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'fbr_product_mappings'
        verbose_name = 'FBR Product Mapping'
        verbose_name_plural = 'FBR Product Mappings'
    
    def __str__(self):
        return f"{self.product.name} → {self.fbr_item_name}"


class FBRInvoice(models.Model):
    """FBR Invoice record"""
    invoice_no = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='fbr_invoices')
    invoice_date = models.DateField()
    total_ex_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_gst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'fbr_invoices'
        ordering = ['-invoice_date', '-created_at']
        verbose_name = 'FBR Invoice'
        verbose_name_plural = 'FBR Invoices'
    
    def __str__(self):
        return f"{self.invoice_no} - {self.customer.name}"


class FBRInvoiceItem(models.Model):
    """Individual items in FBR invoice"""
    invoice = models.ForeignKey(FBRInvoice, on_delete=models.CASCADE, related_name='items')
    product_name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit = models.CharField(max_length=20, default='KG')
    rate = models.DecimalField(max_digits=12, decimal_places=2)
    ex_value = models.DecimalField(max_digits=12, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_value = models.DecimalField(max_digits=12, decimal_places=2)
    delivery = models.ForeignKey(Delivery, on_delete=models.SET_NULL, null=True, blank=True, related_name='fbr_items')
    
    class Meta:
        db_table = 'fbr_invoice_items'
        verbose_name = 'FBR Invoice Item'
        verbose_name_plural = 'FBR Invoice Items'
    
    def __str__(self):
        return f"{self.product_name} - {self.quantity} {self.unit}"