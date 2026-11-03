from datetime import date
import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.products.models import Product
from .models import Purchase, Supplier


class SupplierCreateViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='supplier-user',
            password='secret123',
        )
        self.client.force_login(user)

    def test_create_generates_unique_supplier_code(self):
        Supplier.objects.create(name='Existing Supplier', supplier_code='')

        response = self.client.post(reverse('suppliers:add'), {
            'name': 'New Supplier',
            'mobile': '03001234567',
            'address': 'Test address',
            'bf_balance': '125.50',
            'ntn': '',
            'stn': '',
            'notes': '',
        })

        self.assertRedirects(response, reverse('suppliers:list'))
        supplier = Supplier.objects.get(name='New Supplier')
        self.assertEqual(supplier.supplier_code, 'SUP-0002')
        self.assertEqual(str(supplier.bf_balance), '125.50')

    def test_supplier_level_payment_is_not_repeated_in_each_product_ledger(self):
        supplier = Supplier.objects.create(name='Multi Product Payment Supplier')
        products = [
            Product.objects.create(name=name, is_purchasable=True)
            for name in ('Ledger Product A', 'Ledger Product B')
        ]
        for product in products:
            Purchase.objects.create(
                supplier=supplier,
                product=product,
                purchase_date=date(2026, 9, 1),
                quantity=1,
                unit_price=100,
            )
        standalone_payment = Purchase.objects.create(
            supplier=supplier,
            product=None,
            purchase_date=date(2026, 9, 2),
            quantity=0,
            unit_price=0,
            paid_amount=5000,
            description='Payment Only',
        )

        response = self.client.get(reverse('suppliers:ledger'), {'supplier': str(supplier.pk)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['unallocated_payments']), 1)
        self.assertEqual(response.context['unallocated_payments'][0].pk, standalone_payment.pk)
        self.assertEqual(response.context['unallocated_payments_total'], 5000)
        for ledger in response.context['ledger_sets']:
            self.assertEqual(ledger['total_paid'], 0)
            self.assertFalse(any(
                entry['description'] == 'Payment Only'
                for entry in ledger['ledger_entries']
            ))

    def test_supplier_level_payments_show_previous_and_remaining_running_balances(self):
        supplier = Supplier.objects.create(
            name='Running Balance Supplier',
            bf_balance=100000,
        )
        payments = [
            Purchase.objects.create(
                supplier=supplier,
                product=None,
                purchase_date=date(2026, 9, day),
                quantity=0,
                unit_price=0,
                paid_amount=amount,
                description='Payment Only',
            )
            for day, amount in ((1, 50000), (2, 10000))
        ]

        response = self.client.get(reverse('suppliers:ledger'), {
            'supplier': str(supplier.pk),
        })

        rows = response.context['unallocated_payments']
        self.assertEqual([payment.pk for payment in rows], [payment.pk for payment in payments])
        self.assertEqual(
            [(payment.previous_balance, payment.paid_amount, payment.remaining_balance) for payment in rows],
            [(100000, 50000, 50000), (50000, 10000, 40000)],
        )

    def test_purchase_entry_shows_supplier_previous_balance_before_payment(self):
        supplier = Supplier.objects.create(
            name='Manage Balance Supplier',
            bf_balance=100000,
        )
        Purchase.objects.create(
            supplier=supplier,
            product=None,
            purchase_date=date(2026, 9, 1),
            quantity=0,
            unit_price=0,
            paid_amount=30000,
            description='Earlier Payment',
        )
        payment = Purchase.objects.create(
            supplier=supplier,
            product=None,
            purchase_date=date(2026, 9, 2),
            quantity=0,
            unit_price=0,
            paid_amount=20000,
            description='Payment Only',
        )

        response = self.client.get(reverse('suppliers:purchase_entry'), {
            'date': '2026-09-02',
        })

        activity = response.context['activities'][0]
        self.assertEqual(activity['id'], str(payment.pk))
        self.assertEqual(activity['old_balance'], 70000)
        self.assertEqual(activity['new_balance'], 50000)

    def test_supplier_ledger_filters_products_by_supplier(self):
        supplier = Supplier.objects.create(name='Alpha Gas', supplier_code='SUP-0001')
        other_supplier = Supplier.objects.create(name='Beta Gas', supplier_code='SUP-0002')

        product_from_supplier = Product.objects.create(
            name='Oxygen 10L',
            is_purchasable=True,
            is_sellable=True,
            stock_quantity=0,
        )
        product_from_other_supplier = Product.objects.create(
            name='Nitrogen 10L',
            is_purchasable=True,
            is_sellable=True,
            stock_quantity=0,
        )

        Purchase.objects.create(
            supplier=supplier,
            product=product_from_supplier,
            purchase_date=date(2026, 1, 1),
            quantity=10,
            unit_price=100,
            created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
        )
        Purchase.objects.create(
            supplier=supplier,
            product=product_from_supplier,
            purchase_date=date(2026, 1, 3),
            quantity=4,
            unit_price=100,
            created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
        )
        Purchase.objects.create(
            supplier=other_supplier,
            product=product_from_other_supplier,
            purchase_date=date(2026, 1, 2),
            quantity=5,
            unit_price=90,
            created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
        )

        response = self.client.get(reverse('suppliers:ledger'), {'supplier': str(supplier.id)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['products'].values_list('name', flat=True)), ['OXYGEN 10L'])
        self.assertEqual(response.context['selected_product_ids'], [str(product_from_supplier.pk)])
        self.assertEqual(len(response.context['ledger_sets']), 1)
        self.assertContains(response, 'OXYGEN 10L')
        self.assertNotContains(response, 'NITROGEN 10L')

    def test_supplier_ledger_renders_all_checked_products_and_supports_subset(self):
        supplier = Supplier.objects.create(name='Multi Product Supplier', supplier_code='SUP-0010')
        products = [
            Product.objects.create(
                name=name,
                product_code=f'SUP-MULTI-{index:02d}',
                is_purchasable=True,
                stock_quantity=0,
            )
            for index, name in enumerate(('OXYGEN 10L', 'LPG 12KG', 'CO2 25KG'), start=1)
        ]
        for index, product in enumerate(products, start=1):
            Purchase.objects.create(
                supplier=supplier,
                product=product,
                purchase_date=date(2026, 9, index),
                quantity=index * 10,
                unit_price=100,
                paid_amount=index * 25,
                created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
            )

        supplier_response = self.client.get(reverse('suppliers:ledger'), {
            'supplier': str(supplier.pk),
        })

        self.assertEqual(supplier_response.status_code, 200)
        self.assertEqual(len(supplier_response.context['ledger_sets']), 1)
        combined_ledger = supplier_response.context['ledger_sets'][0]
        self.assertEqual(
            {
                entry['product_name']
                for entry in combined_ledger['ledger_entries']
                if not entry['is_bf_row']
            },
            {product.name for product in products},
        )
        for product in products:
            self.assertContains(supplier_response, product.name)
        self.assertContains(supplier_response, f'{supplier.name} Unified Ledger')
        self.assertEqual(combined_ledger['total_paid'], 150)

        subset_response = self.client.get(reverse('suppliers:ledger'), [
            ('supplier', str(supplier.pk)),
            ('products', str(products[0].pk)),
            ('products', str(products[0].pk)),
            ('products', str(products[2].pk)),
        ])

        self.assertEqual(subset_response.status_code, 200)
        self.assertEqual(len(subset_response.context['ledger_sets']), 1)
        self.assertEqual(
            {
                entry['product_name']
                for entry in subset_response.context['ledger_entries']
                if not entry['is_bf_row']
            },
            {products[0].name, products[2].name},
        )
        self.assertNotContains(subset_response, f'{products[1].name} - {supplier.name} Ledger')

    def test_multi_product_ledger_uses_one_chronological_running_balance(self):
        supplier = Supplier.objects.create(
            name='Unified Ledger Supplier',
            bf_balance=100,
        )
        oxygen = Product.objects.create(name='OXYGEN 10L', is_purchasable=True)
        nitrogen = Product.objects.create(name='NITROGEN 10L', is_purchasable=True)
        later_purchase = Purchase.objects.create(
            supplier=supplier,
            product=nitrogen,
            purchase_date=date(2026, 9, 2),
            quantity=10,
            unit_price=90,
            paid_amount=50,
        )
        earlier_purchase = Purchase.objects.create(
            supplier=supplier,
            product=oxygen,
            purchase_date=date(2026, 9, 1),
            quantity=10,
            unit_price=125,
            paid_amount=25,
        )

        response = self.client.get(reverse('suppliers:ledger'), {'supplier': str(supplier.pk)})

        self.assertEqual(response.status_code, 200)
        ledger = response.context['ledger_sets'][0]
        self.assertTrue(ledger['is_unified'])
        self.assertEqual(len(ledger['ledger_entries']), 3)
        self.assertTrue(ledger['ledger_entries'][0]['is_bf_row'])
        entries = ledger['ledger_entries'][1:]
        self.assertEqual(
            [entry['product_name'] for entry in entries],
            ['OXYGEN 10L', 'NITROGEN 10L'],
        )
        expected_balance = (
            supplier.bf_balance
            + earlier_purchase.subtotal_amount
            + earlier_purchase.sales_tax_amount
            - earlier_purchase.paid_amount
            + later_purchase.subtotal_amount
            + later_purchase.sales_tax_amount
            - later_purchase.paid_amount
        )
        self.assertEqual(entries[-1]['balance'], float(expected_balance))
        self.assertEqual(ledger['final_balance'], float(expected_balance))
        self.assertContains(response, 'Unified Ledger')

    def test_purchase_entry_can_save_supplier_payment_without_product(self):
        supplier = Supplier.objects.create(name='Payment Supplier', supplier_code='SUP-0003')
        selected_date = date(2026, 9, 5)

        response = self.client.post(
            reverse('suppliers:save_purchase_api'),
            data=json.dumps({
                'date': selected_date.isoformat(),
                'data': {
                    'supplier_id': str(supplier.pk),
                    'product_id': '',
                    'invoice_no': 'SUP-PAY-001',
                    'paid_amount': 450,
                    'payment_type': 'transfer',
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        purchase = Purchase.objects.get(supplier=supplier)
        self.assertIsNone(purchase.product)
        self.assertEqual(purchase.invoice_no, 'SUP-PAY-001')
        self.assertEqual(purchase.paid_amount, 450)
        self.assertEqual(purchase.purchase_date, selected_date)

        daily_response = self.client.get(
            reverse('suppliers:purchase_entry'),
            {'date': selected_date.isoformat()},
        )
        activity = daily_response.context['activities'][0]
        self.assertTrue(activity['is_payment'])
        self.assertEqual(activity['product_name'], 'Payment Only')
        self.assertEqual(activity['invoice_no'], 'SUP-PAY-001')

    def test_purchase_entry_post_can_save_supplier_payment_without_product(self):
        supplier = Supplier.objects.create(name='Bulk Payment Supplier', supplier_code='SUP-0004')

        response = self.client.post(
            reverse('suppliers:purchase_entry'),
            {
                'selected_date': date.today().isoformat(),
                'supplier_id_1': str(supplier.pk),
                'product_id_1': '',
                'invoice_no_1': 'SUP-PAY-002',
                'paid_amount_1': '125',
                'payment_type_1': 'cash',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Purchase.objects.filter(
            supplier=supplier,
            product__isnull=True,
            invoice_no='SUP-PAY-002',
            paid_amount=125,
        ).exists())

    def test_purchase_entry_api_can_save_supplier_payment_without_product_and_invoice(self):
        supplier = Supplier.objects.create(name='No Invoice Payment Supplier', supplier_code='SUP-0005')
        selected_date = date(2026, 9, 6)

        response = self.client.post(
            reverse('suppliers:save_purchase_api'),
            data=json.dumps({
                'date': selected_date.isoformat(),
                'data': {
                    'supplier_id': str(supplier.pk),
                    'product_id': '',
                    'invoice_no': '',
                    'paid_amount': 300,
                    'payment_type': 'transfer',
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        purchase = Purchase.objects.get(supplier=supplier)
        self.assertIsNone(purchase.product)
        self.assertEqual(purchase.invoice_no, '')
        self.assertEqual(purchase.paid_amount, 300)
        self.assertEqual(purchase.purchase_date, selected_date)

    def test_purchase_update_api_can_move_payment_only_purchase_to_selected_date(self):
        supplier = Supplier.objects.create(name='Date Shift Supplier', supplier_code='SUP-0006')
        purchase = Purchase.objects.create(
            supplier=supplier,
            product=None,
            purchase_date=date(2026, 9, 8),
            quantity=0,
            unit_price=0,
            paid_amount=150,
            payment_type='cash',
            invoice_no='',
            description='Payment Only',
            created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
        )

        response = self.client.post(
            reverse('suppliers:update_purchase_api'),
            data=json.dumps({
                'entry_id': str(purchase.pk),
                'data': {
                    'supplier_id': str(supplier.pk),
                    'product_id': '',
                    'quantity': 0,
                    'unit_price': 0,
                    'delivery_charges': 0,
                    'paid_amount': 150,
                    'payment_type': 'cash',
                    'invoice_no': '',
                    'description': 'Payment Only',
                    'tax_type': 'none',
                    'sales_tax_rate': 0,
                    'taxable_qty': 0,
                    'extra_charges': 0,
                    'purchase_date': '2026-09-07',
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        purchase.refresh_from_db()
        self.assertEqual(purchase.purchase_date, date(2026, 9, 7))

    def test_supplier_product_ledger_keeps_unallocated_payment_out_of_product_balance(self):
        supplier = Supplier.objects.create(name='Payment Ledger Supplier', supplier_code='SUP-0005')
        product = Product.objects.create(
            name='OXYGEN 10L',
            is_purchasable=True,
            is_sellable=True,
            stock_quantity=0,
        )

        Purchase.objects.create(
            supplier=supplier,
            product=None,
            purchase_date=date(2026, 9, 5),
            quantity=0,
            unit_price=0,
            paid_amount=450,
            payment_type='transfer',
            invoice_no='SUP-PAY-003',
            description='Payment Only',
            created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
        )

        response = self.client.get(reverse('suppliers:ledger'), {
            'supplier': str(supplier.pk),
            'product': str(product.pk),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['unallocated_payments_total'], 450)
        self.assertEqual(len(response.context['unallocated_payments']), 1)
        self.assertFalse(any(
            entry.get('description') == 'Payment Only'
            for entry in response.context['ledger_entries']
        ))

    def test_edit_and_delete_grouped_purchase_reconcile_paid_amount_and_stock_once(self):
        supplier = Supplier.objects.create(name='Grouped Edit Supplier', supplier_code='SUP-0011')
        product = Product.objects.create(name='CO2 25KG', is_purchasable=True, stock_quantity=20)
        group_id = uuid.uuid4()
        first = Purchase.objects.create(
            supplier=supplier,
            product=product,
            entry_group_id=group_id,
            purchase_date=date(2026, 9, 10),
            quantity=5,
            unit_price=100,
            paid_amount=2500,
            tax_type='with_tax',
            sales_tax_rate=18,
        )
        Purchase.objects.create(
            supplier=supplier,
            product=product,
            entry_group_id=group_id,
            purchase_date=date(2026, 9, 10),
            quantity=5,
            unit_price=100,
            paid_amount=2500,
        )

        update_response = self.client.post(
            reverse('suppliers:update_purchase_api'),
            data=json.dumps({
                'entry_id': str(first.pk),
                'data': {
                    'supplier_id': str(supplier.pk),
                    'product_id': str(product.pk),
                    'quantity': 4,
                    'taxable_qty': 2,
                    'unit_price': 100,
                    'delivery_charges': 0,
                    'paid_amount': 1000,
                    'payment_type': 'cash',
                    'invoice_no': 'GROUP-EDIT-1',
                    'description': 'Edited grouped entry',
                    'tax_type': 'none',
                    'sales_tax_rate': 18,
                    'extra_charges': 0,
                    'purchase_date': '2026-09-10',
                },
            }),
            content_type='application/json',
        )

        self.assertTrue(update_response.json()['success'], update_response.json())
        product.refresh_from_db()
        updated_purchases = Purchase.objects.filter(entry_group_id=group_id)
        self.assertEqual(product.stock_quantity, 14)
        self.assertEqual(updated_purchases.count(), 2)
        self.assertEqual(sum(updated_purchases.values_list('paid_amount', flat=True)), 1000)
        self.assertEqual(sum(updated_purchases.values_list('quantity', flat=True)), 4)

        delete_response = self.client.post(
            reverse('suppliers:delete_purchase_api'),
            data=json.dumps({'entry_id': update_response.json()['entry_id']}),
            content_type='application/json',
        )

        self.assertTrue(delete_response.json()['success'], delete_response.json())
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 10)
        self.assertFalse(Purchase.objects.filter(entry_group_id=group_id).exists())

    def test_supplier_product_ledger_renders_edit_delete_action_column(self):
        supplier = Supplier.objects.create(name='Ledger Action Supplier', supplier_code='SUP-0007')
        product = Product.objects.create(
            name='OXYGEN 10L',
            is_purchasable=True,
            is_sellable=True,
            stock_quantity=0,
        )
        Purchase.objects.create(
            supplier=supplier,
            product=product,
            purchase_date=date(2026, 9, 5),
            quantity=10,
            unit_price=100,
            paid_amount=0,
            payment_type='cash',
            invoice_no='LEDGER-INV-001',
            description='Test purchase',
            created_by=self.client.handler._request.user if hasattr(self.client.handler, '_request') else None,
        )

        response = self.client.get(reverse('suppliers:ledger'), {
            'supplier': str(supplier.pk),
            'product': str(product.pk),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Action')
        self.assertContains(response, 'btn-ledger-edit-purchase')
        self.assertContains(response, 'btn-ledger-delete-purchase')
