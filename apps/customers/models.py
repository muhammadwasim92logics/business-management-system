from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid
import re


def generate_customer_code():
    """Generate a unique customer code"""
    last = Customer.objects.exclude(customer_code__isnull=True).exclude(customer_code='').order_by('-created_at').first()
    if last and last.customer_code:
        try:
            match = re.search(r'CUST-(\d+)', last.customer_code)
            if match:
                num = int(match.group(1)) + 1
            else:
                num = 1
        except (IndexError, ValueError, AttributeError):
            num = 1
    else:
        num = 1
    return f'CUST-{num:04d}'


class Customer(models.Model):
    @classmethod
    def get_or_create_walkin(cls, name=None, mobile=None, security_deposit=0, personal_cylinders=0, last_activity_date=None):
        """
        Reuse a single walk-in customer object when the same walk-in identity
        is supplied again, while still creating a brand-new walk-in row only
        when no matching walk-in customer exists.
        """
        normalized_name = (name or 'Walk-in Customer').strip() or 'Walk-in Customer'
        normalized_mobile = (mobile or '').strip()
        if normalized_mobile == 'N/A':
            normalized_mobile = ''

        queryset = cls.objects.filter(is_walkin=True)
        if normalized_mobile:
            queryset = queryset.filter(mobile__iexact=normalized_mobile)
        if normalized_name:
            queryset = queryset.filter(name__iexact=normalized_name)

        customer = queryset.order_by('-updated_at').first()
        if customer:
            updated = False
            if customer.name != normalized_name:
                customer.name = normalized_name
                updated = True
            if customer.mobile != normalized_mobile:
                customer.mobile = normalized_mobile
                updated = True
            if customer.security_deposit != security_deposit:
                customer.security_deposit = security_deposit
                updated = True
            if customer.personal_cylinders != personal_cylinders:
                customer.personal_cylinders = personal_cylinders
                updated = True
            if last_activity_date and customer.last_activity_date != last_activity_date:
                customer.last_activity_date = last_activity_date
                updated = True
            if updated:
                customer.save(update_fields=['name', 'mobile', 'security_deposit', 'personal_cylinders', 'last_activity_date', 'updated_at'])
            return customer

        customer = cls.objects.create(
            name=normalized_name,
            mobile=normalized_mobile,
            security_deposit=security_deposit,
            personal_cylinders=personal_cylinders,
            is_walkin=True,
            last_activity_date=last_activity_date,
        )
        return customer

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    name = models.CharField(max_length=200, blank=True, null=True)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    alternate_mobile = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    area = models.CharField(max_length=100, blank=True, null=True)
    stn = models.CharField(max_length=50, blank=True, null=True, help_text="Sales Tax Number")
    ntn = models.CharField(max_length=50, blank=True, null=True, help_text="National Tax Number")
    registration_date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    previous_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_activity_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Security and Personal Cylinders
    security_deposit = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0, 
        blank=True, 
        null=True,
        help_text="Security deposit amount from customer"
    )
    personal_cylinders = models.PositiveIntegerField(
        default=0, 
        blank=True, 
        null=True,
        help_text="Number of cylinders customer already owns"
    )
    
    # B.F (Bring Forward) Fields
    bf_balance = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0,
        help_text="Bring Forward balance (opening balance)"
    )
    bf_cylinders = models.JSONField(
        default=dict,
        blank=True,
        help_text="Bring Forward cylinders per product {product_name: quantity}"
    )
    bf_description = models.TextField(
        blank=True,
        default='',
        help_text="Description for the Bring Forward ledger entry"
    )
    bf_date = models.DateField(
        default=timezone.localdate,
        help_text="Date of the Bring Forward opening balance"
    )
    
    # Flag to identify walk-in customers
    is_walkin = models.BooleanField(default=False, help_text="Is this a walk-in customer?")
    
    class Meta:
        ordering = ['name']
        db_table = 'customers'
    
    def __str__(self):
        if self.is_walkin:
            return f"{self.customer_code} - Walk-in Customer"
        return f"{self.customer_code} - {self.name or 'Unnamed'}"
    
    def save(self, *args, **kwargs):
        import uuid
        from datetime import datetime
        
        # ============================================================
        # FIX: Handle existing customers with empty customer_code
        # ============================================================
        if self.pk and not self.customer_code:
            try:
                existing = Customer.objects.get(pk=self.pk)
                if existing.customer_code:
                    self.customer_code = existing.customer_code
                else:
                    # Force regeneration
                    self.customer_code = None
            except Customer.DoesNotExist:
                pass
        
        # Generate customer code if not provided
        if not self.customer_code:
            # Get the latest customer with a valid code
            last_customer = Customer.objects.exclude(
                customer_code__isnull=True
            ).exclude(
                customer_code=''
            ).order_by('-created_at').first()
            
            if last_customer and last_customer.customer_code:
                try:
                    match = re.search(r'CUST-(\d+)', last_customer.customer_code)
                    if match:
                        last_num = int(match.group(1))
                        new_num = last_num + 1
                        self.customer_code = f"CUST-{new_num:04d}"
                    else:
                        self.customer_code = "CUST-0001"
                except (ValueError, AttributeError):
                    self.customer_code = "CUST-0001"
            else:
                self.customer_code = "CUST-0001"
            
            # Ensure the generated code is unique
            counter = 0
            while Customer.objects.filter(customer_code=self.customer_code).exists() and counter < 100:
                # Get all existing codes
                existing_codes = list(
                    Customer.objects.exclude(
                        customer_code__isnull=True
                    ).exclude(
                        customer_code=''
                    ).values_list('customer_code', flat=True)
                )
                # Find the next available number
                num = 1
                while f"CUST-{num:04d}" in existing_codes:
                    num += 1
                self.customer_code = f"CUST-{num:04d}"
                counter += 1
            
            # Fallback to UUID if still not unique (safety net)
            if Customer.objects.filter(customer_code=self.customer_code).exists():
                self.customer_code = f"CUST-{uuid.uuid4().hex[:8].upper()}"
        
        super().save(*args, **kwargs)
    
    def get_status(self):
        today = timezone.now().date()
        last_activity = self.last_activity_date or self.registration_date or today
        days_inactive = (today - last_activity).days
        
        if days_inactive >= 30:
            return 'not_coming', f'Not coming for {days_inactive} days'
        elif days_inactive >= 7:
            return 'inactive', f'Inactive for {days_inactive} days'
        else:
            return 'active', f'Active (last activity {days_inactive} days ago)'
    
    def get_status_class(self):
        status, _ = self.get_status()
        return {
            'active': 'bg-success',
            'inactive': 'bg-warning text-dark',
            'not_coming': 'bg-danger'
        }.get(status, 'bg-secondary')
    
    def get_status_display(self):
        status, _ = self.get_status()
        return {
            'active': '🟢 Active',
            'inactive': '🟡 Inactive',
            'not_coming': '🔴 Not Coming'
        }.get(status, status)
    
    def get_total_deliveries(self):
        return self.deliveries.count()
    
    def get_total_cylinders_taken(self):
        return self.deliveries.filter(product__is_quantity_only=False).aggregate(total=models.Sum('quantity'))['total'] or 0
    
    def get_total_cylinders_returned(self):
        normal_returns = self.deliveries.filter(
            product__is_quantity_only=False,
            cylinder_movement_type='',
        ).aggregate(total=models.Sum('empty_returned'))['total'] or 0
        ownership_returns = self.cylinder_entries.filter(
            ownership_movement='customer_received',
        ).aggregate(total=models.Sum('ownership_quantity'))['total'] or 0
        return normal_returns + ownership_returns
    
    def get_net_cylinders(self):
        return sum(self.get_cylinder_balance().values())
    
    def get_total_amount(self):
        return self.deliveries.aggregate(total=models.Sum('delivery_amount'))['total'] or 0
    
    def get_total_payments(self):
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or 0
    
    def get_outstanding_balance(self):
        total_billed = self.get_total_amount()
        total_paid = self.get_total_payments()
        bf_balance = float(self.bf_balance or 0)
        prev_balance = float(self.previous_balance or 0)
        return float(total_billed) - float(total_paid) + bf_balance + prev_balance

    def get_cylinder_balance(self):
        """Returns dictionary of product name to net cylinder quantity"""
        cylinders = {}

        def balance_key(product_name):
            return next(
                (existing for existing in cylinders if existing.casefold() == product_name.casefold()),
                product_name,
            )

        # Start with B.F cylinders
        bf_cyl = self.bf_cylinders or {}
        for product_name, quantity in bf_cyl.items():
            if quantity != 0:
                cylinders[product_name] = int(quantity)
        
        # Add deliveries logic (ignore Sale-Only products)
        for delivery in self.deliveries.all():
            if delivery.product and delivery.product.is_quantity_only:
                continue
            product_name = delivery.product.name if delivery.product else 'Unknown'
            product_name = balance_key(product_name)
            net = delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0)
            if product_name not in cylinders:
                cylinders[product_name] = 0
            cylinders[product_name] += net

        from apps.cylinders.models import CylinderLedger
        for entry in CylinderLedger.objects.filter(
            customer_id=self.pk,
            ownership_movement__in=('customer_received', 'customer_returned')
        ):
            product_name = entry.product.name if entry.product else 'Unknown'
            product_name = balance_key(product_name)
            movement = entry.ownership_quantity
            if entry.ownership_movement == 'customer_received':
                movement = -movement
            cylinders[product_name] = cylinders.get(product_name, 0) + movement
            
        return cylinders

    def get_balance_before_date(self, target_date):
        """Calculate the total outstanding financial balance up to exclusively this date"""
        total_billed = self.deliveries.filter(delivery_date__lt=target_date).aggregate(total=models.Sum('delivery_amount'))['total'] or 0
        total_paid = self.payments.filter(payment_date__lt=target_date).aggregate(total=models.Sum('amount'))['total'] or 0
        bf_balance = float(self.bf_balance or 0)
        prev_balance = float(self.previous_balance or 0)
        return float(total_billed) - float(total_paid) + bf_balance + prev_balance
        
    def get_cylinders_before_date(self, target_date):
        """Calculate the total cylinder inventory break down up to exclusively this date"""
        cylinders = {}

        def balance_key(product_name):
            return next(
                (existing for existing in cylinders if existing.casefold() == product_name.casefold()),
                product_name,
            )

        bf_cyl = self.bf_cylinders or {}
        for product_name, quantity in bf_cyl.items():
            if quantity != 0:
                cylinders[product_name] = int(quantity)
        
        for delivery in self.deliveries.filter(delivery_date__lt=target_date):
            if delivery.product and delivery.product.is_quantity_only:
                continue
            product_name = delivery.product.name if delivery.product else 'Unknown'
            product_name = balance_key(product_name)
            net = delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0)
            if product_name not in cylinders:
                cylinders[product_name] = 0
            cylinders[product_name] += net

        from apps.cylinders.models import CylinderLedger
        for entry in CylinderLedger.objects.filter(
            customer_id=self.pk,
            ownership_movement__in=('customer_received', 'customer_returned'),
            delivery__delivery_date__lt=target_date,
        ):
            product_name = entry.product.name if entry.product else 'Unknown'
            product_name = balance_key(product_name)
            movement = entry.ownership_quantity
            if entry.ownership_movement == 'customer_received':
                movement = -movement
            cylinders[product_name] = cylinders.get(product_name, 0) + movement
            
        return cylinders