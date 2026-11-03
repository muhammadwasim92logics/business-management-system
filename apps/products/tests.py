from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer
from apps.deliveries.models import Delivery
from apps.suppliers.models import Purchase, Supplier
from .models import Factory, FactoryFillTransaction, Product


class ProductCreateViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='product-user',
            password='secret123',
        )
        self.client.force_login(user)

    def test_create_accepts_fields_rendered_by_product_form(self):
        response = self.client.post(reverse('products:add'), {
            'name': 'Direct Regulator',
            'unit_price': '2500',
            'purchase_price': '0',
            'stock_quantity': '10',
            'empty_stock_quantity': '0',
            'unit_weight_kg': '0',
            'stock_weight_kg': '0',
            'minimum_stock': '2',
            'is_sellable': 'on',
            'is_quantity_only': 'on',
        })

        self.assertRedirects(response, reverse('products:list'))
        product = Product.objects.get(name='DIRECT REGULATOR')
        self.assertEqual(product.opening_full_quantity, 0)
        self.assertEqual(product.opening_empty_quantity, 0)

    def test_create_accepts_filling_only_cylinder_product_flag(self):
        response = self.client.post(reverse('products:add'), {
            'name': 'LPG FILLING',
            'unit_price': '2500',
            'purchase_price': '0',
            'stock_quantity': '0',
            'empty_stock_quantity': '0',
            'unit_weight_kg': '0',
            'stock_weight_kg': '0',
            'minimum_stock': '2',
            'is_sellable': 'on',
            'is_filling_only': 'on',
        })

        self.assertRedirects(response, reverse('products:list'))
        product = Product.objects.get(name='LPG FILLING')
        self.assertTrue(product.is_filling_only)

    def test_create_rejects_negative_stock_quantity(self):
        response = self.client.post(reverse('products:add'), {
            'name': 'Negative Stock Product',
            'unit_price': '100',
            'stock_quantity': '-1',
            'empty_stock_quantity': '0',
            'minimum_stock': '5',
            'is_sellable': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stock quantity cannot be negative.')
        self.assertFalse(Product.objects.filter(name='NEGATIVE STOCK PRODUCT').exists())


class ProductUpdateViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='product-update-user',
            password='secret123',
        )
        self.client.force_login(user)

    def test_update_saves_product_with_existing_negative_stock(self):
        product = Product.objects.create(
            name='LPG FILLING',
            unit_price=2500,
            stock_quantity=-24,
            is_filling_only=True,
        )

        response = self.client.post(reverse('products:edit', args=[product.pk]), {
            'name': 'LPG FILLING UPDATED',
            'unit_price': '2700',
            'purchase_price': '0',
            'stock_quantity': '-24',
            'empty_stock_quantity': '0',
            'unit_weight_kg': '0',
            'stock_weight_kg': '0',
            'minimum_stock': '5',
            'is_sellable': 'on',
            'is_filling_only': 'on',
        })

        self.assertRedirects(response, reverse('products:list'))
        product.refresh_from_db()
        self.assertEqual(product.name, 'LPG FILLING UPDATED')
        self.assertEqual(product.unit_price, Decimal('2700'))
        self.assertEqual(product.stock_quantity, -24)


class ProductListViewTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username='product-list-user',
            password='secret123',
        )
        self.client.force_login(user)

    def test_search_filters_by_name_or_product_code(self):
        matching_product = Product.objects.create(name='Nitrogen Cylinder')
        Product.objects.create(name='Oxygen Cylinder')

        response = self.client.get(reverse('products:list'), {'q': 'nitrogen'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['products']), [matching_product])
        self.assertContains(response, matching_product.name)
        self.assertNotContains(response, 'Oxygen Cylinder')

        response = self.client.get(
            reverse('products:list'),
            {'q': matching_product.product_code},
        )

        self.assertEqual(list(response.context['products']), [matching_product])


class StockDetailsViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='stock-user', password='secret123')
        self.client.force_login(self.user)
        self.product = Product.objects.create(name='CO2', stock_quantity=1050)
        self.customer = Customer.objects.create(
            name='Gas Customer',
            mobile='03001234567',
            stn='STN-GAS-CUSTOMER',
        )
        session = self.client.session
        session['fbr_selected_customer_ids'] = [str(self.customer.pk)]
        session.save()
        self.supplier = Supplier.objects.create(name='Gas Supplier', mobile='03007654321')

        Purchase.objects.create(
            supplier=self.supplier,
            product=self.product,
            purchase_date=date(2026, 4, 10),
            quantity=100,
            unit_price=10,
            tax_type='with_tax',
        )
        Delivery.objects.create(
            customer=self.customer,
            product=self.product,
            delivery_date=date(2026, 4, 15),
            quantity=50,
            unit_price=20,
        )

    def test_stock_report_shows_bf_in_out_and_running_balance(self):
        response = self.client.get(reverse('products:stock_details'), {
            'product': 'co2',
            'start_date': '2026-04-01',
            'end_date': '2026-04-30',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['opening_balance'], Decimal('1000'))
        self.assertEqual(response.context['total_in'], Decimal('100'))
        self.assertEqual(response.context['total_out'], Decimal('50'))
        self.assertEqual(response.context['closing_balance'], Decimal('1050'))
        self.assertContains(response, 'Gas Supplier')
        self.assertContains(response, 'Gas Customer')
        self.assertContains(response, 'Balance brought forward')
        self.assertContains(response, '<th>Unit</th>', html=True)
        self.assertContains(response, '<td>KG</td>', html=True)

    def test_oxygen_liquid_category_combines_all_oxygen_family_products(self):
        nitrogen = Product.objects.create(name='Nitrogen 50KG', stock_quantity=200, is_purchasable=True)
        oxygen = Product.objects.create(name='Oxygen 50KG', stock_quantity=300, is_purchasable=True)
        Purchase.objects.create(
            supplier=self.supplier,
            product=nitrogen,
            purchase_date=date(2026, 4, 12),
            quantity=20,
            unit_price=10,
            tax_type='with_tax',
        )
        Delivery.objects.create(
            customer=self.customer,
            product=oxygen,
            delivery_date=date(2026, 4, 16),
            quantity=30,
            unit_price=20,
        )

        response = self.client.get(reverse('products:stock_details'), {'product': 'oxygen_liquid'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['product_name'], 'OXYGEN LIQUID')
        self.assertEqual(response.context['opening_balance'], Decimal('484.42'))
        self.assertEqual(response.context['total_in'], Decimal('20'))
        self.assertEqual(response.context['total_out'], Decimal('4.42'))
        self.assertEqual(response.context['unit'], 'M3')

    def test_stock_report_out_uses_fbr_invoice_quantity(self):
        product = Product.objects.create(name='CO2 25KG', stock_quantity=100)
        Delivery.objects.create(
            customer=self.customer,
            product=product,
            delivery_date=date(2026, 4, 17),
            quantity=2,
            unit_price=236,
        )

        response = self.client.get(reverse('products:stock_details'), {
            'product': 'co2',
            'start_date': '2026-04-01',
            'end_date': '2026-04-30',
        })

        self.assertEqual(response.context['movements'][-1]['out_qty'], Decimal('50'))
        self.assertEqual(response.context['total_out'], Decimal('100'))

    def test_stock_report_excludes_purchases_without_sales_tax(self):
        Purchase.objects.create(
            supplier=self.supplier,
            product=self.product,
            purchase_date=date(2026, 4, 11),
            quantity=75,
            unit_price=10,
            tax_type='none',
        )

        response = self.client.get(reverse('products:stock_details'), {
            'product': 'co2',
            'start_date': '2026-04-01',
            'end_date': '2026-04-30',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_in'], Decimal('100'))


    def test_stock_report_excludes_out_movements_for_non_tax_customers(self):
        non_tax_customer = Customer.objects.create(
            name='Non Tax Customer',
            mobile='03008888888',
        )
        Delivery.objects.create(
            customer=non_tax_customer,
            product=self.product,
            delivery_date=date(2026, 4, 20),
            quantity=25,
            unit_price=20,
        )

        response = self.client.get(reverse('products:stock_details'), {
            'product': 'co2',
            'start_date': '2026-04-01',
            'end_date': '2026-04-30',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_out'], Decimal('50'))
        self.assertNotContains(response, 'Non Tax Customer')

    def test_stock_report_excludes_products_outside_fbr_gas_categories(self):
        other_product = Product.objects.create(
            name='Mantrap',
            stock_quantity=25,
            is_purchasable=True,
        )

        response = self.client.get(reverse('products:stock_details'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Mantrap')

        response = self.client.get(reverse('products:stock_details'), {
            'product': str(other_product.pk),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get('product'))
        self.assertEqual(response.context['movements'], [])

    def test_stock_overview_separates_oxygen_and_nitrogen_sizes(self):
        oxygen_small = Product.objects.create(name='Oxygen Small', product_code='GAS-001', stock_quantity=0)
        oxygen_big = Product.objects.create(name='Oxygen Big', product_code='GAS-002', stock_quantity=0)
        oxygen = Product.objects.create(name='Oxygen', product_code='GAS-008', stock_quantity=0)
        nitrogen_small = Product.objects.create(name='Nitrogen Small', product_code='GAS-003', stock_quantity=0)
        nitrogen = Product.objects.create(name='Nitrogen', product_code='GAS-009', stock_quantity=0)
        lpg = Product.objects.create(name='LPG', product_code='GAS-004', stock_quantity=0)
        lpg_45 = Product.objects.create(name='LPG 45KG', product_code='GAS-007', stock_quantity=0)
        co2_10 = Product.objects.create(name='CO2 10KG', product_code='GAS-005', stock_quantity=0)
        Product.objects.create(name='Argon', product_code='GAS-006', stock_quantity=10)

        Purchase.objects.create(
            supplier=self.supplier, product=oxygen_small, purchase_date=date(2026, 4, 10),
            quantity=2, unit_price=10,
        )
        Purchase.objects.create(
            supplier=self.supplier, product=oxygen_big, purchase_date=date(2026, 4, 10),
            quantity=3, unit_price=10,
        )
        Purchase.objects.create(
            supplier=self.supplier, product=nitrogen_small, purchase_date=date(2026, 4, 10),
            quantity=4, unit_price=10,
        )
        Purchase.objects.create(
            supplier=self.supplier, product=oxygen, purchase_date=date(2026, 4, 10),
            quantity=10, unit_price=10,
        )
        Purchase.objects.create(
            supplier=self.supplier, product=nitrogen, purchase_date=date(2026, 4, 10),
            quantity=10, unit_price=10,
        )
        Purchase.objects.create(
            supplier=self.supplier, product=lpg, purchase_date=date(2026, 4, 10),
            quantity=90, unit_price=10,
        )
        Purchase.objects.create(
            supplier=self.supplier, product=co2_10, purchase_date=date(2026, 4, 10),
            quantity=20, unit_price=10,
        )
        Delivery.objects.create(
            customer=self.customer, product=oxygen_small, delivery_date=date(2026, 4, 15),
            quantity=1, unit_price=10,
        )
        Delivery.objects.create(
            customer=self.customer, product=lpg_45, delivery_date=date(2026, 4, 15),
            quantity=2, unit_price=10,
        )
        Delivery.objects.create(
            customer=self.customer, product=co2_10, delivery_date=date(2026, 4, 15),
            quantity=1, unit_price=10,
        )

        response = self.client.get(reverse('products:stock_overview'))

        self.assertEqual(response.status_code, 200)
        rows = {row['product_name']: row for row in response.context['stock_rows']}
        self.assertEqual(set(rows), {'CO2', 'LPG', 'NITROGEN', 'OXYGEN'})
        self.assertEqual(rows['OXYGEN']['purchased'], Decimal('50.684'))
        self.assertEqual(rows['OXYGEN']['dispatched'], Decimal('6.8'))
        self.assertEqual(rows['OXYGEN']['current_stock'], Decimal('43.884'))
        self.assertEqual(rows['NITROGEN']['purchased'], Decimal('35.64'))
        self.assertEqual(rows['LPG']['purchased'], Decimal('90'))
        self.assertEqual(rows['LPG']['dispatched'], Decimal('90'))
        self.assertEqual(rows['LPG']['current_stock'], Decimal('0'))
        self.assertEqual(rows['CO2']['current_stock'], Decimal('60'))
        self.assertContains(response, 'Small: 6.8 m³')
        self.assertContains(response, 'Big: 9.9 m³')


class FactoryFillViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='factory-user', password='secret123')
        self.client.force_login(self.user)
        self.factory = Factory.objects.create(name='Primary Factory')
        self.product = Product.objects.create(
            name='Argon', stock_quantity=50, empty_stock_quantity=50,
        )

    def test_factory_fill_updates_both_stock_pools_and_history(self):
        response = self.client.post(reverse('products:factory_fill'), {
            'action': 'record_fill',
            'factory': self.factory.pk,
            'product': self.product.pk,
            'transaction_date': '2026-08-27',
            'empty_sent': '30',
            'full_received': '30',
            'invoice_number': 'FF-2026-001',
            'notes': 'August batch',
        })

        self.assertRedirects(response, reverse('products:factory_fill'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.empty_stock_quantity, 20)
        self.assertEqual(self.product.stock_quantity, 80)
        self.assertEqual(FactoryFillTransaction.objects.count(), 1)
        self.assertEqual(FactoryFillTransaction.objects.get().invoice_number, 'FF-2026-001')

    def test_factory_fill_rejects_more_empty_cylinders_than_available(self):
        self.client.post(reverse('products:factory_fill'), {
            'action': 'record_fill',
            'factory': self.factory.pk,
            'product': self.product.pk,
            'transaction_date': '2026-08-27',
            'empty_sent': '51',
            'full_received': '51',
        })

        self.product.refresh_from_db()
        self.assertEqual(self.product.empty_stock_quantity, 50)
        self.assertEqual(self.product.stock_quantity, 50)
        self.assertEqual(FactoryFillTransaction.objects.count(), 0)

    def test_factory_fill_allows_blank_empty_cylinders(self):
        response = self.client.post(reverse('products:factory_fill'), {
            'action': 'record_fill',
            'factory': self.factory.pk,
            'product': self.product.pk,
            'transaction_date': '2026-08-27',
            'empty_sent': '',
            'full_received': '10',
        })

        self.assertRedirects(response, reverse('products:factory_fill'))
        fill = FactoryFillTransaction.objects.get()
        self.assertEqual(fill.empty_sent, 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.empty_stock_quantity, 50)
        self.assertEqual(self.product.stock_quantity, 60)

    def test_factory_fill_allows_zero_empty_cylinders(self):
        response = self.client.post(reverse('products:factory_fill'), {
            'action': 'record_fill',
            'factory': self.factory.pk,
            'product': self.product.pk,
            'transaction_date': '2026-08-27',
            'empty_sent': '0',
            'full_received': '10',
        })

        self.assertRedirects(response, reverse('products:factory_fill'))
        self.assertEqual(FactoryFillTransaction.objects.get().empty_sent, 0)

    def test_factory_fill_edit_reverses_old_stock_and_applies_new_stock(self):
        fill = FactoryFillTransaction.objects.create(
            factory=self.factory,
            product=self.product,
            transaction_date='2026-08-27',
            empty_sent=30,
            full_received=30,
            created_by=self.user,
        )
        self.product.empty_stock_quantity -= 30
        self.product.stock_quantity += 30
        self.product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])

        response = self.client.post(reverse('products:factory_fill_edit', args=[fill.pk]), {
            'factory': self.factory.pk,
            'product': self.product.pk,
            'transaction_date': '2026-08-29',
            'empty_sent': '10',
            'full_received': '5',
            'invoice_number': 'FF-2026-002',
            'notes': 'Updated batch',
        })

        self.assertRedirects(response, reverse('products:factory_detail', args=[self.factory.pk]))
        self.product.refresh_from_db()
        fill.refresh_from_db()
        self.assertEqual(self.product.empty_stock_quantity, 40)
        self.assertEqual(self.product.stock_quantity, 55)
        self.assertEqual(fill.empty_sent, 10)
        self.assertEqual(fill.full_received, 5)
        self.assertEqual(fill.invoice_number, 'FF-2026-002')
        self.assertEqual(fill.notes, 'Updated batch')

    def test_factory_fill_delete_reverses_stock_and_removes_history(self):
        fill = FactoryFillTransaction.objects.create(
            factory=self.factory,
            product=self.product,
            transaction_date='2026-08-27',
            empty_sent=30,
            full_received=30,
            created_by=self.user,
        )
        self.product.empty_stock_quantity -= 30
        self.product.stock_quantity += 30
        self.product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])

        response = self.client.post(reverse('products:factory_fill_delete', args=[fill.pk]))

        self.assertRedirects(response, reverse('products:factory_detail', args=[self.factory.pk]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.empty_stock_quantity, 50)
        self.assertEqual(self.product.stock_quantity, 50)
        self.assertFalse(FactoryFillTransaction.objects.filter(pk=fill.pk).exists())

    def test_factory_fill_delete_reverses_stock_when_received_cylinders_were_used(self):
        fill = FactoryFillTransaction.objects.create(
            factory=self.factory,
            product=self.product,
            transaction_date='2026-08-27',
            empty_sent=10,
            full_received=30,
            created_by=self.user,
        )
        self.product.empty_stock_quantity -= 10
        self.product.stock_quantity = 20
        self.product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])

        response = self.client.post(reverse('products:factory_fill_delete', args=[fill.pk]))

        self.assertRedirects(response, reverse('products:factory_detail', args=[self.factory.pk]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.empty_stock_quantity, 50)
        self.assertEqual(self.product.stock_quantity, -10)
        self.assertFalse(FactoryFillTransaction.objects.filter(pk=fill.pk).exists())

    def test_factory_fill_edit_allows_date_change_when_stock_was_used(self):
        fill = FactoryFillTransaction.objects.create(
            factory=self.factory,
            product=self.product,
            transaction_date='2026-08-27',
            empty_sent=0,
            full_received=5,
            created_by=self.user,
        )
        self.product.stock_quantity = -15
        self.product.save(update_fields=['stock_quantity', 'updated_at'])

        response = self.client.post(reverse('products:factory_fill_edit', args=[fill.pk]), {
            'factory': self.factory.pk,
            'product': self.product.pk,
            'transaction_date': '2026-08-29',
            'empty_sent': '0',
            'full_received': '5',
        })

        self.assertRedirects(response, reverse('products:factory_detail', args=[self.factory.pk]))
        fill.refresh_from_db()
        self.assertEqual(str(fill.transaction_date), '2026-08-29')

    def test_product_stock_api_returns_current_pools(self):
        response = self.client.get(reverse('products:factory_product_stock'), {'product': self.product.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['empty_stock_quantity'], 50)
        self.assertEqual(response.json()['stock_quantity'], 50)
