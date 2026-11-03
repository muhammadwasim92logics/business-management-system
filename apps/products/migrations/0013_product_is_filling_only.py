from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0012_factoryfilltransaction_invoice_number'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_filling_only',
            field=models.BooleanField(default=False, help_text='Customer brings a cylinder only to be filled with gas; quantity is treated as gas weight in kg and no empty cylinder exchange is tracked.'),
        ),
    ]
