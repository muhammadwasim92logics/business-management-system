from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('products', '0014_alter_product_is_filling_only'),
    ]

    operations = [
        migrations.AlterField(
            model_name='factoryfilltransaction',
            name='empty_sent',
            field=models.PositiveIntegerField(validators=[MinValueValidator(0)]),
        ),
    ]