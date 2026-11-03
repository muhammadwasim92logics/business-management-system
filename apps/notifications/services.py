from django.utils import timezone
from datetime import timedelta
from django.db.models import Q, Sum
from django.db import models
from apps.customers.models import Customer
from apps.products.models import Product
from apps.deliveries.models import Delivery
from apps.payments.models import Payment
from .backup_service import BackupService
from .models import Notification, NotificationSettings

class NotificationService:

    @staticmethod
    def _settings():
        return NotificationSettings.get_solo()

    @staticmethod
    def _oldest_payment_date(customer, today):
        payments = float(customer.payments.aggregate(total=Sum('amount'))['total'] or 0)
        if customer.bf_balance or customer.previous_balance:
            opening_balance = float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
            if payments < opening_balance:
                return customer.bf_date or customer.registration_date or today
            payments -= opening_balance

        for delivery in customer.deliveries.order_by('delivery_date', 'created_at'):
            amount = float(delivery.delivery_amount or 0)
            if payments < amount:
                return delivery.delivery_date
            payments -= amount
        return today

    @staticmethod
    def _oldest_cylinder_date(customer, today):
        dates = []
        if any(value > 0 for value in (customer.bf_cylinders or {}).values()):
            dates.append(customer.bf_date or customer.registration_date or today)
        for delivery in customer.deliveries.select_related('product').all():
            if delivery.product and delivery.product.is_quantity_only:
                continue
            if delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0) > 0:
                dates.append(delivery.delivery_date)
        return min(dates) if dates else today
    
    @staticmethod
    def check_inactive_customers():
        """
        Check for customers inactive for 7+ days.
        Categorizes them and includes payment and cylinder details.
        """
        today = timezone.now().date()
        settings = NotificationService._settings()
        
        notifications_created = []
        
        for customer in Customer.objects.all():
            # Skip walk-in customers
            if customer.is_walkin:
                continue
                
            last_activity = customer.last_activity_date or customer.registration_date or today
            days_inactive = (today - last_activity).days
            
            # Only check if inactive for 7+ days
            inactive_hours = days_inactive * 24
            if inactive_hours >= settings.inactive_customer_after_hours:
                # Check if there's already an UNREAD notification for this customer today
                existing_unread = Notification.objects.filter(
                    type=Notification.Type.INACTIVE_CUSTOMER,
                    customer=customer,
                    status=Notification.Status.UNREAD,
                    created_at__date=today
                ).exists()
                
                # Check if there's already a READ notification for today
                existing_read_today = Notification.objects.filter(
                    type=Notification.Type.INACTIVE_CUSTOMER,
                    customer=customer,
                    status=Notification.Status.READ,
                    created_at__date=today
                ).exists()
                
                # Only create if no unread today AND no read today
                if not existing_unread and not existing_read_today:
                    # ============================================================
                    # CALCULATE PENDING PAYMENT
                    # ============================================================
                    total_billed = customer.deliveries.aggregate(total=Sum('delivery_amount'))['total'] or 0
                    total_paid = customer.payments.aggregate(total=Sum('amount'))['total'] or 0
                    pending_amount = float(total_billed) - float(total_paid) + float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
                    
                    # ============================================================
                    # GET CYLINDER BALANCE PER PRODUCT
                    # ============================================================
                    cylinder_details = []
                    cylinder_breakdown = customer.get_cylinder_balance()
                    
                    if cylinder_breakdown:
                        for product_name, balance in cylinder_breakdown.items():
                            if balance > 0:
                                cylinder_details.append(f"{product_name}: {balance}")
                    
                    # ============================================================
                    # DETERMINE STATUS LABEL
                    # ============================================================
                    if inactive_hours >= settings.not_coming_customer_after_hours:
                        status_label = "🔴 NOT COMING"
                        status_emoji = "🔴"
                    else:
                        status_label = "🟡 INACTIVE"
                        status_emoji = "🟡"
                    
                    # ============================================================
                    # BUILD MESSAGE
                    # ============================================================
                    message_parts = [
                        f"{status_emoji} {status_label} - No activity for {days_inactive} days."
                    ]
                    
                    if pending_amount > 0:
                        message_parts.append(f"💰 Pending payment: PKR {pending_amount:,.2f}")
                    else:
                        message_parts.append("✅ No pending payment")
                    
                    if cylinder_details:
                        message_parts.append(f"📦 Cylinders to return: {', '.join(cylinder_details)}")
                    else:
                        message_parts.append("📦 No cylinders currently with customer")
                    
                    # Add last activity date
                    if last_activity:
                        message_parts.append(f"📅 Last activity: {last_activity.strftime('%d %b %Y')}")
                    
                    message = " | ".join(message_parts)
                    
                    # ============================================================
                    # CREATE TITLE
                    # ============================================================
                    title = f"{status_label}: {customer.name} - {days_inactive} days inactive"
                    
                    notification = Notification.objects.create(
                        type=Notification.Type.INACTIVE_CUSTOMER,
                        title=title,
                        message=message,
                        customer=customer,
                        link=f"/customers/ledger/?customer_id={customer.pk}"
                    )
                    notifications_created.append(notification)
        
        return notifications_created
    
    @staticmethod
    def check_low_stock():
        """Check for products with low stock"""
        today = timezone.now().date()
        
        notifications_created = []
        
        for product in Product.objects.filter(stock_quantity__lte=models.F('minimum_stock')):
            # Check if there's already an UNREAD notification today
            existing_unread = Notification.objects.filter(
                type=Notification.Type.LOW_STOCK,
                product=product,
                status=Notification.Status.UNREAD,
                created_at__date=today
            ).exists()
            
            # Check if there's already a READ notification today
            existing_read_today = Notification.objects.filter(
                type=Notification.Type.LOW_STOCK,
                product=product,
                status=Notification.Status.READ,
                created_at__date=today
            ).exists()
            
            if not existing_unread and not existing_read_today:
                # Determine urgency
                if product.stock_quantity <= 0:
                    urgency = "⚠️ CRITICAL"
                    bg_color = "bg-danger"
                else:
                    urgency = "⚠️ LOW STOCK"
                    bg_color = "bg-warning"
                
                notification = Notification.objects.create(
                    type=Notification.Type.LOW_STOCK,
                    title=f"{urgency}: {product.name}",
                    message=f"Current stock: {product.stock_quantity} units. Minimum required: {product.minimum_stock}. Please restock immediately.",
                    product=product,
                    link=f"/products/{product.pk}/edit/"
                )
                notifications_created.append(notification)
        
        return notifications_created
    
    @staticmethod
    def check_pending_payments():
        """
        Check for customers with pending payments.
        Only for active customers (activity within last 7 days).
        """
        today = timezone.now().date()
        settings = NotificationService._settings()
        
        notifications_created = []
        
        for customer in Customer.objects.all():
            # Skip walk-in customers
            if customer.is_walkin:
                continue
                
            total_billed = customer.deliveries.aggregate(total=Sum('delivery_amount'))['total'] or 0
            total_paid = customer.payments.aggregate(total=Sum('amount'))['total'] or 0
            pending = float(total_billed) - float(total_paid) + float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
            payment_age = (today - NotificationService._oldest_payment_date(customer, today)).days
            payment_age_hours = payment_age * 24
            
            if pending > settings.pending_payment_minimum and payment_age_hours >= settings.pending_payment_after_hours:
                # Check if there's already an UNREAD notification today
                existing_unread = Notification.objects.filter(
                    type=Notification.Type.PENDING_PAYMENT,
                    customer=customer,
                    status=Notification.Status.UNREAD,
                    created_at__date=today
                ).exists()
                
                # Check if there's already a READ notification today
                existing_read_today = Notification.objects.filter(
                    type=Notification.Type.PENDING_PAYMENT,
                    customer=customer,
                    status=Notification.Status.READ,
                    created_at__date=today
                ).exists()
                
                if not existing_unread and not existing_read_today:
                    # ============================================================
                    # GET CYLINDER BALANCE
                    # ============================================================
                    cylinder_details = []
                    cylinder_breakdown = customer.get_cylinder_balance()
                    
                    if cylinder_breakdown:
                        for product_name, balance in cylinder_breakdown.items():
                            if balance > 0:
                                cylinder_details.append(f"{product_name}: {balance}")
                    
                    # ============================================================
                    # BUILD MESSAGE
                    # ============================================================
                    message_parts = [
                        f"💰 Outstanding for {payment_age} days",
                        f"💰 Pending payment: PKR {pending:,.2f}"
                    ]
                    
                    if cylinder_details:
                        message_parts.append(f"📦 Cylinders with customer: {', '.join(cylinder_details)}")
                    else:
                        message_parts.append("📦 No cylinders with customer")
                    
                    last_activity = customer.last_activity_date or customer.registration_date or today
                    message_parts.append(f"📅 Last activity: {last_activity.strftime('%d %b %Y')}")
                    
                    message = " | ".join(message_parts)
                    
                    notification = Notification.objects.create(
                        type=Notification.Type.PENDING_PAYMENT,
                        title=f"💰 Pending Payment: {customer.name}",
                        message=message,
                        customer=customer,
                        link=f"/customers/ledger/?customer_id={customer.pk}"
                    )
                    notifications_created.append(notification)
        
        return notifications_created
    
    @staticmethod
    def check_cylinder_due():
        """Check for customers with cylinders due (10+ cylinders)"""
        today = timezone.now().date()
        settings = NotificationService._settings()
        
        notifications_created = []
        
        for customer in Customer.objects.all():
            # Skip walk-in customers
            if customer.is_walkin:
                continue
                
            # Get cylinder balance with breakdown
            cylinder_breakdown = customer.get_cylinder_balance()
            total_cylinders = sum(cylinder_breakdown.values())
            
            cylinder_age = (today - NotificationService._oldest_cylinder_date(customer, today)).days
            cylinder_age_hours = cylinder_age * 24
            if total_cylinders >= settings.cylinder_due_minimum and cylinder_age_hours >= settings.cylinder_due_after_hours:
                # Check if there's already an UNREAD notification today
                existing_unread = Notification.objects.filter(
                    type=Notification.Type.CYLINDER_DUE,
                    customer=customer,
                    status=Notification.Status.UNREAD,
                    created_at__date=today
                ).exists()
                
                # Check if there's already a READ notification today
                existing_read_today = Notification.objects.filter(
                    type=Notification.Type.CYLINDER_DUE,
                    customer=customer,
                    status=Notification.Status.READ,
                    created_at__date=today
                ).exists()
                
                if not existing_unread and not existing_read_today:
                    # Build cylinder details
                    cylinder_details = []
                    for product_name, balance in cylinder_breakdown.items():
                        if balance > 0:
                            cylinder_details.append(f"{product_name}: {balance}")
                    
                    # Get pending payment
                    total_billed = customer.deliveries.aggregate(total=Sum('delivery_amount'))['total'] or 0
                    total_paid = customer.payments.aggregate(total=Sum('amount'))['total'] or 0
                    pending_amount = float(total_billed) - float(total_paid) + float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
                    
                    # Build message
                    message_parts = [
                        f"📦 {total_cylinders} cylinders with customer for {cylinder_age} days"
                    ]
                    
                    if cylinder_details:
                        message_parts.append(f"Breakdown: {', '.join(cylinder_details)}")
                    
                    if pending_amount > 0:
                        message_parts.append(f"💰 Pending: PKR {pending_amount:,.2f}")
                    
                    last_activity = customer.last_activity_date or customer.registration_date or today
                    days_inactive = (today - last_activity).days
                    if days_inactive > 0:
                        message_parts.append(f"📅 {days_inactive} days since last activity")
                    
                    message = " | ".join(message_parts)
                    
                    notification = Notification.objects.create(
                        type=Notification.Type.CYLINDER_DUE,
                        title=f"📦 Cylinders Due: {customer.name} ({total_cylinders} cylinders)",
                        message=message,
                        customer=customer,
                        link=f"/customers/ledger/?customer_id={customer.pk}"
                    )
                    notifications_created.append(notification)
        
        return notifications_created
    
    @staticmethod
    def check_weekly_reminder():
        """
        Weekly summary notification for all customers with pending payments or cylinders.
        Runs on Mondays only.
        """
        today = timezone.now().date()
        
        # Only run on Mondays (weekday = 0)
        if today.weekday() != 0 or not NotificationService._settings().weekly_reminder_enabled:
            return []
        
        notifications_created = []
        
        # Get all customers with pending payments or cylinders
        customers_with_issues = []
        
        for customer in Customer.objects.all():
            # Skip walk-in customers
            if customer.is_walkin:
                continue
                
            total_billed = customer.deliveries.aggregate(total=Sum('delivery_amount'))['total'] or 0
            total_paid = customer.payments.aggregate(total=Sum('amount'))['total'] or 0
            pending = float(total_billed) - float(total_paid) + float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
            
            cylinders = customer.get_cylinder_balance()
            total_cylinders = sum(cylinders.values())
            
            if pending > 0 or total_cylinders > 0:
                customers_with_issues.append({
                    'customer': customer,
                    'pending': pending,
                    'cylinders': cylinders,
                    'total_cylinders': total_cylinders,
                })
        
        if customers_with_issues:
            # Create a summary notification
            summary_lines = []
            for item in customers_with_issues[:10]:  # Limit to 10 customers
                name = item['customer'].name
                parts = []
                if item['pending'] > 0:
                    parts.append(f"PKR {item['pending']:,.2f}")
                if item['total_cylinders'] > 0:
                    parts.append(f"{item['total_cylinders']} cylinders")
                summary_lines.append(f"• {name}: {', '.join(parts)}")
            
            if len(customers_with_issues) > 10:
                summary_lines.append(f"• ... and {len(customers_with_issues) - 10} more customers")
            
            summary = "\n".join(summary_lines)
            
            notification = Notification.objects.create(
                type=Notification.Type.WEEKLY_REMINDER,
                title=f"📊 Weekly Summary - {today.strftime('%d %b %Y')}",
                message=f"Customers with pending payments or cylinders:\n\n{summary}\n\nPlease follow up with these customers.",
                link="/customers/"
            )
            notifications_created.append(notification)
        
        return notifications_created
    
    @staticmethod
    def run_daily_checks():
        """Run all daily notification checks"""
        notifications = []
        notifications.extend(NotificationService.check_inactive_customers())
        notifications.extend(NotificationService.check_low_stock())
        notifications.extend(NotificationService.check_pending_payments())
        notifications.extend(NotificationService.check_cylinder_due())
        notifications.extend(NotificationService.check_backup_reminder())

        # Weekly summary (only on Mondays)
        notifications.extend(NotificationService.check_weekly_reminder())

        return notifications

    @staticmethod
    def check_backup_reminder():
        """Create a backup reminder if no daily backup has been sent recently."""
        created = BackupService.create_backup_reminder_if_missing()
        return [] if not created else [
            Notification.objects.filter(
                type=Notification.Type.BACKUP_REMINDER,
                status=Notification.Status.UNREAD,
                created_at__date=timezone.now().date()
            ).order_by('-created_at').first()
        ]
