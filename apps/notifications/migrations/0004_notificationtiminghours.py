from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0003_notificationsettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationsettings',
            name='pending_payment_after_hours',
            field=models.PositiveIntegerField(default=168, validators=[MinValueValidator(1)]),
        ),
        migrations.AddField(
            model_name='notificationsettings',
            name='cylinder_due_after_hours',
            field=models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='notificationsettings',
            name='inactive_customer_after_hours',
            field=models.PositiveIntegerField(default=168, validators=[MinValueValidator(1)]),
        ),
        migrations.AddField(
            model_name='notificationsettings',
            name='not_coming_customer_after_hours',
            field=models.PositiveIntegerField(default=720, validators=[MinValueValidator(1)]),
        ),
    ]