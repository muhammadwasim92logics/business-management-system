import re

from django.db import transaction
from django.db.models.signals import pre_save
from django.dispatch import receiver

from apps.deliveries.models import Delivery, DeliveryInvoiceSequence
from apps.fbr.invoice_numbers import get_fbr_category


def _numeric_suffix(value):
    match = re.search(r'(\d+)$', value or '')
    return int(match.group(1)) if match else None


@receiver(pre_save, sender=Delivery)
def auto_assign_invoice_number(sender, instance, **kwargs):
    if not instance._state.adding:
        return

    with transaction.atomic():
        sequence = DeliveryInvoiceSequence.objects.select_for_update().get(pk=1)
        category = get_fbr_category(instance.product.name if instance.product_id else '')
        if category:
            existing_group = Delivery.objects.filter(
                customer_id=instance.customer_id,
                delivery_date=instance.delivery_date,
                product__isnull=False,
                fbr_invoice_no__isnull=False,
            ).exclude(fbr_invoice_no='').order_by('created_at', 'pk')
            for existing in existing_group.select_related('product'):
                if get_fbr_category(existing.product.name) == category:
                    instance.fbr_invoice_no = existing.fbr_invoice_no
                    return

        existing_numbers = Delivery.objects.exclude(
            fbr_invoice_no__isnull=True
        ).exclude(fbr_invoice_no='').values_list('fbr_invoice_no', flat=True)
        next_number = sequence.next_number
        for value in existing_numbers:
            number = _numeric_suffix(value)
            if number is not None:
                next_number = max(next_number, number + 1)

        if instance.fbr_invoice_no:
            assigned_number = _numeric_suffix(instance.fbr_invoice_no)
            if assigned_number is not None:
                next_number = max(next_number, assigned_number + 1)
        else:
            instance.fbr_invoice_no = str(next_number)
            next_number += 1

        sequence.next_number = next_number
        sequence.save(update_fields=['next_number'])
