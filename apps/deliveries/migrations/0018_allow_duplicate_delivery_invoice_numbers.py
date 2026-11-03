from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deliveries', '0017_unique_delivery_invoice_numbers'),
    ]

    operations = [
        migrations.AlterField(
            model_name='delivery',
            name='invoice_no',
            field=models.CharField(
                blank=True,
                help_text='Optional invoice number; duplicate numbers are allowed',
                max_length=50,
                null=True,
            ),
        ),
    ]
