from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.customers.models import Customer
from apps.products.models import Product

from .models import CylinderLedger


class CylinderDashboardPerformanceTests(TestCase):
    def test_dashboard_query_count_stays_bounded_for_many_customer_product_pairs(self):
        user = get_user_model().objects.create_user(username='cylinder-dashboard-user', password='secret123')
        self.client.force_login(user)
        products = [
            Product.objects.create(
                name=f'Dashboard Cylinder {index}',
                product_code=f'CYL-DASH-{index:04d}',
                stock_quantity=20 if index == 0 else 0,
                opening_full_quantity=20 if index == 0 else 0,
            )
            for index in range(12)
        ]
        customers = [
            Customer.objects.create(
                name=f'Dashboard Customer {index}',
                bf_cylinders={products[0].name: 1},
            )
            for index in range(12)
        ]
        for customer in customers:
            CylinderLedger.objects.create(
                customer=customer,
                product=products[0],
                full_out=3,
                empty_in=1,
            )
            CylinderLedger.objects.create(
                customer=customer,
                product=products[0],
                ownership_movement='customer_received',
                ownership_quantity=1,
            )

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('cylinders:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 20)
        self.assertEqual(response.context['cylinders_with_customers'], 36)
        self.assertEqual(response.context['customer_owned_in_shop'], 12)
        self.assertEqual(len(response.context['customer_cylinder_data']), 12)