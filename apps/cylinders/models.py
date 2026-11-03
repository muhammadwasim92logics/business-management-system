from django.db import models
import uuid

class CylinderLedger(models.Model):
    OWNERSHIP_MOVEMENT_TYPES = (
        ('', 'Normal cylinder movement'),
        ('customer_received', 'Customer-owned cylinder received'),
        ('customer_returned', 'Customer-owned cylinder returned'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='cylinder_entries')
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True)
    transaction_date = models.DateField(auto_now_add=True)
    full_out = models.IntegerField(default=0, help_text="Full cylinders given to customer")
    empty_in = models.IntegerField(default=0, help_text="Empty cylinders returned by customer")
    guarantee_deposit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    delivery = models.ForeignKey('deliveries.Delivery', on_delete=models.SET_NULL, null=True, blank=True)
    ownership_movement = models.CharField(max_length=30, choices=OWNERSHIP_MOVEMENT_TYPES, blank=True, default='')
    ownership_quantity = models.PositiveIntegerField(default=0, help_text="Customer-owned cylinders involved in this movement")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'cylinder_ledger'
        ordering = ['-transaction_date']

    @property
    def net_with_customer(self):
        return self.full_out - self.empty_in

    def __str__(self):
        return f"{self.customer.name} - Net: {self.net_with_customer} cylinders"