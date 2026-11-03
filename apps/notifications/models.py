from django.db import models
from django.conf import settings
import uuid
from django.core.validators import MinValueValidator


class Notification(models.Model):
    class Type(models.TextChoices):
        INACTIVE_CUSTOMER = 'inactive_customer', 'Inactive Customer'
        LOW_STOCK = 'low_stock', 'Low Stock'
        PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
        CYLINDER_DUE = 'cylinder_due', 'Cylinder Due'
        WEEKLY_REMINDER = 'weekly_reminder', 'Weekly Reminder'
        BACKUP_REMINDER = 'backup_reminder', 'Backup Reminder'
        BACKUP_SENT = 'backup_sent', 'Backup Sent'
    
    class Status(models.TextChoices):
        UNREAD = 'unread', 'Unread'
        READ = 'read', 'Read'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=50, choices=Type.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNREAD)
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True)
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True)
    link = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        db_table = 'notifications'
    
    def __str__(self):
        return f"{self.get_type_display()}: {self.title}"
    
    def mark_as_read(self):
        self.status = self.Status.READ
        self.save(update_fields=['status', 'updated_at'])
    
    @classmethod
    def mark_all_as_read(cls):
        cls.objects.filter(status=cls.Status.UNREAD).update(
            status=cls.Status.READ
        )


class NotificationSettings(models.Model):
    pending_payment_days = models.PositiveIntegerField(default=7, validators=[MinValueValidator(1)])
    pending_payment_minimum = models.DecimalField(max_digits=12, decimal_places=2, default=1000, validators=[MinValueValidator(0)])
    cylinder_due_days = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    cylinder_due_minimum = models.PositiveIntegerField(default=10, validators=[MinValueValidator(1)])
    inactive_customer_days = models.PositiveIntegerField(default=7, validators=[MinValueValidator(1)])
    not_coming_customer_days = models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)])
    pending_payment_after_hours = models.PositiveIntegerField(default=168, validators=[MinValueValidator(1)])
    cylinder_due_after_hours = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    inactive_customer_after_hours = models.PositiveIntegerField(default=168, validators=[MinValueValidator(1)])
    not_coming_customer_after_hours = models.PositiveIntegerField(default=720, validators=[MinValueValidator(1)])
    backup_reminder_after_hours = models.PositiveIntegerField(default=24, validators=[MinValueValidator(1)])
    weekly_reminder_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings