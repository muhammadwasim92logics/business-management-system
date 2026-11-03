from django.db import migrations, models


def copy_existing_invoice_numbers(apps, schema_editor):
    Delivery = apps.get_model('deliveries', 'Delivery')
    for delivery in Delivery.objects.exclude(invoice_no__isnull=True).exclude(invoice_no='').iterator():
        delivery.fbr_invoice_no = delivery.invoice_no
        delivery.save(update_fields=['fbr_invoice_no'])


class Migration(migrations.Migration):

    dependencies = [
        ('deliveries', '0018_allow_duplicate_delivery_invoice_numbers'),
    ]

    operations = [
        migrations.AddField(
            model_name='delivery',
            name='fbr_invoice_no',
            field=models.CharField(
                blank=True,
                help_text='Invoice number assigned by the FBR invoicing sequence',
                max_length=50,
                null=True,
            ),
        ),
        migrations.RunPython(copy_existing_invoice_numbers, migrations.RunPython.noop),
    ]
