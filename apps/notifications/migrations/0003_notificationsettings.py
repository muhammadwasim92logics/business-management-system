from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0002_alter_notification_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pending_payment_days', models.PositiveIntegerField(default=7, validators=[MinValueValidator(1)])),
                ('pending_payment_minimum', models.DecimalField(decimal_places=2, default=1000, max_digits=12, validators=[MinValueValidator(0)])),
                ('cylinder_due_days', models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])),
                ('cylinder_due_minimum', models.PositiveIntegerField(default=10, validators=[MinValueValidator(1)])),
                ('inactive_customer_days', models.PositiveIntegerField(default=7, validators=[MinValueValidator(1)])),
                ('not_coming_customer_days', models.PositiveIntegerField(default=30, validators=[MinValueValidator(1)])),
                ('weekly_reminder_enabled', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'notification_settings'},
        ),
    ]