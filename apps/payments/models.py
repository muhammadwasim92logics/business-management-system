from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
from django.utils import timezone
import uuid

def generate_payment_no():
    from datetime import datetime
    prefix = f"PAY-{datetime.now().strftime('%Y%m%d')}"
    last = Payment.objects.filter(payment_no__startswith=prefix).order_by('-payment_no').first()
    if last:
        try:
            num = int(last.payment_no.split('-')[-1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:03d}"

# Add this method to the Payment model
def save(self, *args, **kwargs):
    if not self.payment_no:
        self.payment_no = generate_payment_no()
    super().save(*args, **kwargs)
    
    # Update customer's last activity date
    from apps.customers.models import Customer
    customer = Customer.objects.get(id=self.customer_id)
    customer.last_activity_date = self.payment_date
    customer.save(update_fields=['last_activity_date', 'updated_at'])

class Payment(models.Model):
    class PaymentType(models.TextChoices):
        CASH = 'cash', 'Cash'
        CREDIT = 'credit', 'Credit'
        TRANSFER = 'transfer', 'Bank Transfer'
        UPI = 'upi', 'UPI'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_no = models.CharField(max_length=30, unique=True, blank=True)
    invoice_no = models.CharField(max_length=50, blank=True, default='')
    delivery = models.ForeignKey(
        'deliveries.Delivery',
        on_delete=models.CASCADE,
        related_name='payments',
        null=True,
        blank=True,
    )
    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='payments')
    payment_date = models.DateField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices, default=PaymentType.CASH)
    notes = models.TextField(blank=True, null=True)
    matched_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'payments'
    
    def __str__(self):
        return f"{self.payment_no} - {self.customer.name} - {self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.payment_no:
            self.payment_no = generate_payment_no()
        super().save(*args, **kwargs)