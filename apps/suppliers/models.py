from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
import uuid


class Supplier(models.Model):
    """Supplier model for tracking purchase sources"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier_code = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=200)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    bf_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Opening balance (amount you owe to this supplier)")
    ntn = models.CharField(max_length=50, blank=True, null=True, help_text="National Tax Number")
    stn = models.CharField(max_length=50, blank=True, null=True, help_text="Sales Tax Number")
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        db_table = 'suppliers'
    
    def __str__(self):
        return f"{self.supplier_code} - {self.name}"


class Purchase(models.Model):
    """Purchase order from supplier"""
    PAYMENT_TYPES = (
        ('cash', 'Cash'),
        ('transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online Transfer'),
    )
    
    TAX_TYPES = (
        ('none', 'Without Sales Tax'),
        ('with_tax', 'With Sales Tax'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry_group_id = models.UUIDField(default=uuid.uuid4, null=True, blank=True, db_index=True, editable=False)
    purchase_no = models.CharField(max_length=30, unique=True, blank=True)
    # Add this field to the Purchase model
    rate_without_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Rate per unit without tax (calculated as unit_price / 1.18)")
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchases')
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='purchases', null=True, blank=True)
    purchase_date = models.DateField()
    quantity = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, editable=False, default=0)
    delivery_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, default='cash')
    invoice_no = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_purchasable = models.BooleanField(default=False, help_text="Can this product be purchased from suppliers?")
    
    # Tax fields
    tax_type = models.CharField(max_length=20, choices=TAX_TYPES, default='none')
    sales_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, 
                                        help_text="Sales Tax Rate %")
    sales_tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, editable=False)
    subtotal_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, editable=False)
    
    # Cubic Meters field (for Oxygen/Nitrogen)
    cubic_meters = models.DecimalField(max_digits=15, decimal_places=4, default=0, editable=False)

    # Cylinder & Extra fields
    total_cubic_meters = models.DecimalField(max_digits=15, decimal_places=4, default=0, help_text="Total M³ (for Argon/Gas Mix)")
    cylinder_qty = models.IntegerField(default=0, help_text="Number of cylinders")
    cylinder_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Weight per cylinder in kg (for LPG)")
    extra_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Extra charges (not included in Total)")
    
    # ============================================================
    # ✅ ADD THIS FIELD - Rate per cylinder for LPG products
    # ============================================================
    rate_per_cylinder = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Rate per cylinder (calculated for LPG products)"
    )
    
    class Meta:
        ordering = ['-purchase_date', '-created_at']
        db_table = 'purchases'
    
    def __str__(self):
        product_name = self.product.name if self.product_id else 'Payment Only'
        return f"{self.purchase_no} - {self.supplier.name} - {product_name}"
    
    def save(self, *args, **kwargs):
        from django.utils import timezone
        
        if not self.purchase_date:
            self.purchase_date = timezone.now().date()
        if not self.purchase_no:
            prefix = f"PUR-{self.purchase_date.strftime('%Y%m%d') if self.purchase_date else timezone.now().strftime('%Y%m%d')}"
            last = Purchase.objects.filter(purchase_no__startswith=prefix).order_by('-purchase_no').first()
            if last:
                try:
                    num = int(last.purchase_no.split('-')[-1]) + 1
                except (IndexError, ValueError):
                    num = 1
            else:
                num = 1
            self.purchase_no = f"{prefix}-{num:03d}"
        
        if not self.product_id:
            self.total_amount = 0
            self.subtotal_amount = 0
            self.sales_tax_amount = 0
            super().save(*args, **kwargs)
            return

        product_name = self.product.name.lower()
        
        # ============================================================
        # CALCULATION ENGINE
        # ============================================================
        
        # 1. OXYGEN / NITROGEN (KG → M³)
        if 'oxygen' in product_name:
            # ✅ Keep quantity as KG
            kg_quantity = float(self.quantity)
            self.cubic_meters = kg_quantity * 0.7384
            # Calculate rate without tax
            rate_without_tax = (
                float(self.unit_price) / 1.18
                if self.tax_type == 'with_tax' else float(self.unit_price)
            )
            self.rate_without_tax = rate_without_tax
            # Subtotal = Rate without tax × Cubic Meters
            self.subtotal_amount = rate_without_tax * self.cubic_meters
            # ✅ Quantity remains KG
            self.quantity = kg_quantity
            # print(f"🔵 OXYGEN: {kg_quantity} KG → {self.cubic_meters} M³, Rate without Tax: {rate_without_tax}")
            
        elif 'nitrogen' in product_name:
            # ✅ Keep quantity as KG
            kg_quantity = float(self.quantity)
            self.cubic_meters = kg_quantity * 0.844
            # Calculate rate without tax
            rate_without_tax = (
                float(self.unit_price) / 1.18
                if self.tax_type == 'with_tax' else float(self.unit_price)
            )
            self.rate_without_tax = rate_without_tax
            # Subtotal = Rate without tax × Cubic Meters
            self.subtotal_amount = rate_without_tax * self.cubic_meters
            # ✅ Quantity remains KG
            self.quantity = kg_quantity
            # print(f"🔵 NITROGEN: {kg_quantity} KG → {self.cubic_meters} M³, Rate without Tax: {rate_without_tax}")
            
        # 2. CO2 (Standard KG)
        elif 'co2' in product_name and 'lpg' not in product_name:
            self.cubic_meters = 0
            self.subtotal_amount = self.quantity * self.unit_price
            
        # 3. ARGON / GAS MIX (M³ based)
        # elif 'argon' in product_name or 'mixture' in product_name:
        elif ('argon' in product_name or 'special argon' in product_name or 'mixture' in product_name or'da' in product_name or'dry air' in product_name or'da gas' in product_name):
            if self.cylinder_qty > 0 and self.total_cubic_meters > 0:
                self.cubic_meters = self.total_cubic_meters / self.cylinder_qty
                self.quantity = self.total_cubic_meters
                self.rate_without_tax = self.unit_price
                self.subtotal_amount = self.total_cubic_meters * self.unit_price
                rate = self.unit_price
                if self.tax_type == 'with_tax':
                    rate *= 1 + (self.sales_tax_rate / 100)
                self.rate_per_cylinder = (self.total_cubic_meters / self.cylinder_qty) * rate
            else:
                self.cubic_meters = 0
                self.subtotal_amount = 0
                self.rate_without_tax = 0
                self.rate_per_cylinder = 0

        # 4. LPG (Cylinder based)
        elif 'lpg' in product_name:
            if self.cylinder_weight > 0 and (self.cylinder_qty > 0 or float(self.quantity) > 0):
                total_cylinder_rate = float(self.unit_price)
                per_kg_rate = total_cylinder_rate / 11.80
                rate = per_kg_rate
                subtotal_rate = per_kg_rate
                if self.tax_type == 'with_tax':
                    rate *= 1 + (float(self.sales_tax_rate) / 100)
                    subtotal_rate = per_kg_rate / (1 + float(self.sales_tax_rate) / 100)
                self.rate_per_cylinder = rate * float(self.cylinder_weight)
                if float(self.quantity) <= 0:
                    self.quantity = float(self.cylinder_qty) * float(self.cylinder_weight)
                self.subtotal_amount = float(self.quantity) * subtotal_rate
            else:
                # Generic LPG purchases may already be entered as kilograms.
                self.subtotal_amount = self.quantity * self.unit_price
                self.rate_per_cylinder = 0

        # 5. STANDARD PRODUCTS
        else:
            self.subtotal_amount = self.quantity * self.unit_price
            self.rate_per_cylinder = 0

        # ============================================================
        # TAX & TOTAL CALCULATION
        # ============================================================
        if self.tax_type == 'with_tax':
            self.sales_tax_amount = self.subtotal_amount * (float(self.sales_tax_rate) / 100)
            self.total_amount = self.subtotal_amount + self.sales_tax_amount
        else:
            self.sales_tax_amount = 0
            self.total_amount = self.subtotal_amount

        # Extra charges and Delivery are ADDED to Total
        self.total_amount = float(self.total_amount)
        self.total_amount += float(self.delivery_charges)
        self.total_amount += float(self.extra_charges)
        
        super().save(*args, **kwargs)