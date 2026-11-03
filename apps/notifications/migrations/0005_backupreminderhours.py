from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0004_notificationtiminghours'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationsettings',
            name='backup_reminder_after_hours',
            field=models.PositiveIntegerField(default=24, validators=[MinValueValidator(1)]),
        ),
    ]