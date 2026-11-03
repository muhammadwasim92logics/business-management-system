from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer
from apps.deliveries.models import Delivery
from apps.payments.models import Payment
from apps.products.models import Product


class DashboardPendingAmountTests(TestCase):
    def test_pending_amount_includes_all_customer_balances(self):
        user = get_user_model().objects.create_user(username='dashboard-user', password='secret123')
        self.client.force_login(user)
        product = Product.objects.create(name='Dashboard Product', unit_price=250)
        customer_with_payment = Customer.objects.create(
            name='Customer With Payment',
            bf_balance=Decimal('1000'),
            previous_balance=Decimal('200'),
        )
        customer_with_opening_balance = Customer.objects.create(
            name='Customer With Opening Balance',
            bf_balance=Decimal('2000'),
        )
        Delivery.objects.create(
            customer=customer_with_payment,
            product=product,
            delivery_date=date.today(),
            quantity=2,
            unit_price=Decimal('250'),
        )
        Delivery.objects.create(
            customer=customer_with_opening_balance,
            product=product,
            delivery_date=date.today(),
            quantity=1,
            unit_price=Decimal('100'),
        )
        Payment.objects.create(
            customer=customer_with_payment,
            payment_date=date.today(),
            amount=Decimal('250'),
        )

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['pending_amount'], Decimal('3550'))


class DashboardCylinderSalesTests(TestCase):
    def test_cylinder_sales_summarize_recent_deliveries_and_returns(self):
        user = get_user_model().objects.create_user(username='dashboard-sales-user', password='secret123')
        self.client.force_login(user)
        customer = Customer.objects.create(name='Cylinder Sales Customer')
        cylinder = Product.objects.create(name='LPG 12KG')
        accessory = Product.objects.create(name='Regulator', is_quantity_only=True)
        filling_product = Product.objects.create(name='LPG FILLING', is_filling_only=True)
        today = date.today()

        Delivery.objects.create(
            customer=customer,
            product=cylinder,
            delivery_date=today,
            quantity=3,
            unit_price=100,
            full_returned=1,
        )
        Delivery.objects.create(
            customer=customer,
            product=cylinder,
            delivery_date=today,
            quantity=2,
            unit_price=100,
        )
        Delivery.objects.create(
            customer=customer,
            product=cylinder,
            delivery_date=today - timedelta(days=14),
            quantity=8,
            unit_price=100,
        )
        Delivery.objects.create(
            customer=customer,
            product=accessory,
            delivery_date=today,
            quantity=10,
            unit_price=100,
        )
        Delivery.objects.create(
            customer=customer,
            product=filling_product,
            delivery_date=today,
            quantity=5,
            unit_price=100,
        )

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['cylinder_sales']), [{
            'product__name': 'LPG 12KG',
            'delivered': Decimal('5'),
            'total_full_returned': Decimal('1'),
            'net_sold': Decimal('4'),
        }])
        self.assertContains(response, 'Net Sold')
        self.assertContains(response, 'LPG 12KG')