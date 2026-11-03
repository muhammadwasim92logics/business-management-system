from django.db import migrations


def replace_reconciled_delivery_payments(apps, schema_editor):
    Delivery = apps.get_model('deliveries', 'Delivery')
    Payment = apps.get_model('payments', 'Payment')
    database = schema_editor.connection.alias

    payments = Payment.objects.using(database).filter(
        delivery__isnull=True,
        notes__startswith='Payment for ',
    ).order_by('created_at', 'id')

    for payment in payments.iterator():
        if '(Invoice:' not in (payment.notes or ''):
            continue
        invoice_no = payment.notes.rsplit('(Invoice:', 1)[-1].rstrip(') ').strip()
        if not invoice_no or invoice_no == 'N/A':
            continue

        candidates = Delivery.objects.using(database).filter(
            customer_id=payment.customer_id,
            invoice_no=invoice_no,
            payment_amount=payment.amount,
        )
        if candidates.count() != 1:
            continue

        delivery = candidates.first()
        synthetic = Payment.objects.using(database).filter(
            delivery_id=delivery.pk,
            payment_no__startswith='PAY-BF-',
            amount=payment.amount,
        ).first()

        if synthetic is None:
            if Payment.objects.using(database).filter(delivery_id=delivery.pk).exists():
                continue
        else:
            synthetic.delete()

        payment.delivery_id = delivery.pk
        payment.invoice_no = invoice_no
        payment.save(update_fields=['delivery', 'invoice_no'])


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0004_link_invoice_delivery_payments'),
        ('deliveries', '0016_decimal_quantity'),
    ]

    operations = [
        migrations.RunPython(replace_reconciled_delivery_payments, migrations.RunPython.noop),
    ]