from datetime import date, timedelta
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer
from apps.cylinders.models import CylinderLedger
from apps.deliveries.models import Delivery
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.products.models import Product


class CustomerListDateFilterTests(TestCase):
    def test_customer_management_search_dropdown_filters_by_selected_customer(self):
        user = get_user_model().objects.create_user(username='customer-dropdown-search', password='secret123')
        self.client.force_login(user)
        matching_customer = Customer.objects.create(
            name='Alpha Customer',
            customer_code='CUST-1001',
            mobile='03000000001',
        )
        other_customer = Customer.objects.create(
            name='Beta Customer',
            customer_code='CUST-1002',
            mobile='03000000002',
        )

        response = self.client.get(
            reverse('customers:list'),
            {'customer_id': str(matching_customer.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['customers']), [matching_customer])
        self.assertEqual(
            list(response.context['customer_options']),
            [matching_customer, other_customer],
        )
        self.assertContains(response, 'Search Customer')
        self.assertContains(response, f'value="{matching_customer.pk}" selected')

    def test_customer_list_supports_date_range_and_quick_filters(self):
        user = get_user_model().objects.create_user(username='customerfilter', password='secret123')
        self.client.force_login(user)

        today_customer = Customer.objects.create(name='Today Customer', mobile='03000000001')
        older_customer = Customer.objects.create(name='Older Customer', mobile='03000000002')

        today_customer.registration_date = date.today()
        today_customer.save(update_fields=['registration_date'])

        older_customer.registration_date = date.today() - timedelta(days=20)
        older_customer.save(update_fields=['registration_date'])

        response = self.client.get(
            reverse('customers:list'),
            {'date_from': date.today().isoformat(), 'date_to': date.today().isoformat()}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Today')
        self.assertContains(response, 'This Week')
        self.assertContains(response, 'This Month')
        self.assertContains(response, 'date_from')
        self.assertContains(response, 'date_to')
        self.assertContains(response, today_customer.name)
        self.assertEqual(list(response.context['customers']), [today_customer])

    def test_quick_filter_date_ranges_use_calendar_periods(self):
        user = get_user_model().objects.create_user(username='customer-quick-filter', password='secret123')
        self.client.force_login(user)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        today_customer = Customer.objects.create(name='Created Today')
        week_customer = Customer.objects.create(name='Created This Week')
        month_customer = Customer.objects.create(name='Created This Month')
        older_customer = Customer.objects.create(name='Created Earlier')

        dated_customers = (
            (today_customer, today),
            (week_customer, week_start),
            (month_customer, month_start),
            (older_customer, min(week_start, month_start) - timedelta(days=1)),
        )
        for customer, created_date in dated_customers:
            customer.registration_date = created_date
            customer.save(update_fields=['registration_date'])

        cases = (
            (today, today),
            (week_start, today),
            (month_start, today),
        )
        for date_from, date_to in cases:
            expected_names = {
                customer.name for customer, created_date in dated_customers
                if date_from <= created_date <= date_to
            }
            response = self.client.get(reverse('customers:list'), {
                'date_from': date_from.isoformat(),
                'date_to': date_to.isoformat(),
            })
            self.assertEqual(response.status_code, 200)
            result_names = {customer.name for customer in response.context['customers']}
            self.assertEqual(result_names, expected_names)

    def test_status_filters_match_customer_display_status_and_boundaries(self):
        user = get_user_model().objects.create_user(username='customer-status-filter', password='secret123')
        self.client.force_login(user)
        today = date.today()
        customers_by_status = {'active': set(), 'inactive': set(), 'not_coming': set()}

        for name, last_activity, expected_status in (
            ('Active Today', today, 'active'),
            ('Active Boundary', today - timedelta(days=6), 'active'),
            ('Inactive Boundary', today - timedelta(days=7), 'inactive'),
            ('Inactive Recent', today - timedelta(days=29), 'inactive'),
            ('Not Coming Boundary', today - timedelta(days=30), 'not_coming'),
            ('Not Coming Older', today - timedelta(days=45), 'not_coming'),
        ):
            customer = Customer.objects.create(name=name)
            customer.last_activity_date = last_activity
            customer.save(update_fields=['last_activity_date'])
            self.assertEqual(customer.get_status()[0], expected_status)
            customers_by_status[expected_status].add(name)

        customer_without_activity = Customer.objects.create(name='New Customer Without Activity')
        self.assertIsNone(customer_without_activity.last_activity_date)
        customers_by_status['active'].add(customer_without_activity.name)

        for status, expected_names in customers_by_status.items():
            response = self.client.get(reverse('customers:list'), {'status': status})
            self.assertEqual(response.status_code, 200)
            result_names = {customer.name for customer in response.context['customers']}
            self.assertEqual(result_names, expected_names)


class CustomerEditTests(TestCase):
    def test_edit_form_persists_customer_changes(self):
        user = get_user_model().objects.create_user(username='customer-edit-user', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Original Customer', mobile='03000000001')
        edit_url = reverse('customers:edit', args=[customer.pk])
        form_response = self.client.get(edit_url)
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, 'type="date"')
        self.assertContains(form_response, customer.bf_date.isoformat())
        updated_bf_date = customer.bf_date - timedelta(days=1)

        response = self.client.post(edit_url, {
            'name': 'Updated Customer',
            'mobile': '03000000002',
            'alternate_mobile': '',
            'address': 'Updated address',
            'area': 'Updated area',
            'stn': '',
            'ntn': '',
            'notes': '',
            'previous_balance': '0.00',
            'security_deposit': '0.00',
            'personal_cylinders': '0',
            'bf_balance': '0.00',
            'bf_cylinders': '{}',
            'bf_date': updated_bf_date.isoformat(),
        }, follow=True)

        self.assertEqual(response.redirect_chain, [(reverse('customers:list'), 302)])
        self.assertContains(response, 'Customer updated successfully.')
        self.assertContains(response, 'alert-success customer-toast')
        customer.refresh_from_db()
        self.assertEqual(customer.name, 'Updated Customer')
        self.assertEqual(customer.mobile, '03000000002')
        self.assertEqual(customer.address, 'Updated address')
        self.assertEqual(customer.bf_date, updated_bf_date)

    def test_invalid_customer_edit_shows_field_errors(self):
        user = get_user_model().objects.create_user(username='customer-edit-error-user', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Customer With Invalid Edit')

        response = self.client.post(reverse('customers:edit', args=[customer.pk]), {
            'name': 'Should Not Save',
            'mobile': '',
            'alternate_mobile': '',
            'address': '',
            'area': '',
            'stn': '',
            'ntn': '',
            'notes': '',
            'previous_balance': '0.00',
            'security_deposit': '0.00',
            'personal_cylinders': '0',
            'bf_balance': '0.00',
            'bf_cylinders': '{invalid json',
            'bf_date': customer.bf_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enter a valid JSON.')
        self.assertContains(response, 'Customer update failed. Please correct the highlighted fields.')
        self.assertContains(response, 'alert-danger customer-toast')
        customer.refresh_from_db()
        self.assertEqual(customer.name, 'Customer With Invalid Edit')


class CustomerLedgerPaymentMatchingTests(TestCase):
    def test_nearby_standalone_payment_is_not_assigned_to_another_delivery(self):
        user = get_user_model().objects.create_user(username='ledger-payment-match-user', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Ledger Payment Match Customer')
        product = Product.objects.create(name='Ledger Payment Match Product', unit_price=100)
        selected_date = date.today()
        paid_delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=selected_date,
            quantity=10,
            unit_price=100,
            payment_amount=5000,
            created_by=user,
        )
        unpaid_delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=selected_date,
            quantity=2,
            unit_price=100,
            payment_amount=0,
            created_by=user,
        )
        linked_payment = Payment.objects.create(
            customer=customer,
            delivery=paid_delivery,
            payment_date=selected_date,
            amount=5000,
            notes='Payment for Ledger Payment Match Product',
            created_by=user,
        )
        standalone_payment = Payment.objects.create(
            customer=customer,
            payment_date=selected_date,
            amount=175,
            notes='Separate payment',
            created_by=user,
        )

        response = self.client.get(reverse('customers:ledger'), {
            'customer_id': str(customer.pk),
        })

        self.assertEqual(response.status_code, 200)
        transactions = response.context['transactions']
        delivery_rows = {row['id']: row for row in transactions if row['type'] == 'delivery'}
        payment_rows = [row for row in transactions if row['type'] == 'payment']
        self.assertEqual(delivery_rows[str(paid_delivery.pk)]['payment_recv'], 5000)
        self.assertEqual(delivery_rows[str(unpaid_delivery.pk)]['payment_recv'], 0)
        self.assertEqual([row['id'] for row in payment_rows], [str(standalone_payment.pk)])
        self.assertNotIn(linked_payment.pk, [row.get('payment_obj').pk for row in payment_rows])


class CustomerDeletionTests(TestCase):
    def test_delete_customer_removes_related_records_without_restoring_stock(self):
        user = get_user_model().objects.create_user(username='deletecustomer', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(
            name='Delete Customer',
            bf_cylinders={'CO2 10KG': -2},
            bf_balance=1000,
        )
        product = Product.objects.create(name='CO2 10KG', stock_quantity=150)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=date.today(),
            quantity=1,
            unit_price=100,
        )
        payment = Payment.objects.create(
            customer=customer,
            payment_date=date.today(),
            amount=50,
        )
        cylinder_entry = CylinderLedger.objects.create(
            customer=customer,
            product=product,
            delivery=delivery,
            full_out=1,
        )
        notification = Notification.objects.create(
            type=Notification.Type.PENDING_PAYMENT,
            title='Pending payment',
            message='Customer has a balance',
            customer=customer,
        )

        response = self.client.post(reverse('customers:delete', args=[customer.pk]))

        self.assertRedirects(response, reverse('customers:list'))
        self.assertFalse(Customer.objects.filter(pk=customer.pk).exists())
        self.assertFalse(Delivery.objects.filter(pk=delivery.pk).exists())
        self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())
        self.assertFalse(CylinderLedger.objects.filter(pk=cylinder_entry.pk).exists())
        self.assertFalse(Notification.objects.filter(pk=notification.pk).exists())
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 150)


class CustomerLedgerActionColumnTests(TestCase):
    def test_customer_ledger_renders_edit_delete_action_column(self):
        user = get_user_model().objects.create_user(username='ledger-customer-action-user', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Ledger Action Customer', mobile='03000000001')
        product = Product.objects.create(name='Test Product', unit_price=100, stock_quantity=5)
        Delivery.objects.create(
            customer=customer,
            product=product,
            quantity=2,
            unit_price=100,
            delivery_date=date.today(),
            delivery_amount=200,
            payment_amount=0,
            created_by=user,
        )

        response = self.client.get(reverse('customers:ledger'), {'customer_id': str(customer.pk)})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Action')
        self.assertContains(response, 'btn-ledger-edit-delivery')
        self.assertContains(response, 'btn-ledger-delete-delivery')
        self.assertContains(response, 'editLedgerCustomer')
        self.assertContains(response, f'data-customer-id="{customer.pk}"')

    def test_ledger_edit_can_reassign_delivery_and_linked_records_to_another_customer(self):
        user = get_user_model().objects.create_user(username='ledger-reassign-user', password='secret123')
        self.client.force_login(user)
        original_customer = Customer.objects.create(name='Original Ledger Customer')
        destination_customer = Customer.objects.create(name='Destination Ledger Customer')
        product = Product.objects.create(name='Reassignment Cylinder', unit_price=100, stock_quantity=5)
        delivery = Delivery.objects.create(
            customer=original_customer,
            product=product,
            quantity=1,
            unit_price=100,
            delivery_date=date.today(),
            payment_amount=25,
            created_by=user,
        )
        cylinder_entry = CylinderLedger.objects.create(
            customer=original_customer,
            product=product,
            delivery=delivery,
            full_out=1,
        )
        payment = Payment.objects.create(
            customer=original_customer,
            delivery=delivery,
            payment_date=date.today(),
            amount=25,
            created_by=user,
        )

        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data=json.dumps({
                'entry_id': str(delivery.pk),
                'data': {
                    'customer_id': str(destination_customer.pk),
                    'delivery_date': date.today().isoformat(),
                    'payment_amount': 25,
                    'payment_type': 'cash',
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'], response.json())
        delivery.refresh_from_db()
        cylinder_entry.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(delivery.customer, destination_customer)
        self.assertEqual(cylinder_entry.customer, destination_customer)
        self.assertEqual(payment.customer, destination_customer)
        self.assertEqual(response.json()['entry']['customer_id'], str(destination_customer.pk))

    def test_ledger_edit_can_reassign_standalone_payment_to_another_customer(self):
        user = get_user_model().objects.create_user(username='ledger-payment-reassign', password='secret123')
        self.client.force_login(user)
        original_customer = Customer.objects.create(name='Original Payment Customer')
        destination_customer = Customer.objects.create(name='Destination Payment Customer')
        payment = Payment.objects.create(
            customer=original_customer,
            payment_date=date.today(),
            amount=75,
            created_by=user,
        )

        response = self.client.post(
            reverse('deliveries:update_entry_api'),
            data=json.dumps({
                'entry_id': str(payment.pk),
                'data': {
                    'customer_id': str(destination_customer.pk),
                    'delivery_date': date.today().isoformat(),
                    'payment_amount': 75,
                    'payment_type': 'cash',
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'], response.json())
        payment.refresh_from_db()
        self.assertEqual(payment.customer, destination_customer)

class CustomerLedgerReturnTests(TestCase):
    def test_customer_ledger_prefers_delivery_invoice_field_for_transaction_invoice_no(self):
        user = get_user_model().objects.create_user(username='ledgerinvoice', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Invoice Ledger Customer')
        product = Product.objects.create(name='CO2 10KG', stock_quantity=10)

        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=date.today(),
            quantity=1,
            unit_price=100,
            delivery_no='DEL-1001',
            invoice_no='INV-LEDGER-900',
        )

        response = self.client.get(reverse('customers:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        transaction = next(item for item in response.context['transactions'] if item['type'] == 'delivery')
        self.assertEqual(transaction['invoice_no'], delivery.invoice_no)
        self.assertNotEqual(transaction['invoice_no'], delivery.delivery_no)

    def test_backdated_entries_use_business_date_in_ledger(self):
        user = get_user_model().objects.create_user(username='backdatedledger', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Backdated Ledger Customer')
        product = Product.objects.create(name='CO2 10KG', stock_quantity=10)
        old_date = date.today() - timedelta(days=3)

        Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=old_date,
            quantity=1,
            unit_price=100,
        )
        Payment.objects.create(
            customer=customer,
            payment_date=old_date,
            amount=25,
        )

        response = self.client.get(reverse('customers:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        transactions = [item for item in response.context['transactions'] if not item['is_bf']]
        self.assertEqual({item['date'] for item in transactions}, {old_date.strftime('%d/%m/%Y')})

    def test_customer_owned_return_appears_in_ledger(self):
        user = get_user_model().objects.create_user(username='ledgerreturn', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Ledger Return Customer')
        product = Product.objects.create(name='CO2 10KG', stock_quantity=10)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=date.today(),
            quantity=1,
            unit_price=0,
            cylinder_movement_type='customer_returned',
        )
        CylinderLedger.objects.create(
            customer=customer,
            product=product,
            delivery=delivery,
            ownership_movement='customer_returned',
            ownership_quantity=2,
        )

        response = self.client.get(reverse('customers:ledger'), {'customer_id': customer.pk})

        self.assertEqual(response.status_code, 200)
        transaction = next(item for item in response.context['transactions'] if item['type'] == 'delivery')
        self.assertEqual(transaction['empty'], 2)
        summary = next(iter(response.context['product_summary']))
        self.assertEqual(summary['returns'], 2)
        self.assertEqual(response.context['net_cylinders'], 2)

    def test_customer_profile_shows_owned_return_in_history_and_summary(self):
        user = get_user_model().objects.create_user(username='profilereturn', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Profile Return Customer')
        product = Product.objects.create(name='CO2 10KG', stock_quantity=10)
        delivery = Delivery.objects.create(
            customer=customer,
            product=product,
            delivery_date=date.today(),
            quantity=0,
            unit_price=0,
            cylinder_movement_type='customer_returned',
        )
        CylinderLedger.objects.create(
            customer=customer,
            product=product,
            delivery=delivery,
            ownership_movement='customer_returned',
            ownership_quantity=2,
        )

        response = self.client.get(reverse('customers:detail', args=[customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_cylinders_returned'], 2)
        self.assertEqual(response.context['net_cylinders'], 2)
        summary = next(iter(response.context['product_summary']))
        self.assertEqual(summary['current'], 2)
        self.assertEqual(response.context['deliveries'][0].display_empty_returned, 2)


class BulkBFSetupTests(TestCase):
    def test_bulk_setup_allows_multiple_customers_without_mobile(self):
        user = get_user_model().objects.create_user(username='bulkbf', password='secret123')
        self.client.force_login(user)

        response = self.client.post(
            reverse('customers:bf_setup'),
            {
                'customer_name_1': 'First Customer',
                'customer_mobile_1': '',
                'customer_name_2': 'Second Customer',
                'customer_mobile_2': '',
            }
        )

        self.assertEqual(response.status_code, 302)
        customers = Customer.objects.filter(name__in=['First Customer', 'Second Customer'])
        self.assertEqual(customers.count(), 2)
        self.assertEqual(customers.exclude(mobile='').count(), 0)

    def test_bulk_setup_rejects_only_exact_name_and_mobile_duplicate(self):
        Customer.objects.create(name='Existing Customer', mobile='03000000001')
        user = get_user_model().objects.create_user(username='bulkbfduplicates', password='secret123')
        self.client.force_login(user)

        self.client.post(
            reverse('customers:bf_setup'),
            {
                'customer_name_1': 'Existing Customer',
                'customer_mobile_1': '03000000001',
                'customer_name_2': 'Existing Customer',
                'customer_mobile_2': '03000000002',
                'customer_name_3': 'Different Customer',
                'customer_mobile_3': '03000000001',
            }
        )

        self.assertFalse(Customer.objects.filter(name='Existing Customer', mobile='03000000001').count() > 1)
        self.assertTrue(Customer.objects.filter(name='Existing Customer', mobile='03000000002').exists())
        self.assertTrue(Customer.objects.filter(name='Different Customer', mobile='03000000001').exists())

    def test_bulk_setup_rejects_duplicate_name_when_mobile_is_blank(self):
        Customer.objects.create(name='No Mobile Customer', mobile='')
        user = get_user_model().objects.create_user(username='bulkbfblankduplicate', password='secret123')
        self.client.force_login(user)

        self.client.post(
            reverse('customers:bf_setup'),
            {
                'customer_name_1': 'No Mobile Customer',
                'customer_mobile_1': '',
            }
        )

        self.assertEqual(Customer.objects.filter(name='No Mobile Customer').count(), 1)

    def test_single_bf_setup_rejects_exact_duplicate(self):
        Customer.objects.create(name='Existing Customer', mobile='03000000001')
        user = get_user_model().objects.create_user(username='singlebfduplicate', password='secret123')
        self.client.force_login(user)

        response = self.client.post(
            reverse('customers:save_bf_customer_api'),
            data={
                'name': 'Existing Customer',
                'mobile': '03000000001',
            },
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertEqual(Customer.objects.filter(name='Existing Customer', mobile='03000000001').count(), 1)

    def test_bf_cylinder_signs_are_preserved_in_customer_balance(self):
        customer = Customer.objects.create(
            name='Signed Cylinders Customer',
            bf_cylinders={'Argon': -3, 'CO2': 2},
        )

        self.assertEqual(customer.get_cylinder_balance(), {'Argon': -3, 'CO2': 2})

    def test_customer_profile_shows_cylinder_ownership_by_sign(self):
        customer = Customer.objects.create(
            name='Profile Cylinders Customer',
            bf_cylinders={'Argon': -3, 'CO2': 2},
        )
        user = get_user_model().objects.create_user(username='profilecylinders', password='secret123')
        self.client.force_login(user)

        response = self.client.get(reverse('customers:detail', args=[customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cylinders_with_customer'], 2)
        self.assertEqual(response.context['cylinders_at_company'], 3)
        self.assertContains(response, 'Company cylinders customer must return')
        self.assertContains(response, 'Customer cylinders held by company')
