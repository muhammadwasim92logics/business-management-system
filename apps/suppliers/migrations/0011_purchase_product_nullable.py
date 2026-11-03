from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('suppliers', '0010_purchase_rate_without_tax'),
    ]

    operations = [
        migrations.AlterField(
            model_name='purchase',
            name='product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name='purchases',
                to='products.product',
            ),
        ),
    ]