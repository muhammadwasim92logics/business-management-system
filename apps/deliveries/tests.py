from datetime import date, timedelta
from pathlib import Path
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from urllib.parse import urlencode

from apps.customers.models import Customer
from apps.products.models import Product
from apps.payments.models import Payment
from apps.cylinders.models import CylinderLedger
from .models import Delivery


class SessionTimeoutConfigurationTests(TestCase):
    def test_session_persists_until_explicit_logout(self):
        self.assertGreaterEqual(settings.SESSION_COOKIE_AGE, 315360000)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertFalse(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)

        app_js = Path(settings.BASE_DIR) / 'static' / 'js' / 'app.js'
        self.assertTrue(app_js.exists())
        content = app_js.read_text(encoding='utf-8')
        self.assertNotIn('INACTIVITY_LIMIT', content)
        self.assertNotIn("window.location.href = '/auth/logout/'", content)


class DeliveryDateTests(TestCase):
    def test_explicit_delivery_date_is_preserved(self):
        user = get_user_model().objects.create_user(username='tester', password='secret123')
        customer = Customer.objects.create(name='Test Customer', mobile='03001234567')
        product = Product.objects.create(name='Test Product', unit_price=10, stock_quantity=5)

        old_date = date(2024, 6, 15)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=10,
            delivery_date=old_date,
            created_by=user,
        )

        self.assertEqual(delivery.delivery_date, old_date)

    def test_delivery_accepts_decimal_quantity_in_kg_for_home_refill_entry(self):
        user = get_user_model().objects.create_user(username='decimal-quantity-tester', password='secret123')
        customer = Customer.objects.create(name='Decimal Quantity Customer', mobile='03001234567')
        product = Product.objects.create(name='CO2 10KG', unit_price=100, stock_quantity=10)

        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2.5,
            unit_price=100,
            delivery_date=date.today(),
            created_by=user,
        )

        self.assertEqual(float(delivery.quantity), 2.5)
        self.assertEqual(float(delivery.delivery_amount), 250.0)


class WalkinDuplicatePreventionTests(TestCase):
    def test_same_walkin_identity_reuses_one_customer_record(self):
        selected_date = date.today()

        first = Customer.get_or_create_walkin(
            name='Ali',
            mobile='03001234567',
            security_deposit=100,
            personal_cylinders=2,
            last_activity_date=selected_date,
        )
        second = Customer.get_or_create_walkin(
            name='Ali',
            mobile='03001234567',
            security_deposit=250,
            personal_cylinders=5,
            last_activity_date=selected_date,
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Customer.objects.filter(is_walkin=True).count(), 1)


class DailyEntryTemplateTests(TestCase):
    def test_bulk_entry_ajax_save_returns_success_and_persists_delivery(self):
        user = get_user_model().objects.create_user(username='daily-entry-save-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Bulk Save Customer', mobile='03001234567')
        product = Product.objects.create(name='Bulk Save Cylinder', unit_price=100, stock_quantity=5)

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            {
                'selected_date': date.today().isoformat(),
                'customer_type_1': 'existing',
                'customer_id_1': str(customer.pk),
                'product_ids_1[]': [str(product.pk)],
                'quantities_1[]': ['1'],
                'sale_quantities_1[]': ['0'],
                'empty_returns_1[]': ['0'],
                'cylinder_movements_1[]': [''],
                'product_prices_1[]': ['100'],
                'invoice_numbers_1[]': [''],
                'personal_details_1[]': [''],
                'delivery_charges_1[]': ['0'],
                'damage_charges_1[]': ['0'],
                'payment_amount_1[]': ['0'],
                'payment_type_1[]': ['cash'],
                'description_1[]': [''],
                'low_pressure_json_1[]': [''],
                'full_returned_1[]': ['0'],
                'full_returned_value_1[]': ['0'],
                'full_returned_paid_1[]': ['false'],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(Delivery.objects.filter(customer=customer, product=product).count(), 1)

    def test_bulk_walkin_entry_is_processed_when_customer_radios_are_disabled(self):
        user = get_user_model().objects.create_user(username='daily-walkin-bulk-tester', password='secret123')
        self.client.force_login(user)
        product = Product.objects.create(name='Walk-in Bulk Cylinder', unit_price=100, stock_quantity=5)

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            {
                'selected_date': date.today().isoformat(),
                'walkin_flag_1': 'true',
                'walkin_name_1': 'Walk-in Bulk Test',
                'walkin_mobile_1': '03001239876',
                'walkin_security_1': '0',
                'walkin_personal_1': '0',
                'product_ids_1[]': [str(product.pk)],
                'quantities_1[]': ['1'],
                'sale_quantities_1[]': ['0'],
                'empty_returns_1[]': ['0'],
                'delivery_charges_1[]': ['0'],
                'damage_charges_1[]': ['0'],
                'payment_amount_1[]': ['0'],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(
            Delivery.objects.filter(customer__name='Walk-in Bulk Test', product=product).count(),
            1,
        )

    def test_bulk_entry_error_response_identifies_entry_and_customer_field(self):
        user = get_user_model().objects.create_user(username='daily-entry-error-tester', password='secret123')
        self.client.force_login(user)

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            {
                'selected_date': date.today().isoformat(),
                'customer_type_2': 'existing',
                'product_ids_2[]': ['missing-customer-product'],
                'sale_quantities_2[]': ['1'],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['entry_number'], 2)
        self.assertEqual(response.json()['location'], 'Customer')
        self.assertEqual(
            response.json()['error'],
            'Select a customer before entering products or payments.',
        )

    def test_bulk_save_reports_each_populated_invalid_entry_and_ignores_blank_rows(self):
        user = get_user_model().objects.create_user(username='daily-entry-sequential-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Sequential Save Customer', mobile='03001234567')
        product = Product.objects.create(name='Sequential Save Cylinder', unit_price=100, stock_quantity=20)

        def entry_fields(number, *, product_selected=False, quantity='0', invoice='', selected_customer=True):
            return {
                f'customer_type_{number}': 'existing',
                f'customer_id_{number}': str(customer.pk) if selected_customer else '',
                f'product_ids_{number}[]': [str(product.pk) if product_selected else ''],
                f'quantities_{number}[]': [quantity],
                f'sale_quantities_{number}[]': ['0'],
                f'empty_returns_{number}[]': ['0'],
                f'cylinder_movements_{number}[]': [''],
                f'product_prices_{number}[]': ['100' if product_selected else ''],
                f'invoice_numbers_{number}[]': [invoice],
                f'personal_details_{number}[]': [''],
                f'delivery_charges_{number}[]': ['0'],
                f'damage_charges_{number}[]': ['0'],
                f'payment_amount_{number}[]': ['0'],
                f'payment_type_{number}[]': ['cash'],
                f'description_{number}[]': [''],
                f'low_pressure_json_{number}[]': [''],
                f'full_returned_{number}[]': ['0'],
                f'full_returned_value_{number}[]': ['0.00'],
                f'full_returned_paid_{number}[]': ['false'],
            }

        def post_entries(entries):
            data = {'selected_date': date.today().isoformat()}
            for number, fields in entries:
                data.update(entry_fields(number, **fields))
            return self.client.post(
                reverse('deliveries:daily_entry'),
                data,
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

        blank_defaults = {'product_selected': False, 'selected_customer': False}
        first_attempt = post_entries([
            (1, {'product_selected': True, 'quantity': '1'}),
            (2, blank_defaults),
            (3, {'product_selected': True, 'quantity': '0'}),
            (4, blank_defaults),
        ])

        self.assertEqual(first_attempt.status_code, 400)
        self.assertEqual(first_attempt.json()['entry_number'], 3)
        self.assertEqual(first_attempt.json()['location'], 'Product row 1 / Quantity or return details')
        self.assertIn('Enter a quantity', first_attempt.json()['error'])
        self.assertEqual(Delivery.objects.filter(customer=customer).count(), 0)

        retry = post_entries([
            (1, {'product_selected': True, 'quantity': '1'}),
            (2, blank_defaults),
            (3, {'product_selected': True, 'quantity': '1'}),
            (4, blank_defaults),
            (5, {'product_selected': False, 'invoice': 'INV-5'}),
            (6, blank_defaults),
        ])

        self.assertEqual(retry.status_code, 400)
        self.assertEqual(retry.json()['entry_number'], 5)
        self.assertEqual(retry.json()['location'], 'Product row 1 / Product or payment amount')
        self.assertIn('Select a product or enter a payment amount', retry.json()['error'])
        self.assertEqual(Delivery.objects.filter(customer=customer).count(), 0)

    def test_daily_entry_error_modal_is_rendered(self):
        user = get_user_model().objects.create_user(username='daily-entry-modal-tester', password='secret123')
        self.client.force_login(user)

        response = self.client.get(reverse('deliveries:daily_entry'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dailyEntryErrorModal')
        self.assertContains(response, 'Affected entry')
        self.assertContains(response, 'Problem location')
        self.assertContains(response, 'Why it could not be saved')

    def test_transaction_filters_return_only_matching_daily_entries(self):
        user = get_user_model().objects.create_user(username='daily-filter-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Daily Filter Customer', mobile='03001234567')
        product = Product.objects.create(name='Filter Cylinder', unit_price=100, stock_quantity=20)
        selected_date = date.today()

        cases = [
            (3, 0, 0),
            (2, 1, 0),
            (2, 1, 50),
        ]
        for quantity, empty_returned, payment_amount in cases:
            delivery = Delivery.objects.create(
                customer=customer,
                product=product,
                quantity=quantity,
                unit_price=100,
                empty_returned=empty_returned,
                payment_amount=payment_amount,
                delivery_date=selected_date,
                created_by=user,
            )
            CylinderLedger.objects.create(
                customer=customer,
                product=product,
                delivery=delivery,
                full_out=quantity,
                empty_in=empty_returned,
            )

        url = reverse('deliveries:daily_entry')
        for filter_name, expected_count, expected_payments in (
            ('full_no_empty', 1, [0.0]),
            ('credit', 2, [0.0, 0.0]),
            ('partial_payment', 1, [50.0]),
        ):
            response = self.client.get(url, {'date': selected_date.isoformat(), 'transaction_filter': filter_name})
            self.assertEqual(response.status_code, 200)
            activities = response.context['activities']
            self.assertEqual(len(activities), expected_count)
            self.assertEqual([float(activity['payment_amount']) for activity in activities], expected_payments)
            self.assertContains(response, 'Active filters:')

        multi_response = self.client.get(
            f"{url}?date={selected_date.isoformat()}&{urlencode([('transaction_filter', 'full_no_empty'), ('transaction_filter', 'partial_payment')])}"
        )
        self.assertEqual(multi_response.status_code, 200)
        self.assertEqual(len(multi_response.context['activities']), 2)

    def test_standalone_payment_appears_as_payment_only_activity(self):
        user = get_user_model().objects.create_user(username='daily-payment-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Daily Payment Customer', mobile='03001234567')
        product = Product.objects.create(name='Test Product', unit_price=100, stock_quantity=5)
        selected_date = date.today()

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=selected_date,
            created_by=user,
        )
        Payment.objects.create(
            customer=customer,
            payment_date=selected_date,
            amount=25,
            notes='Payment Only on test date',
            created_by=user,
        )

        response = self.client.get(
            reverse('deliveries:daily_entry'),
            {'date': selected_date.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        payment_activities = [
            activity for activity in response.context['activities']
            if activity['type'] == 'payment_only'
        ]
        self.assertEqual(len(payment_activities), 1)
        self.assertEqual(payment_activities[0]['payment_amount'], 25.0)

    def test_payment_only_form_preserves_selected_date(self):
        user = get_user_model().objects.create_user(username='backdated-payment-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Backdated Payment Customer', mobile='03001234567')
        selected_date = date.today() - timedelta(days=3)

        response = self.client.post(
            reverse('deliveries:payment_only'),
            {
                'customer_id': customer.pk,
                'payment_amount': '25',
                'payment_type': 'cash',
                'selected_date': selected_date.isoformat(),
            },
        )

        self.assertRedirects(
            response,
            f'{reverse("deliveries:daily_entry")}?date={selected_date.isoformat()}',
        )
        self.assertTrue(Payment.objects.filter(customer=customer, payment_date=selected_date).exists())

    def test_daily_entry_new_customer_can_be_saved_without_mobile(self):
        user = get_user_model().objects.create_user(username='optional-mobile-tester', password='secret123')
        self.client.force_login(user)
        product = Product.objects.create(name='Optional Mobile Product', unit_price=100, stock_quantity=5)

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_type': 'new',
                    'is_existing': False,
                    'is_walkin': False,
                    'new_customer_name': 'No Mobile Customer',
                    'new_customer_mobile': '',
                    'products': [{
                        'product_id': str(product.pk),
                        'quantity': 1,
                        'rate': 100,
                    }],
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'], response.json())
        customer = Customer.objects.get(name='No Mobile Customer')
        self.assertIn(customer.mobile, ('', None))
        self.assertTrue(Delivery.objects.filter(customer=customer, product=product).exists())

    def test_daily_entry_row_can_save_invoice_payment_without_product(self):
        user = get_user_model().objects.create_user(username='row-payment-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Row Payment Customer', mobile='03001234567')
        selected_date = date.today() - timedelta(days=1)

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(customer.pk),
                    'is_existing': True,
                    'selected_date': selected_date.isoformat(),
                    'products': [{
                        'product_id': '',
                        'invoice_no': 'INV-PAY-001',
                        'payment_amount': 275,
                        'payment_type': 'cash',
                    }],
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        payment = Payment.objects.get(customer=customer)
        self.assertEqual(payment.invoice_no, 'INV-PAY-001')
        self.assertEqual(payment.amount, 275)
        self.assertEqual(payment.payment_date, selected_date)
        daily_response = self.client.get(
            reverse('deliveries:daily_entry'),
            {'date': selected_date.isoformat()},
        )
        activity = next(
            item for item in daily_response.context['activities']
            if item['type'] == 'payment_only'
        )
        self.assertEqual(activity['invoice_no'], 'INV-PAY-001')

    def test_daily_entry_allows_duplicate_delivery_invoice_number(self):
        user = get_user_model().objects.create_user(username='duplicate-invoice-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Duplicate Invoice Customer')
        product = Product.objects.create(name='Duplicate Invoice Product', unit_price=100, stock_quantity=5)
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            invoice_no='INV-DUPLICATE-1',
        )

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(customer.pk),
                    'is_existing': True,
                    'selected_date': date.today().isoformat(),
                    'products': [{
                        'product_id': str(product.pk),
                        'quantity': 1,
                        'rate': 100,
                        'invoice_no': 'INV-DUPLICATE-1',
                    }],
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(Delivery.objects.filter(invoice_no='INV-DUPLICATE-1').count(), 2)

        form_response = self.client.post(
            reverse('deliveries:daily_entry'),
            {
                'selected_date': date.today().isoformat(),
                'customer_type_1': 'existing',
                'customer_id_1': str(customer.pk),
                'product_ids_1[]': [str(product.pk)],
                'quantities_1[]': ['1'],
                'sale_quantities_1[]': ['0'],
                'empty_returns_1[]': ['0'],
                'product_prices_1[]': ['100'],
                'invoice_numbers_1[]': ['INV-DUPLICATE-1'],
            },
            follow=True,
        )
        self.assertEqual(form_response.status_code, 200)
        self.assertEqual(Delivery.objects.filter(invoice_no='INV-DUPLICATE-1').count(), 3)

    def test_daily_entry_individual_payment_only_allows_blank_invoice_number(self):
        user = get_user_model().objects.create_user(username='payment-only-blank-invoice-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Blank Invoice Payment Customer', mobile='03009999999')
        selected_date = date.today() - timedelta(days=1)

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(customer.pk),
                    'is_existing': True,
                    'selected_date': selected_date.isoformat(),
                    'products': [{
                        'product_id': '',
                        'invoice_no': '',
                        'payment_amount': 275,
                        'payment_type': 'cash',
                    }],
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertTrue(Payment.objects.filter(
            customer=customer,
            amount=275,
            payment_type='cash',
            payment_date=selected_date,
            invoice_no='',
        ).exists())

    def test_save_all_can_save_invoice_payment_without_product(self):
        user = get_user_model().objects.create_user(username='bulk-row-payment-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Bulk Row Payment Customer', mobile='03001234567')
        selected_date = date.today()

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            {
                'selected_date': selected_date.isoformat(),
                'customer_type_1': 'existing',
                'customer_id_1': str(customer.pk),
                'product_ids_1[]': [''],
                'invoice_numbers_1[]': ['INV-PAY-002'],
                'payment_amount_1[]': ['125'],
                'payment_type_1[]': ['transfer'],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(
            customer=customer,
            invoice_no='INV-PAY-002',
            amount=125,
            payment_type='transfer',
        ).exists())

    def test_daily_entry_view_uses_before_and_after_delivery_charge_labels(self):
        user = get_user_model().objects.create_user(username='tester', password='secret123')
        self.client.force_login(user)

        customer = Customer.objects.create(name='Test Customer', mobile='03001234567')
        product = Product.objects.create(name='Test Product', unit_price=100, stock_quantity=5)

        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            delivery_charges=25,
            delivery_date=date.today(),
            created_by=user,
        )

        response = self.client.get(reverse('deliveries:daily_entry'), {'date': date.today().isoformat()})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Total Before Delivery Charges', content)
        self.assertIn('Total After Delivery Charges', content)
        self.assertNotIn('<th>Type</th>', content)
        self.assertIn('id="productDetailsModal"', content)
        self.assertIn('openFullReturnModal', content)
        self.assertIn('openLowPressureModal', content)
        self.assertIn('Calculation Preview', content)
        self.assertIn('Total payable:', content)

    def test_payment_only_page_renders_cancel_link(self):
        user = get_user_model().objects.create_user(username='payment-tester', password='secret123')
        self.client.force_login(user)

        response = self.client.get(reverse('deliveries:payment_only'))

        self.assertEqual(response.status_code, 200)

    def test_payment_only_post_handles_float_outstanding_balance(self):
        user = get_user_model().objects.create_user(username='payment-post-tester', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(
            name='Payment Customer',
            mobile='03001234567',
            previous_balance=50000,
        )

        response = self.client.post(reverse('deliveries:payment_only'), {
            'customer_id': customer.pk,
            'payment_amount': '3000',
            'payment_type': 'cash',
        })

        self.assertRedirects(
            response,
            f'{reverse("deliveries:daily_entry")}?date={date.today().isoformat()}',
        )
        self.assertTrue(Payment.objects.filter(customer=customer, amount=3000).exists())


class DailyEntryEditAccountingTests(TestCase):
    def test_edit_and_delete_reconcile_stock_payment_and_customer_balance(self):
        user = get_user_model().objects.create_user(username='daily-edit-accounting', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Daily Edit Accounting Customer')
        product = Product.objects.create(
            name='CO2 10KG',
            unit_price=100,
            stock_quantity=90,
            empty_stock_quantity=1,
            unit_weight_kg=10,
        )
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=date.today(),
            quantity=1,
            unit_price=100,
            empty_returned=1,
            payment_amount=5000,
            created_by=user,
        )
        ledger = CylinderLedger.objects.create(
            customer=customer,
            product=product,
            delivery=delivery,
            full_out=1,
            empty_in=1,
        )

        update_response = self.client.post(
            reverse('deliveries:save_entry_api'),
            data=json.dumps({
                'date': date.today().isoformat(),
                'entry_id': str(delivery.pk),
                'data': {
                    'customer_id': str(customer.pk),
                    'products': [{
                        'product_id': str(product.pk),
                        'full': 2,
                        'rate': 200,
                        'empty': 2,
                    }],
                    'payment': 250,
                    'payment_type': 'cash',
                },
            }),
            content_type='application/json',
        )

        self.assertTrue(update_response.json()['success'], update_response.json())
        delivery.refresh_from_db()
        product.refresh_from_db()
        ledger.refresh_from_db()
        payment = Payment.objects.get(delivery=delivery)
        self.assertEqual(product.stock_quantity, 80)
        self.assertEqual(product.empty_stock_quantity, 2)
        self.assertEqual(ledger.full_out, 2)
        self.assertEqual(ledger.empty_in, 2)
        self.assertEqual(Payment.objects.filter(delivery=delivery).count(), 1)
        self.assertEqual(payment.amount, 250)
        self.assertEqual(customer.get_outstanding_balance(), 150)

        delete_response = self.client.post(
            reverse('deliveries:delete_entry_api'),
            data=json.dumps({'entry_id': str(delivery.pk)}),
            content_type='application/json',
        )

        self.assertTrue(delete_response.json()['success'], delete_response.json())
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 100)
        self.assertEqual(product.empty_stock_quantity, 0)
        self.assertFalse(Delivery.objects.filter(pk=delivery.pk).exists())
        self.assertFalse(Payment.objects.filter(delivery=delivery).exists())
        self.assertFalse(CylinderLedger.objects.filter(pk=ledger.pk).exists())
        self.assertEqual(customer.get_outstanding_balance(), 0)


class FullCylinderReturnTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='return-tester', password='secret123')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='Return Customer',
            mobile='03001234567',
            bf_balance=50000,
        )
        self.product = Product.objects.create(
            name='20kg LPG',
            stock_quantity=200,
            unit_weight_kg=20,
        )

    def save_return(self, paid):
        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'products': [{
                        'product_id': str(self.product.pk),
                        'quantity': 0,
                        'empty_returned': 0,
                        'full_returned': 1,
                        'full_returned_value': 5000,
                        'full_returned_paid': paid,
                        'rate': 0,
                    }],
                    'selected_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    def test_return_to_customer_can_use_negative_bf_cylinders(self):
        self.customer.bf_cylinders = {'20kg LPG': -3}
        self.customer.save(update_fields=['bf_cylinders'])

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'products': [{
                        'product_id': str(self.product.pk),
                        'empty_returned': 2,
                        'cylinder_movement_type': 'customer_returned',
                    }],
                    'selected_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertTrue(response.json()['success'], response.json())
        self.customer.refresh_from_db()
        ownership_entry = CylinderLedger.objects.get(customer=self.customer, ownership_movement='customer_returned')
        self.assertEqual(ownership_entry.ownership_quantity, 2)
        self.assertEqual(self.customer.get_cylinder_balance()['20kg LPG'], -1)

    def test_save_all_records_return_to_customer_ownership_movement(self):
        self.customer.bf_cylinders = {'20kg LPG': -3}
        self.customer.save(update_fields=['bf_cylinders'])

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'selected_date': date.today().isoformat(),
                'customer_type_1': 'existing',
                'customer_id_1': str(self.customer.pk),
                'product_ids_1[]': [str(self.product.pk)],
                'quantities_1[]': ['0'],
                'sale_quantities_1[]': ['0'],
                'empty_returns_1[]': ['2'],
                'cylinder_movements_1[]': ['customer_returned'],
                'product_prices_1[]': ['0'],
            }
        )

        self.assertEqual(response.status_code, 302)
        ledger = CylinderLedger.objects.get(customer=self.customer, ownership_movement='customer_returned')
        self.assertEqual(ledger.ownership_quantity, 2)
        self.assertEqual(self.customer.get_cylinder_balance()['20kg LPG'], -1)

        daily_response = self.client.get(
            reverse('deliveries:daily_entry'),
            {'date': date.today().isoformat()},
        )
        self.assertEqual(daily_response.status_code, 200)
        activity_balances = [
            (activity.get('type'), activity.get('new_cylinders_display'))
            for activity in daily_response.context['activities']
        ]
        self.assertTrue(any(
            activity['new_cylinders_display'].casefold() == '20kg lpg: -1'
            for activity in daily_response.context['activities']
            if activity.get('type') == 'delivery'
        ), activity_balances)
        ownership_activity = next(
            activity for activity in daily_response.context['activities']
            if activity.get('type') == 'delivery'
            and activity['id'] == str(Delivery.objects.get(
                customer=self.customer,
                cylinder_movement_type='customer_returned',
            ).pk)
        )
        self.assertEqual(ownership_activity['items'][0]['empty_returned'], 2)

    def test_credit_return_reduces_balance_and_adds_weighted_stock(self):
        self.save_return(False)

        self.customer.refresh_from_db()
        self.product.refresh_from_db()
        delivery = Delivery.objects.get(customer=self.customer)
        self.assertEqual(self.customer.get_outstanding_balance(), 45000)
        self.assertEqual(self.customer.get_cylinder_balance()['20KG LPG'], -1)
        self.assertEqual(self.product.stock_quantity, 220)
        self.assertEqual(self.product.stock_weight_kg, 20)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(delivery.return_details, ['Full return: 1 cylinder(s) -> PKR 5,000.00 (credited to account)'])

    def test_cash_paid_return_keeps_balance_and_records_cash_outflow(self):
        self.save_return(True)

        self.customer.refresh_from_db()
        self.product.refresh_from_db()
        delivery = Delivery.objects.get(customer=self.customer)
        self.assertEqual(self.customer.get_outstanding_balance(), 50000)
        self.assertEqual(Payment.objects.get().amount, -5000)
        self.assertEqual(self.product.stock_weight_kg, 20)
        self.assertIn('paid cash on spot', delivery.return_details[0])

    def test_exchange_sale_moves_full_stock_to_empty_stock(self):
        product = Product.objects.create(
            name='ARGON',
            stock_quantity=28,
            empty_stock_quantity=20,
        )
        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'products': [{
                        'product_id': str(product.pk),
                        'quantity': 2,
                        'empty_returned': 2,
                        'rate': 100,
                    }],
                    'selected_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertTrue(response.json()['success'])
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 26)
        self.assertEqual(product.empty_stock_quantity, 22)

    def test_empty_cylinder_return_to_customer_creates_no_charge_or_payment(self):
        product = Product.objects.create(
            name='ARGON RETURN',
            stock_quantity=10,
            empty_stock_quantity=3,
        )
        receive_response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'products': [{
                        'product_id': str(product.pk),
                        'empty_returned': 1,
                        'cylinder_movement_type': 'customer_received',
                    }],
                    'selected_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )
        self.assertTrue(receive_response.json()['success'])

        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'products': [{
                        'product_id': str(product.pk),
                        'empty_returned': 1,
                        'cylinder_movement_type': 'customer_returned',
                        'rate': 0,
                        'payment_amount': 0,
                    }],
                    'selected_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        product.refresh_from_db()
        delivery = Delivery.objects.get(
            customer=self.customer,
            product=product,
            cylinder_movement_type='customer_returned',
        )
        ledger = CylinderLedger.objects.get(delivery=delivery)
        self.assertEqual(product.empty_stock_quantity, 3)
        self.assertEqual(delivery.quantity, 0)
        self.assertEqual(delivery.delivery_amount, 0)
        self.assertEqual(delivery.payment_amount, 0)
        self.assertEqual(ledger.full_out, 0)
        self.assertEqual(ledger.empty_in, 0)
        self.assertEqual(ledger.ownership_movement, 'customer_returned')
        self.assertEqual(ledger.ownership_quantity, 1)
        self.assertEqual(Payment.objects.count(), 0)

        delete_response = self.client.post(
            reverse('deliveries:delete_entry_api'),
            data={'entry_id': str(delivery.pk)},
            content_type='application/json',
        )

        self.assertTrue(delete_response.json()['success'])
        product.refresh_from_db()
        self.assertEqual(product.empty_stock_quantity, 3)
        self.assertFalse(CylinderLedger.objects.filter(pk=ledger.pk).exists())

    def test_sale_only_reduces_full_stock_without_empty_stock(self):
        product = Product.objects.create(
            name='BLACK CYLINDER',
            stock_quantity=100,
            empty_stock_quantity=20,
            is_quantity_only=True,
        )
        response = self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'products': [{
                        'product_id': str(product.pk),
                        'sale_quantity': 2,
                        'quantity': 0,
                        'empty_returned': 2,
                        'rate': 100,
                    }],
                    'selected_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertTrue(response.json()['success'])
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 98)
        self.assertEqual(product.empty_stock_quantity, 20)


class DeliveryUpdateDetailsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='update-tester', password='secret123')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Update Customer', mobile='03001112222')
        self.product = Product.objects.create(name='Update LPG 20KG', stock_quantity=200, stock_weight_kg=200, unit_weight_kg=20)
        self.delivery = Delivery.objects.create(
            customer=self.customer,
            product=self.product,
            quantity=2,
            unit_price=100,
            empty_returned=0,
            delivery_date=date.today(),
            created_by=self.user,
        )
        self.product.stock_quantity -= 40
        self.product.stock_weight_kg -= 40
        self.product.save()
        CylinderLedger.objects.create(
            customer=self.customer,
            product=self.product,
            delivery=self.delivery,
            full_out=2,
            empty_in=0,
        )

    def test_update_entry_saves_returns_low_pressure_and_ledger(self):
        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(self.delivery.pk),
                'data': {
                    'customer_id': str(self.customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 2,
                    'unit_price': 100,
                    'empty_returned': 1,
                    'full_returned': 1,
                    'full_returned_value': 50,
                    'full_returned_paid': False,
                    'low_pressure_details': [{
                        'total_pressure': 2000,
                        'actual_pressure': 1000,
                        'calculated_price': 50,
                    }],
                    'damage_charges': 0,
                    'delivery_charges': 0,
                    'payment_amount': 0,
                    'payment_type': 'cash',
                    'delivery_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.delivery.refresh_from_db()
        self.product.refresh_from_db()
        ledger = CylinderLedger.objects.get(delivery=self.delivery)
        self.assertEqual(self.delivery.empty_returned, 1)
        self.assertEqual(self.delivery.full_returned, 1)
        self.assertEqual(len(self.delivery.low_pressure_details), 1)
        self.assertEqual(ledger.empty_in, 2)
        self.assertEqual(self.product.stock_quantity, 180)
        self.assertEqual(self.product.stock_weight_kg, 180)

    def test_update_entry_allows_invoice_number_used_by_another_delivery(self):
        other_delivery = Delivery.objects.create(
            customer=self.customer,
            product=self.product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            invoice_no='INV-ALREADY-USED',
            created_by=self.user,
        )

        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(self.delivery.pk),
                'data': {
                    'customer_id': str(self.customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 2,
                    'unit_price': 100,
                    'invoice_no': other_delivery.invoice_no,
                    'delivery_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.invoice_no, other_delivery.invoice_no)

    def test_update_entry_moves_generated_payment_with_delivery_date(self):
        old_date = date.today()
        new_date = old_date - timedelta(days=1)
        self.delivery.payment_amount = 5000
        self.delivery.payment_type = 'cash'
        self.delivery.save()
        payment = Payment.objects.create(
            customer=self.customer,
            amount=5000,
            payment_type='cash',
            payment_date=old_date,
            notes=f'Payment for {self.product.name} on {old_date} (Invoice: N/A)',
            created_by=self.user,
        )

        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(self.delivery.pk),
                'data': {
                    'customer_id': str(self.customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 2,
                    'unit_price': 100,
                    'empty_returned': 0,
                    'payment_amount': 5000,
                    'payment_type': 'cash',
                    'delivery_date': new_date.isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        payment.refresh_from_db()
        self.assertEqual(payment.payment_date, new_date)
        self.assertFalse(Payment.objects.filter(
            customer=self.customer,
            payment_date=old_date,
            notes__startswith='Payment for ',
        ).exists())

    def test_update_links_legacy_payment_by_invoice_when_note_date_differs(self):
        old_date = date.today()
        new_date = old_date - timedelta(days=1)
        self.delivery.invoice_no = 'LEGACY-INV-1'
        self.delivery.payment_amount = 5000
        self.delivery.save()
        payment = Payment.objects.create(
            customer=self.customer,
            amount=5000,
            payment_type='cash',
            payment_date=old_date,
            notes=f'Payment for {self.product.name} on {new_date} (Invoice: LEGACY-INV-1)',
            created_by=self.user,
        )

        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(self.delivery.pk),
                'data': {
                    'customer_id': str(self.customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 2,
                    'unit_price': 100,
                    'empty_returned': 0,
                    'payment_amount': 5000,
                    'payment_type': 'cash',
                    'delivery_date': new_date.isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertTrue(response.json()['success'])
        payment.refresh_from_db()
        self.assertEqual(payment.delivery_id, self.delivery.pk)
        self.assertEqual(payment.payment_date, new_date)

        daily_response = self.client.get(
            reverse('deliveries:daily_entry'),
            {'date': new_date.isoformat()},
        )
        activities = daily_response.context['activities']
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]['type'], 'delivery')
        self.assertEqual(activities[0]['payment_amount'], 5000.0)

    def test_update_entry_preserves_return_to_customer_ownership_movement(self):
        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(self.delivery.pk),
                'data': {
                    'customer_id': str(self.customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 0,
                    'unit_price': 0,
                    'empty_returned': 2,
                    'cylinder_movement_type': 'customer_returned',
                    'full_returned': 0,
                    'full_returned_value': 0,
                    'payment_amount': 0,
                    'delivery_charges': 0,
                    'damage_charges': 0,
                    'payment_type': 'cash',
                    'delivery_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        ledger = CylinderLedger.objects.get(delivery=self.delivery)
        self.assertEqual(ledger.ownership_movement, 'customer_returned')
        self.assertEqual(ledger.ownership_quantity, 2)
        self.assertEqual(self.customer.get_cylinder_balance()[self.product.name], 2)


class DeliveryPaymentConsistencyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='delivery-payment-user', password='secret123')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Delivery Payment Customer')
        self.product = Product.objects.create(name='Delivery Payment Product', unit_price=100, stock_quantity=100)

    def test_customer_balance_api_matches_opening_balance_and_transactions(self):
        customer = Customer.objects.create(name='Balance Breakdown Customer', bf_balance=31600)
        Delivery.objects.create(
            customer=customer,
            product=self.product,
            quantity=1,
            unit_price=12000,
            delivery_date=date.today(),
        )
        Payment.objects.create(
            customer=customer,
            payment_date=date.today(),
            amount=20000,
        )

        response = self.client.get(
            reverse('deliveries:get_customer_balance'),
            {'customer_id': str(customer.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total_billed'], 12000)
        self.assertEqual(response.json()['total_paid'], 20000)
        self.assertEqual(response.json()['bf_balance'], 31600)
        self.assertEqual(response.json()['outstanding'], 23600)

    def save_individual_entry(self, payment_amount):
        return self.client.post(
            reverse('deliveries:daily_entry'),
            data={
                'save_type': 'individual',
                'entry_data': {
                    'customer_id': str(self.customer.pk),
                    'is_existing': True,
                    'selected_date': date.today().isoformat(),
                    'products': [{
                        'product_id': str(self.product.pk),
                        'quantity': 2,
                        'rate': 100,
                        'payment_amount': payment_amount,
                    }],
                },
            },
            content_type='application/json',
        )

    def test_same_amount_delivery_payments_are_distinct_and_linked(self):
        first_response = self.save_individual_entry(50)
        second_response = self.save_individual_entry(50)

        self.assertTrue(first_response.json()['success'])
        self.assertTrue(second_response.json()['success'])
        deliveries = Delivery.objects.filter(customer=self.customer)
        self.assertEqual(deliveries.count(), 2)
        self.assertEqual(Payment.objects.filter(delivery__in=deliveries).count(), 2)
        self.assertEqual(self.customer.get_outstanding_balance(), 300)

        entries_response = self.client.get(
            reverse('deliveries:get_daily_entries_api'),
            {'date': date.today().isoformat()},
        )
        entries = entries_response.json()['entries']
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(entry['type'] == 'delivery' for entry in entries))

    def test_edit_and_delete_delivery_keep_payment_balance_and_stock_synced(self):
        response = self.save_individual_entry(50)
        self.assertTrue(response.json()['success'])
        delivery = Delivery.objects.get(customer=self.customer)
        other_customer = Customer.objects.create(name='Updated Delivery Customer')

        update_response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(delivery.pk),
                'data': {
                    'customer_id': str(other_customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 2,
                    'unit_price': 100,
                    'empty_returned': 0,
                    'payment_amount': 75,
                    'payment_type': 'cash',
                    'delivery_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertTrue(update_response.json()['success'])
        self.assertEqual(self.customer.get_outstanding_balance(), 0)
        self.assertEqual(other_customer.get_outstanding_balance(), 125)
        linked_payment = Payment.objects.get(delivery=delivery)
        self.assertEqual(linked_payment.customer_id, other_customer.pk)
        self.assertEqual(linked_payment.amount, 75)

        delete_response = self.client.post(
            reverse('deliveries:delete_entry_api'),
            data={'entry_id': str(delivery.pk)},
            content_type='application/json',
        )

        self.assertTrue(delete_response.json()['success'])
        self.assertFalse(Payment.objects.filter(delivery=delivery).exists())
        self.assertEqual(other_customer.get_outstanding_balance(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)

    def test_editing_delivery_payment_to_zero_removes_linked_payment(self):
        response = self.save_individual_entry(50)
        self.assertTrue(response.json()['success'])
        delivery = Delivery.objects.get(customer=self.customer)

        update_response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data={
                'entry_id': str(delivery.pk),
                'data': {
                    'customer_id': str(self.customer.pk),
                    'product_id': str(self.product.pk),
                    'quantity': 2,
                    'unit_price': 100,
                    'payment_amount': 0,
                    'payment_type': 'cash',
                    'delivery_date': date.today().isoformat(),
                },
            },
            content_type='application/json',
        )

        self.assertTrue(update_response.json()['success'])
        self.assertFalse(Payment.objects.filter(delivery=delivery).exists())
        self.assertEqual(self.customer.get_outstanding_balance(), 200)

    def test_clear_entries_removes_linked_and_standalone_payments(self):
        response = self.save_individual_entry(50)
        self.assertTrue(response.json()['success'])
        Payment.objects.create(
            customer=self.customer,
            payment_date=date.today(),
            amount=25,
            created_by=self.user,
        )

        clear_response = self.client.post(
            reverse('deliveries:clear_entries_api'),
            data={'date': date.today().isoformat()},
            content_type='application/json',
        )

        self.assertTrue(clear_response.json()['success'])
        self.assertFalse(Delivery.objects.filter(customer=self.customer).exists())
        self.assertFalse(Payment.objects.filter(customer=self.customer).exists())
        self.assertEqual(self.customer.get_outstanding_balance(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)
