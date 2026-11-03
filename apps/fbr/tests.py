from datetime import date
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer
from apps.deliveries.models import Delivery
from apps.fbr.models import FBRCustomerSetting
from apps.products.models import Product


class FBRLedgerDeductionTests(TestCase):
    def test_fbr_invoice_page_resets_only_shown_rows_and_reassigns_sequence(self):
        user = get_user_model().objects.create_user(username='fbrreset', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Reset Invoice Customer')
        other_customer = Customer.objects.create(name='Outside Reset Customer')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)
        first = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='DAILY-500',
            fbr_invoice_no='500',
            delivery_date=date(2026, 9, 1),
        )
        second = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='DAILY-501',
            fbr_invoice_no='501',
            delivery_date=date(2026, 9, 2),
        )
        outside_date = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='DAILY-502',
            fbr_invoice_no='502',
            delivery_date=date(2026, 9, 10),
        )
        outside_customer = Delivery.objects.create(
            customer=other_customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='DAILY-503',
            fbr_invoice_no='503',
            delivery_date=date(2026, 9, 1),
        )

        action_url = reverse('fbr:manage_invoice_numbers')
        report_scope = {
            'customer_id': [str(customer.pk)],
            'delivery_id': [str(first.pk), str(second.pk)],
            'date_from': '2026-09-01',
            'date_to': '2026-09-05',
        }
        reset_response = self.client.post(action_url, {**report_scope, 'action': 'reset'})
        self.assertEqual(reset_response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        outside_date.refresh_from_db()
        outside_customer.refresh_from_db()
        self.assertIsNone(first.fbr_invoice_no)
        self.assertIsNone(second.fbr_invoice_no)
        self.assertEqual(outside_date.fbr_invoice_no, '502')
        self.assertEqual(outside_customer.fbr_invoice_no, '503')
        self.assertEqual(first.invoice_no, 'DAILY-500')
        self.assertEqual(second.invoice_no, 'DAILY-501')

        assign_response = self.client.post(
            action_url,
            {**report_scope, 'action': 'assign', 'start_number': '700'},
        )
        self.assertEqual(assign_response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.fbr_invoice_no, '700')
        self.assertEqual(second.fbr_invoice_no, '701')
        self.assertEqual(first.invoice_no, 'DAILY-500')
        self.assertEqual(second.invoice_no, 'DAILY-501')

    def test_fbr_invoice_sequence_assignment_rejects_conflicts_outside_report(self):
        user = get_user_model().objects.create_user(username='fbrresetconflict', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Reset Conflict Customer')
        other_customer = Customer.objects.create(name='Reset Conflict Outside Customer')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)
        displayed = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date(2026, 9, 1),
            invoice_no='DAILY-600',
            fbr_invoice_no='600',
        )
        outside = Delivery.objects.create(
            customer=other_customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date(2026, 9, 1),
            invoice_no='DAILY-800',
            fbr_invoice_no='800',
        )

        response = self.client.post(reverse('fbr:manage_invoice_numbers'), {
            'action': 'assign',
            'customer_id': str(customer.pk),
            'delivery_id': str(displayed.pk),
            'start_number': '800',
        })

        self.assertEqual(response.status_code, 302)
        displayed.refresh_from_db()
        outside.refresh_from_db()
        self.assertEqual(displayed.fbr_invoice_no, '600')
        self.assertEqual(outside.fbr_invoice_no, '800')

    def test_fbr_invoice_number_assignment_keeps_grouped_deliveries_together(self):
        user = get_user_model().objects.create_user(username='fbrgroupsequence', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Grouped Sequence Customer')
        oxygen = Product.objects.create(name='O2 SMALL', unit_price=2000, stock_quantity=20)
        nitrogen = Product.objects.create(name='N2 SMALL', unit_price=2000, stock_quantity=20)
        invoice_date = date(2026, 9, 16)
        first = Delivery.objects.create(
            customer=customer,
            product=oxygen,
            quantity=1,
            unit_price=2000,
            invoice_no='DAILY-2828',
            fbr_invoice_no='2828',
            delivery_date=invoice_date,
        )
        second = Delivery.objects.create(
            customer=customer,
            product=nitrogen,
            quantity=3,
            unit_price=2000,
            invoice_no='DAILY-2828',
            fbr_invoice_no='2828',
            delivery_date=invoice_date,
        )

        response = self.client.post(reverse('fbr:manage_invoice_numbers'), {
            'action': 'assign',
            'customer_id': str(customer.pk),
            'delivery_group': f'{first.pk},{second.pk}',
            'start_number': '900',
        })

        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.fbr_invoice_no, '900')
        self.assertEqual(second.fbr_invoice_no, '900')
        self.assertEqual(first.invoice_no, 'DAILY-2828')
        self.assertEqual(second.invoice_no, 'DAILY-2828')

    def test_fbr_invoices_preserve_transaction_date_and_sort_by_date(self):
        user = get_user_model().objects.create_user(username='fbrdates', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Date Order Customer', mobile='03001111111')
        co2_product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=20)
        lpg_product = Product.objects.create(name='LPG 15KG', unit_price=80, stock_quantity=20)

        later_transaction = Delivery.objects.create(
            customer=customer,
            product=co2_product,
            quantity=1,
            unit_price=100,
            invoice_no='1002',
            delivery_date=date(2026, 8, 20),
            created_by=user,
        )
        earlier_transaction = Delivery.objects.create(
            customer=customer,
            product=lpg_product,
            quantity=1,
            unit_price=80,
            invoice_no='1001',
            delivery_date=date(2026, 8, 19),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {'customer_id': [customer.pk]},
        )

        rows = response.context['invoice_rows']
        self.assertEqual([row['invoice_no'] for row in rows], ['1002', '1001'])
        self.assertEqual([row['date'] for row in rows], [date(2026, 8, 19), date(2026, 8, 20)])
        self.assertEqual(rows[0]['created_at'], earlier_transaction.created_at)
        self.assertEqual(rows[1]['created_at'], later_transaction.created_at)
        self.assertContains(response, 'ADDED ON')

    def test_fbr_invoices_uses_custom_gst_rate_and_shows_total(self):
        user = get_user_model().objects.create_user(username='fbrgst', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='GST Customer', mobile='03002222222')
        product = Product.objects.create(name='CO2 25KG', unit_price=110, stock_quantity=10)
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=110,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {'customer_id': [customer.pk], 'gst_rate': '10'},
        )

        row = response.context['invoice_rows'][0]
        self.assertEqual(response.context['gst_rate'], Decimal('10'))
        self.assertAlmostEqual(float(row['ex_value']), 100.00, places=2)
        self.assertAlmostEqual(float(row['gst_amount']), 10.00, places=2)
        self.assertAlmostEqual(float(response.context['total_gst']), 10.00, places=2)
        self.assertContains(response, 'GST(10%)')

    def test_fbr_ledger_allows_deduction_percentage_and_shows_before_after_totals(self):
        user = get_user_model().objects.create_user(username='fbrtester', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Test Customer', mobile='03001234567')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:ledger'),
            {'customer_id': customer.pk, 'deduction_percent': '5.5'}
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Deduction (%)', content)
        self.assertIn('Total Ex Value', content)
        self.assertIn('Value After Deduction', content)

    def test_fbr_ledger_excludes_delivery_charges_from_totals(self):
        user = get_user_model().objects.create_user(username='fbrtester2', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Delivery Charge Customer', mobile='03007654321')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            delivery_charges=25,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(float(response.context['total_value']), 200.0, places=2)
        self.assertAlmostEqual(float(response.context['total_ex_value']), 169.49, places=2)
        self.assertAlmostEqual(float(response.context['net_balance']), 200.0, places=2)
        self.assertEqual(response.context['fbr_entries'][0]['delivery_charges'], Decimal('0'))

    def test_fbr_ledger_shows_compact_values_with_hover_details(self):
        user = get_user_model().objects.create_user(username='fbrcompact', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Compact Ledger Customer', mobile='03007777777')
        product = Product.objects.create(name='CO2 25KG', unit_price=115, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=115,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})
        rendered = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'money-display')
        self.assertIn('PKR 230.00', rendered)
        self.assertIn('Full value: PKR 194.92', rendered)

    def test_fbr_formula_ex_value_and_rate_calculations(self):
        user = get_user_model().objects.create_user(username='fbrformula', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Formula Customer', mobile='03009999999')
        product = Product.objects.create(name='CO2 25KG', unit_price=236, stock_quantity=50)

        # 10 cylinders * 236 = 2360 Total Amount
        # Total KG = 10 * 25 = 250 KG
        # EX.VALUE = 2360 / 1.18 = 2000.00
        # RATE = 2000.00 / 250 = 8.00
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=10,
            unit_price=236,
            delivery_date=date.today(),
            created_by=user,
        )

        # Test Ledger Formula
        response_ledger = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})
        self.assertEqual(response_ledger.status_code, 200)
        ledger_entry = response_ledger.context['fbr_entries'][0]
        self.assertAlmostEqual(float(ledger_entry['ex_value']), 2000.00, places=2)
        self.assertAlmostEqual(float(ledger_entry['rate']), 8.00, places=2)
        self.assertAlmostEqual(float(ledger_entry['total_value']), 2360.00, places=2)

        # Test Invoices Formula
        response_invoices = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
            }
        )
        self.assertEqual(response_invoices.status_code, 200)
        invoice_row = response_invoices.context['invoice_rows'][0]
        self.assertAlmostEqual(float(invoice_row['ex_value']), 2000.00, places=2)
        self.assertAlmostEqual(float(invoice_row['rate']), 8.00, places=2)
        self.assertAlmostEqual(float(invoice_row['total_value']), 2360.00, places=2)

    def test_fbr_invoice_keeps_ledger_total_after_rate_rounding(self):
        user = get_user_model().objects.create_user(username='fbrrounding', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Rounding Customer', mobile='03008888888')
        product = Product.objects.create(name='LPG 45KG', unit_price=18500, stock_quantity=20)
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=10,
            unit_price=18500,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('fbr:invoices'), {'customer_id': [customer.pk]})

        row = response.context['invoice_rows'][0]
        self.assertEqual(row['quantity'], Decimal('450.00'))
        self.assertEqual(row['rate'], Decimal('348.40'))
        self.assertEqual(row['ex_value'], Decimal('156780.00'))
        self.assertEqual(row['gst_amount'], Decimal('28220.00'))
        self.assertEqual(row['total_value'], Decimal('185000.00'))
        self.assertEqual(row['ex_value'] + row['gst_amount'], row['total_value'])

    def test_fbr_invoice_row_ex_value_tracks_visible_quantity_and_rate_contract(self):
        user = get_user_model().objects.create_user(username='fbrvisiblecontract', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Visible Rate Contract Customer', mobile='03001112222')
        product = Product.objects.create(name='OXYGEN GAGE', unit_price=115, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=Decimal('66.32'),
            unit_price=Decimal('115.00'),
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
                'gst_rate': '18.00',
                'divisor_value': '115',
            },
        )

        self.assertEqual(response.status_code, 200)
        row = response.context['invoice_rows'][0]
        self.assertAlmostEqual(
            float(row['ex_value']),
            float(row['quantity']) * float(row['rate']),
            places=2,
        )

    def test_compact_decimal_rounds_two_places(self):
        from apps.fbr.templatetags.fbr_filters import compact_decimal

        self.assertEqual(compact_decimal(Decimal('911.1771')), '911.18')
        self.assertEqual(compact_decimal(Decimal('23.49') * Decimal('38.79')), '911.18')

    def test_truncate_decimal_unrounded_rules(self):
        from apps.fbr.templatetags.fbr_filters import truncate_decimal
        self.assertEqual(truncate_decimal(2.5), '2.5')
        self.assertEqual(truncate_decimal(1.5), '1.5')
        self.assertEqual(truncate_decimal(1.6), '1.6')
        self.assertEqual(truncate_decimal(1.4), '1.4')
        self.assertEqual(truncate_decimal(1.1), '1.1')

    def test_precise_decimal_preserves_requested_precision(self):
        from apps.fbr.templatetags.fbr_filters import precise_decimal

        self.assertEqual(precise_decimal('254.22485'), '254.22')
        self.assertEqual(precise_decimal('254.000'), '254')

    def test_compact_decimal_shows_two_places_but_keeps_full_value(self):
        from apps.fbr.templatetags.fbr_filters import compact_decimal, precise_decimal

        self.assertEqual(compact_decimal('254.22485'), '254.22')
        self.assertEqual(compact_decimal('254.000'), '254.00')
        self.assertEqual(precise_decimal('254.22485'), '254.22')

    def test_fbr_ledger_uses_source_delivery_invoice_number(self):
        user = get_user_model().objects.create_user(username='fbrledgerinvoice', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Manual Ledger Customer', mobile='03006666666')
        product = Product.objects.create(name='Manual Ledger Product', unit_price=100, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            invoice_no='DAILY-INV-100',
            fbr_invoice_no='INV-LEGACY-100',
            delivery_date=date.today(),
            created_by=user,
        )

        FBRCustomerSetting.objects.create(
            customer=customer,
            invoice_number='INV-ASSIGNED-900',
            stn='STN-NEW',
            ntn='NTN-NEW',
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['fbr_entries'][0]['invoice_no'], 'INV-LEGACY-100')
        self.assertContains(response, 'INV-LEGACY-100')
        self.assertNotContains(response, 'INV-ASSIGNED-900')

    def test_fbr_ledger_renders_source_delivery_actions(self):
        user = get_user_model().objects.create_user(username='fbractions', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Action Customer', mobile='03007770000')
        product = Product.objects.create(name='LPG 45KG', unit_price=100, stock_quantity=10)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        self.assertContains(response, 'ACTION')
        self.assertContains(response, 'Edit')
        self.assertContains(response, 'Delete')
        self.assertContains(response, f'edit_id={delivery.pk}')

    def test_fbr_ledger_renders_one_action_pair_per_source_delivery(self):
        user = get_user_model().objects.create_user(username='fbrmulti_actions', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Multi Action Customer', mobile='03007772222')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=20)
        first_delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.context['fbr_entries'][0]['source_delivery'].pk, first_delivery.pk)
        self.assertEqual(response.content.decode().count('title="Edit this source delivery"'), 2)
        self.assertEqual(response.content.decode().count('title="Delete this source delivery"'), 2)

    def test_fbr_ledger_combines_same_category_deliveries_on_the_same_date(self):
        user = get_user_model().objects.create_user(username='fbrseparateo2', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='O2 Separate Entry Customer')
        product = Product.objects.create(name='O2 BIG', unit_price=2000, stock_quantity=20)
        quantities = [2, 4, 2, 2]
        deliveries = [
            Delivery.objects.create(
                customer=customer,
                product=product,
                quantity=quantity,
                unit_price=2000,
                delivery_date=date.today(),
                created_by=user,
            )
            for quantity in quantities
        ]

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        entries = response.context['fbr_entries']
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            {delivery.pk for delivery in entries[0]['source_deliveries']},
            {delivery.pk for delivery in deliveries},
        )
        self.assertEqual(entries[0]['cylinders'], Decimal('10'))
        self.assertEqual(response.context['product_summary'][0]['products'][0]['cylinders'], Decimal('10'))

    def test_fbr_ledger_combines_same_invoice_oxygen_nitrogen_and_argon(self):
        user = get_user_model().objects.create_user(username='fbrcombinedgas', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Combined Gas Customer')
        oxygen = Product.objects.create(name='O2 SMALL', product_code='PROD-AG-01', unit_price=2000, stock_quantity=20)
        nitrogen = Product.objects.create(name='N2 SMALL', product_code='PROD-AG-02', unit_price=2000, stock_quantity=20)
        argon = Product.objects.create(name='ARGON SMALL', product_code='PROD-AG-03', unit_price=2000, stock_quantity=20)
        invoice_date = date(2026, 9, 16)
        source_deliveries = [
            Delivery.objects.create(
                customer=customer,
                product=product,
                quantity=quantity,
                unit_price=2000,
                invoice_no='2828',
                fbr_invoice_no='2828',
                delivery_date=invoice_date,
                created_by=user,
            )
            for product, quantity in ((nitrogen, 3), (oxygen, 1), (argon, 1))
        ]

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        entries = response.context['fbr_entries']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['invoice_no'], '2828')
        self.assertEqual(entries[0]['category'], 'OXYGEN LIQUID')
        self.assertEqual(entries[0]['item_description'], 'OXYGEN LIQUID')
        self.assertEqual(entries[0]['total_value'], Decimal('10000.00'))
        self.assertEqual(entries[0]['cylinders'], Decimal('5'))
        self.assertEqual(entries[0]['source_deliveries'], source_deliveries)
        self.assertEqual(response.content.decode().count('title="Edit this source delivery"'), 3)
        self.assertEqual(response.content.decode().count('title="Delete this source delivery"'), 3)

    def test_fbr_ledger_delete_action_removes_source_delivery(self):
        user = get_user_model().objects.create_user(username='fbrdelete', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Delete Customer', mobile='03007771111')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=0)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.post(
            reverse('fbr:delete_ledger_delivery', kwargs={'pk': delivery.pk}),
        )

        self.assertRedirects(response, f'{reverse("fbr:ledger")}?customer_id={customer.pk}')
        self.assertFalse(Delivery.objects.filter(pk=delivery.pk).exists())
        self.assertEqual(response.status_code, 302)

    def test_fbr_ledger_uses_sequential_numbers_when_multiple_products(self):
        user = get_user_model().objects.create_user(username='fbrledgermulti', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Multi Product Ledger Customer', mobile='03006666667')
        co2_product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)
        lpg_product = Product.objects.create(name='LPG 15KG', unit_price=80, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=co2_product,
            quantity=2,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )
        Delivery.objects.create(
            customer=customer,
            product=lpg_product,
            quantity=3,
            unit_price=80,
            delivery_date=date.today(),
            created_by=user,
        )

        FBRCustomerSetting.objects.create(
            customer=customer,
            invoice_number='INV-ASSIGNED-900',
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        invoice_numbers = [entry['invoice_no'] for entry in response.context['fbr_entries']]
        self.assertEqual(invoice_numbers, ['1001', '1002'])

    def test_fbr_invoices_page_keeps_daily_and_fbr_invoice_numbers_separate(self):
        user = get_user_model().objects.create_user(username='fbrinvoice', password='secret123')
        self.client.force_login(user)

        customer_one = Customer.objects.create(name='Invoice Customer One', mobile='03001111111', stn='STN-001', ntn='NTN-001')
        customer_two = Customer.objects.create(name='Invoice Customer Two', mobile='03002222222', stn='STN-002', ntn='NTN-002')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)

        Delivery.objects.create(
            customer=customer_one,
            product=product,
            quantity=2,
            unit_price=100,
            invoice_no='DAILY-INV-001',
            fbr_invoice_no='INV-CUSTOM-001',
            delivery_date=date.today(),
            created_by=user,
        )
        Delivery.objects.create(
            customer=customer_two,
            product=product,
            quantity=3,
            unit_price=50,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer_one.pk, customer_two.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['selected_customers']), 2)
        self.assertEqual(len(response.context['invoice_rows']), 2)
        self.assertIn('INV-CUSTOM-001', response.content.decode())
        self.assertNotIn('DAILY-INV-001', response.content.decode())

    def test_fbr_invoice_consolidates_category_rows_by_customer_date_and_invoice(self):
        user = get_user_model().objects.create_user(username='fbrconsolidate', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Consolidated Invoice Customer')
        oxygen = Product.objects.create(name='O2 SMALL', product_code='PROD-AI-01', unit_price=2000, stock_quantity=20)
        nitrogen = Product.objects.create(name='N2 SMALL', product_code='PROD-AI-02', unit_price=2000, stock_quantity=20)
        argon = Product.objects.create(name='ARGON SMALL', product_code='PROD-AI-03', unit_price=2000, stock_quantity=20)
        invoice_date = date(2026, 9, 16)
        first = Delivery.objects.create(
            customer=customer,
            product=nitrogen,
            quantity=3,
            unit_price=2000,
            invoice_no='2828',
            fbr_invoice_no='2828',
            delivery_date=invoice_date,
            created_by=user,
        )
        second = Delivery.objects.create(
            customer=customer,
            product=oxygen,
            quantity=1,
            unit_price=2000,
            invoice_no='2828',
            fbr_invoice_no='2828',
            delivery_date=invoice_date,
            created_by=user,
        )
        third = Delivery.objects.create(
            customer=customer,
            product=argon,
            quantity=1,
            unit_price=2000,
            invoice_no='2828',
            fbr_invoice_no='2828',
            delivery_date=invoice_date,
            created_by=user,
        )
        fourth = Delivery.objects.create(
            customer=customer,
            product=oxygen,
            quantity=1,
            unit_price=2000,
            invoice_no='2829',
            fbr_invoice_no='2829',
            delivery_date=invoice_date,
            created_by=user,
        )

        response = self.client.get(reverse('fbr:invoices'), {
            'customer_id': [str(customer.pk)],
            'date_from': invoice_date.isoformat(),
            'date_to': invoice_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        oxygen_invoice_rows = [
            row for row in response.context['invoice_rows']
            if row['invoice_no'] == '2828'
        ]
        self.assertEqual(len(oxygen_invoice_rows), 1)
        combined_row = oxygen_invoice_rows[0]
        self.assertEqual(combined_row['item_description'], 'OXYGEN LIQUID')
        self.assertEqual(combined_row['total_value'], Decimal('12000.00'))
        self.assertEqual(set(combined_row['delivery_ids']), {
            str(first.pk), str(second.pk), str(third.pk), str(fourth.pk),
        })
        self.assertEqual(len(response.context['invoice_rows']), 1)

    def test_fbr_sequence_is_shared_within_category_and_distinct_across_categories(self):
        user = get_user_model().objects.create_user(username='fbrcategorysequence', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Category Sequence Customer')
        oxygen = Product.objects.create(name='O2 SMALL', product_code='PROD-SEQ-01', unit_price=100, stock_quantity=20)
        nitrogen = Product.objects.create(name='N2 SMALL', product_code='PROD-SEQ-02', unit_price=100, stock_quantity=20)
        co2 = Product.objects.create(name='CO2 40KG', product_code='PROD-SEQ-03', unit_price=100, stock_quantity=20)
        lpg = Product.objects.create(name='LPG 45KG', product_code='PROD-SEQ-04', unit_price=100, stock_quantity=20)
        invoice_date = date(2026, 9, 18)

        deliveries = [
            Delivery.objects.create(
                customer=customer,
                product=product,
                quantity=1,
                unit_price=100,
                invoice_no=f'DAILY-{index}',
                delivery_date=invoice_date,
                created_by=user,
            )
            for index, product in enumerate((oxygen, nitrogen, co2, lpg), start=1)
        ]

        self.assertEqual(deliveries[0].fbr_invoice_no, deliveries[1].fbr_invoice_no)
        self.assertNotEqual(deliveries[0].fbr_invoice_no, deliveries[2].fbr_invoice_no)
        self.assertNotEqual(deliveries[2].fbr_invoice_no, deliveries[3].fbr_invoice_no)
        self.assertEqual(
            [delivery.invoice_no for delivery in deliveries],
            ['DAILY-1', 'DAILY-2', 'DAILY-3', 'DAILY-4'],
        )
        response = self.client.get(reverse('fbr:invoices'), {
            'customer_id': [str(customer.pk)],
            'date_from': invoice_date.isoformat(),
            'date_to': invoice_date.isoformat(),
        })
        rows = response.context['invoice_rows']
        self.assertEqual(len(rows), 3)
        oxygen_row = next(row for row in rows if row['item_description'] == 'OXYGEN LIQUID')
        self.assertEqual(set(oxygen_row['delivery_ids']), {
            str(deliveries[0].pk), str(deliveries[1].pk),
        })
        self.assertEqual(len({row['invoice_no'] for row in rows}), 3)

    def test_daily_invoice_number_remains_separate_from_fbr_sequence(self):
        user = get_user_model().objects.create_user(username='invoice-separation', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Separated Invoice Customer')
        product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='DAILY-INV-2026-01',
            delivery_date=date.today(),
        )

        fbr_response = self.client.get(reverse('fbr:invoices'), {
            'customer_id': [str(customer.pk)],
        })
        customer_ledger_response = self.client.get(reverse('customers:ledger'), {
            'customer_id': str(customer.pk),
        })

        delivery.refresh_from_db()
        self.assertEqual(delivery.invoice_no, 'DAILY-INV-2026-01')
        self.assertEqual(delivery.fbr_invoice_no, '1001')
        self.assertEqual(fbr_response.context['invoice_rows'][0]['invoice_no'], '1001')
        self.assertNotContains(fbr_response, 'DAILY-INV-2026-01')
        self.assertContains(customer_ledger_response, 'DAILY-INV-2026-01')

    def test_fbr_invoices_excludes_products_outside_special_categories(self):
        user = get_user_model().objects.create_user(username='fbrotherproducts', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Other Product Customer', mobile='03007777777')
        product = Product.objects.create(name='Medical Vacuum Pump', unit_price=100, stock_quantity=10)
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['invoice_rows']), 0)
        self.assertNotContains(response, 'MEDICAL VACUUM PUMP')

    def test_fbr_invoices_page_supports_manual_stn_ntn_without_overriding_source_number(self):
        user = get_user_model().objects.create_user(username='fbrmanual', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Manual Invoice Customer', mobile='03005555555', stn='STN-OLD', ntn='NTN-OLD')
        product = Product.objects.create(name='Manual Product', unit_price=100, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            invoice_no='DAILY-INV-001',
            fbr_invoice_no='INV-LEGACY-001',
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
            }
        )

        FBRCustomerSetting.objects.create(
            customer=customer,
            invoice_number='1002',
            stn='STN-NEW',
            ntn='NTN-NEW',
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['invoice_rows'][0]['invoice_no'], 'INV-LEGACY-001')
        self.assertEqual(response.context['invoice_rows'][0]['stn'], 'STN-NEW')
        self.assertEqual(response.context['invoice_rows'][0]['ntn'], 'NTN-NEW')
        self.assertContains(response, 'INV-LEGACY-001')
        self.assertContains(response, 'STN-NEW')
        self.assertContains(response, 'NTN-NEW')

    def test_fbr_invoices_assigns_sequential_invoice_numbers_per_row(self):
        user = get_user_model().objects.create_user(username='fbrsequence', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Sequential Customer', mobile='03007777777')
        co2_product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)
        lpg_product = Product.objects.create(name='LPG 15KG', unit_price=80, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=co2_product,
            quantity=2,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )
        Delivery.objects.create(
            customer=customer,
            product=lpg_product,
            quantity=3,
            unit_price=80,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(
            reverse('fbr:invoices'),
            {
                'customer_id': [customer.pk],
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat(),
            }
        )

        invoice_numbers = [row['invoice_no'] for row in response.context['invoice_rows']]
        self.assertEqual(invoice_numbers, ['1001', '1002'])

    def test_fbr_invoices_keeps_numbers_unique_across_customers_and_product_categories(self):
        user = get_user_model().objects.create_user(username='fbrglobalunique', password='secret123')
        self.client.force_login(user)
        customer_one = Customer.objects.create(name='Global Invoice Customer One')
        customer_two = Customer.objects.create(name='Global Invoice Customer Two')
        co2 = Product.objects.create(name='CO2 25KG', stock_quantity=10)
        oxygen = Product.objects.create(name='OXYGEN LIQUID', stock_quantity=10)
        invoice_date = date(2026, 9, 3)

        first_delivery = Delivery.objects.create(
            customer=customer_one,
            product=co2,
            quantity=1,
            unit_price=100,
            delivery_date=invoice_date,
        )
        second_delivery = Delivery.objects.create(
            customer=customer_one,
            product=oxygen,
            quantity=1,
            unit_price=100,
            delivery_date=invoice_date,
        )
        third_delivery = Delivery.objects.create(
            customer=customer_two,
            product=co2,
            quantity=1,
            unit_price=100,
            delivery_date=invoice_date,
        )
        FBRCustomerSetting.objects.create(customer=customer_one, invoice_number='1001')
        FBRCustomerSetting.objects.create(customer=customer_two, invoice_number='1001')

        response = self.client.get(reverse('fbr:invoices'), {
            'customer_id': [str(customer_one.pk), str(customer_two.pk)],
        })

        self.assertEqual(response.status_code, 200)
        invoice_numbers = [row['invoice_no'] for row in response.context['invoice_rows']]
        self.assertEqual(len(invoice_numbers), 3)
        self.assertEqual(
            invoice_numbers,
            [first_delivery.fbr_invoice_no, second_delivery.fbr_invoice_no, third_delivery.fbr_invoice_no],
        )

    def test_fbr_ledger_uses_sequential_source_invoice_numbers(self):
        user = get_user_model().objects.create_user(username='fbrledgerseq', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Ledger Sequence Customer', mobile='03008888888')
        co2_product = Product.objects.create(name='CO2 25KG', unit_price=100, stock_quantity=10)
        lpg_product = Product.objects.create(name='LPG 15KG', unit_price=80, stock_quantity=10)

        Delivery.objects.create(
            customer=customer,
            product=co2_product,
            quantity=2,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )
        Delivery.objects.create(
            customer=customer,
            product=lpg_product,
            quantity=3,
            unit_price=80,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('fbr:ledger'), {'customer_id': customer.pk})

        invoice_numbers = [entry['invoice_no'] for entry in response.context['fbr_entries']]
        self.assertEqual(invoice_numbers, ['1001', '1002'])

    def test_new_deliveries_receive_global_sequential_invoice_numbers(self):
        user = get_user_model().objects.create_user(username='fbrsave', password='secret123')
        self.client.force_login(user)

        first_customer = Customer.objects.create(name='First Sequence Customer')
        second_customer = Customer.objects.create(name='Second Sequence Customer')
        product = Product.objects.create(name='OXYGEN LIQUID', stock_quantity=10)
        first = Delivery.objects.create(
            customer=first_customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date(2026, 9, 3),
            created_by=user,
        )
        second = Delivery.objects.create(
            customer=second_customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date(2026, 9, 1),
            created_by=user,
        )

        self.assertEqual(first.fbr_invoice_no, '1001')
        self.assertEqual(second.fbr_invoice_no, '1002')
        self.assertIsNone(first.invoice_no)
        self.assertIsNone(second.invoice_no)

    def test_delivery_invoice_number_database_allows_duplicates(self):
        customer = Customer.objects.create(name='Unique Number Customer')
        product = Product.objects.create(name='CO2 25KG', stock_quantity=10)
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='UNIQUE-INV-1',
            delivery_date=date.today(),
        )

        duplicate = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            invoice_no='UNIQUE-INV-1',
            delivery_date=date.today(),
        )

        self.assertEqual(duplicate.invoice_no, 'UNIQUE-INV-1')
        self.assertEqual(Delivery.objects.filter(invoice_no='UNIQUE-INV-1').count(), 2)

    def test_fbr_invoices_and_ledger_exclude_zero_value_rows(self):
        user = get_user_model().objects.create_user(username='fbrzero', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Zero Value Customer', mobile='03000000001')
        o2_product = Product.objects.create(name='OXYGEN LIQUID', unit_price=0, stock_quantity=10)

        # Zero quantity and zero price delivery
        Delivery.objects.create(
            customer=customer,
            product=o2_product,
            quantity=0,
            unit_price=0,
            delivery_amount=0,
            delivery_date=date.today(),
            created_by=user,
        )

        response_invoices = self.client.get(
            reverse('fbr:invoices'),
            {'customer_id': [customer.pk]},
        )
        self.assertEqual(response_invoices.status_code, 200)
        self.assertEqual(len(response_invoices.context['invoice_rows']), 0)

        response_ledger = self.client.get(
            reverse('fbr:ledger'),
            {'customer_id': customer.pk},
        )
        self.assertEqual(response_ledger.status_code, 200)
        self.assertEqual(len(response_ledger.context['fbr_entries']), 0)
