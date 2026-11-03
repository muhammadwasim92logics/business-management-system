from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('earnings', '0002_openingbalance'),
    ]

    operations = [
        migrations.CreateModel(
            name='PartnerAccountBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('partner_name', models.CharField(max_length=200)),
                ('bank_name', models.CharField(max_length=200)),
                ('account_amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('description', models.TextField(blank=True)),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date', 'partner_name', 'bank_name', '-created_at'],
            },
        ),
    ]
