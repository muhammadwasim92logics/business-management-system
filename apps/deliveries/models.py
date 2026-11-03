from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
import uuid


def generate_delivery_no():
    from datetime import datetime
    prefix = f"DEL-{datetime.now().strftime('%Y%m%d')}"
    last = Delivery.objects.filter(delivery_no__startswith=prefix).order_by('-delivery_no').first()
    if last:
        try:
            num = int(last.delivery_no.split('-')[-1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:03d}"

class Delivery(models.Model):
    CYLINDER_MOVEMENT_TYPES = (
        ('', 'Normal delivery'),
        ('customer_received', 'Customer-owned cylinder received'),
        ('customer_returned', 'Customer-owned cylinder returned'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delivery_no = models.CharField(max_length=30, unique=True, blank=True)
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='deliveries')
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='deliveries')
    delivery_date = models.DateField()
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    empty_returned = models.IntegerField(default=0)
    full_delivered = models.IntegerField(default=0)
    is_guarantee = models.BooleanField(default=False)
    guarantee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remarks = models.TextField(blank=True, null=True)
    invoice_no = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Optional invoice number; duplicate numbers are allowed",
    )
    fbr_invoice_no = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Invoice number assigned by the FBR invoicing sequence",
    )
    delivery_charges = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Optional delivery charges")
    
    # ============================================================
    # ✅ ADD THIS MISSING FIELD
    # ============================================================
    has_returns = models.BooleanField(default=False, help_text="Does this delivery have any empty returns?")
    
    # ============================================================
    # DAMAGE CHARGES FIELDS
    # ============================================================
    damage_charges = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Charges for damaged cylinders/products"
    )
    damage_description = models.TextField(
        blank=True,
        null=True,
        help_text="Description of damage (e.g., 'Dented cylinder', 'Valve broken')"
    )
    
    # ============================================================
    # LOW PRESSURE CYLINDER FIELDS
    # ============================================================
    low_pressure_details = models.JSONField(
        default=list,
        blank=True,
        null=True,
        help_text="Details of low pressure cylinders [{total_pressure, actual_pressure, calculated_price}]"
    )
    
    # ============================================================
    # FULL CYLINDER RETURN FIELDS
    # ============================================================
    full_returned = models.IntegerField(default=0, help_text="Full cylinders returned by customer")
    full_returned_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Credit value of full returned cylinders")
    full_returned_paid = models.BooleanField(default=False, help_text="Was full returned cylinder value paid cash to customer on spot?")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, null=True, blank=True)
    payment_type = models.CharField(max_length=20, default='cash', null=True, blank=True)
    description = models.TextField(blank=True, null=True, help_text="Description/Note for this delivery (e.g., 10kg gas only)")
    cylinder_movement_type = models.CharField(max_length=30, choices=CYLINDER_MOVEMENT_TYPES, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        db_table = 'deliveries'

    def __str__(self):
        return f"{self.delivery_no} - {self.customer.name}"

    @property
    def is_sale_only(self):
        if self.product and (self.product.is_quantity_only or self.product.is_filling_only):
            return True
        return not self.cylinderledger_set.exists()

    @property
    def is_filling_only(self):
        return bool(self.product and self.product.is_filling_only)

    @property
    def calculation_details(self):
        """Return readable arithmetic notes for exceptional delivery pricing."""
        from decimal import Decimal

        details = []
        low_pressure_items = self.low_pressure_details or []
        if low_pressure_items:
            full_rate_quantity = max(0, (self.quantity or 0) - len(low_pressure_items))
            details.append(
                f"Pricing: {full_rate_quantity} full-rate + "
                f"{len(low_pressure_items)} low-pressure cylinder(s) "
                f"at PKR {self.unit_price:,.2f} full rate"
            )
            for index, item in enumerate(low_pressure_items, start=1):
                if not isinstance(item, dict):
                    continue
                standard = Decimal(str(item.get('total_pressure', 0) or 0))
                actual = Decimal(str(item.get('actual_pressure', 0) or 0))
                calculated = Decimal(str(item.get('calculated_price', 0) or 0))
                details.append(
                    f"Low pressure #{index}: {actual:g}/{standard:g} PSI "
                    f"-> PKR {calculated:,.2f}"
                )

        return details

    @property
    def return_details(self):
        """Return readable notes for full-cylinder returns."""
        if not self.full_returned:
            return []
        payment_status = 'paid cash on spot' if self.full_returned_paid else 'credited to account'
        return [
            f"Full return: {self.full_returned} cylinder(s) "
            f"-> PKR {self.full_returned_value:,.2f} ({payment_status})"
        ]

    def save(self, *args, **kwargs):
        from django.utils import timezone
        from decimal import Decimal

        if not self.delivery_date:
            self.delivery_date = timezone.now().date()
        if not self.delivery_no:
            self.delivery_no = generate_delivery_no()
        
        # ============================================================
        # ✅ AUTO-SET has_returns based on empty_returned
        # ============================================================
        self.has_returns = self.empty_returned > 0
        
        # ============================================================
        # CALCULATE PRODUCT COST (WITH LOW PRESSURE ADJUSTMENT)
        # ============================================================
        if self.low_pressure_details and isinstance(self.low_pressure_details, list) and len(self.low_pressure_details) > 0:
            num_low_pressure = len(self.low_pressure_details)
            full_qty = max(0, (self.quantity or 0) - num_low_pressure)
            full_cost = Decimal(str(full_qty)) * Decimal(str(self.unit_price or 0))
            
            low_pressure_cost = Decimal('0')
            for lp in self.low_pressure_details:
                if isinstance(lp, dict):
                    calc_price = lp.get('calculated_price', 0)
                    try:
                        low_pressure_cost += Decimal(str(calc_price))
                    except Exception:
                        pass
            product_total = full_cost + low_pressure_cost
        else:
            product_total = Decimal(str(self.quantity or 0)) * Decimal(str(self.unit_price or 0))
            
        self.delivery_amount = (
            product_total
            + Decimal(str(self.delivery_charges or 0))
            + Decimal(str(self.damage_charges or 0))
            - Decimal(str(self.full_returned_value or 0))
        )
        if self.invoice_no is not None:
            self.invoice_no = self.invoice_no.strip() or None
        if self.fbr_invoice_no is not None:
            self.fbr_invoice_no = self.fbr_invoice_no.strip() or None
        super().save(*args, **kwargs)


class DeliveryInvoiceSequence(models.Model):
    next_number = models.PositiveBigIntegerField(default=1001)

    class Meta:
        db_table = 'delivery_invoice_sequence'