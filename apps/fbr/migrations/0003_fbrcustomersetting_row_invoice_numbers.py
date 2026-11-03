from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fbr', '0002_fbrcustomersetting'),
    ]

    operations = [
        migrations.AddField(
            model_name='fbrcustomersetting',
            name='row_invoice_numbers',
            field=models.JSONField(blank=True, default=dict, help_text='Per-row invoice number overrides keyed by row identifier'),
        ),
        migrations.AlterField(
            model_name='fbrcustomersetting',
            name='invoice_number',
            field=models.CharField(blank=True, help_text='Starting invoice number for this customer', max_length=50, null=True),
        ),
    ]
