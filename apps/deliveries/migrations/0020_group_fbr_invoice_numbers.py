import re

from django.db import migrations


def category_for_product(product_name):
    name = (product_name or '').upper()
    if 'CO2' in name or 'CARBON DIOXIDE' in name:
        return 'CO2'
    if 'LPG' in name:
        return 'LPG'
    if any(term in name for term in (
        'OXYGEN', 'NITROGEN', 'N2', 'DA', 'SPECIAL ARGON', 'ARGON', 'O2',
    )):
        return 'OXYGEN LIQUID'
    if any(term in name for term in (
        'VACUUM', 'PUMP', 'SERVICE', 'RENTAL', 'REPAIR', 'EQUIPMENT', 'FITTING',
    )):
        return None
    return 'OXYGEN LIQUID'


def normalize_grouped_invoice_numbers(apps, schema_editor):
    Delivery = apps.get_model('deliveries', 'Delivery')
    DeliveryInvoiceSequence = apps.get_model('deliveries', 'DeliveryInvoiceSequence')
    database = schema_editor.connection.alias
    sequence, _ = DeliveryInvoiceSequence.objects.using(database).get_or_create(pk=1)

    deliveries = list(
        Delivery.objects.using(database)
        .select_related('product')
        .order_by('delivery_date', 'created_at', 'pk')
    )
    groups = {}
    for delivery in deliveries:
        category = category_for_product(delivery.product.name if delivery.product_id else '')
        key = (
            delivery.customer_id,
            delivery.delivery_date,
            category if category else f'non-fbr-{delivery.pk}',
        )
        groups.setdefault(key, []).append(delivery)

    used_numbers = set()
    suffixes = [
        int(match.group(1))
        for delivery in deliveries
        if delivery.fbr_invoice_no
        for match in [re.search(r'(\d+)$', delivery.fbr_invoice_no)]
        if match
    ]
    next_number = max([sequence.next_number, *(number + 1 for number in suffixes)])

    for group in groups.values():
        group_number = next(
            (
                delivery.fbr_invoice_no
                for delivery in group
                if delivery.fbr_invoice_no and delivery.fbr_invoice_no not in used_numbers
            ),
            None,
        )
        if group_number is None:
            group_number = str(next_number)
            next_number += 1
        used_numbers.add(group_number)
        Delivery.objects.using(database).filter(
            pk__in=[delivery.pk for delivery in group]
        ).update(fbr_invoice_no=group_number)

    sequence.next_number = next_number
    sequence.save(using=database, update_fields=['next_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('deliveries', '0019_delivery_fbr_invoice_no'),
    ]

    operations = [
        migrations.RunPython(
            normalize_grouped_invoice_numbers,
            migrations.RunPython.noop,
        ),
    ]
