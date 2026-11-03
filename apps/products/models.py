from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
import uuid

def generate_product_code():
    last = Product.objects.order_by('-created_at').first()
    if last and last.product_code:
        try:
            num = int(last.product_code.split('-')[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f'PROD-{num:04d}'

class Product(models.Model):
    PRODUCT_TYPES = (
        ('purchase', 'For Purchase Only'),
        ('sale', 'For Sale Only'),
        ('both', 'For Both'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_code = models.CharField(max_length=20, unique=True, blank=True)
    name = models.CharField(max_length=200, unique=True)
    
    category = models.CharField(max_length=100, blank=True, null=True)
    
    # 👈 ADD THESE FIELDS
    is_sellable = models.BooleanField(default=True, help_text="Show in Sales module")
    is_purchasable = models.BooleanField(default=False, help_text="Show in Purchases module")
    
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)], help_text="Price when purchasing from supplier")
    
    stock_quantity = models.IntegerField(default=0)
    empty_stock_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    opening_full_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)], help_text="Full cylinders owned when tracking started")
    opening_empty_quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)], help_text="Empty cylinders owned when tracking started")
    unit_weight_kg = models.DecimalField(max_digits=8, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    stock_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    minimum_stock = models.IntegerField(default=5, validators=[MinValueValidator(0)])
    is_quantity_only = models.BooleanField(default=False)
    is_filling_only = models.BooleanField(
        default=False,
        help_text='Customer brings a cylinder only to be filled; no empty cylinder exchange is tracked and quantity is interpreted as gas kg.'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
        db_table = 'products'
    
    def __str__(self):
        return f"{self.product_code} - {self.name}"
    
    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.upper().strip()
        if not self.product_code:
            self.product_code = generate_product_code()
        super().save(*args, **kwargs)


class StockOpeningBalance(models.Model):
    """Editable opening quantity used by the stock-details report."""
    category = models.CharField(max_length=50, unique=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0, validators=[MinValueValidator(0)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stock_opening_balances'
        ordering = ['category']

    def __str__(self):
        return f"{self.category}: {self.quantity}"


class Factory(models.Model):
    """Factory used for cylinder filling transactions."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    mobile = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        db_table = 'factories'

    def __str__(self):
        return self.name


class FactoryFillTransaction(models.Model):
    """A movement of empty cylinders to a factory and full cylinders back."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    factory = models.ForeignKey(Factory, on_delete=models.PROTECT, related_name='fill_transactions')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='factory_fills')
    transaction_date = models.DateField()
    empty_sent = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    full_received = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    invoice_number = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_date', '-created_at']
        db_table = 'factory_fill_transactions'

    def __str__(self):
        return f"{self.factory.name} - {self.product.name} - {self.transaction_date}"