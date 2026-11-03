from datetime import date
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Expense, PartnerAccountBalance


class PartnerAccountBalanceTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='earnings-user', password='secret123')
        self.client.force_login(user)

    def test_add_and_update_partner_account_snapshot(self):
        response = self.client.post(reverse('earnings:add_partner_account'), {
            'partner_name': 'Partner A',
            'bank_name': 'Bank One',
            'amount': '125000.75',
            'description': 'Operating account',
            'date': '2026-08-28',
        })

        self.assertEqual(response.status_code, 200)
        account = PartnerAccountBalance.objects.get()
        self.assertEqual(account.account_amount, Decimal('125000.75'))

        response = self.client.post(reverse('earnings:update_partner_account', args=[account.id]), {
            'partner_name': 'Partner A',
            'bank_name': 'Bank Two',
            'amount': '130000.25',
            'description': 'Updated account',
            'date': '2026-08-29',
        })

        self.assertEqual(response.status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.bank_name, 'Bank Two')
        self.assertEqual(account.date, date(2026, 8, 29))

    def test_details_returns_accounts_for_selected_date_range(self):
        user = get_user_model().objects.get(username='earnings-user')
        PartnerAccountBalance.objects.create(
            partner_name='Partner B',
            bank_name='Bank Three',
            account_amount='5000.00',
            date=date(2026, 8, 28),
            created_by=user,
        )

        response = self.client.get(reverse('earnings:get_details'), {
            'start_date': '2026-08-28',
            'end_date': '2026-08-28',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['partner_accounts'][0]['partner_name'], 'Partner B')


class BulkExpenseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='bulk-expense-user', password='secret123')
        self.client.force_login(self.user)

    def test_bulk_save_accepts_json_array_sent_by_expense_form(self):
        selected_date = date(2026, 9, 27)
        expenses = [
            {'description': 'Fuel', 'amount': '1200.50'},
            {'description': 'Lunch', 'amount': '450'},
        ]

        response = self.client.post(
            reverse('earnings:add_expenses_bulk'),
            {
                'expenses[]': json.dumps(expenses),
                'date': selected_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['count'], 2)
        self.assertEqual(response.json()['total'], '1650.50')
        self.assertEqual(Expense.objects.filter(date=selected_date).count(), 2)
        self.assertEqual(
            list(Expense.objects.filter(date=selected_date).order_by('description').values_list('description', 'amount')),
            [('Fuel', Decimal('1200.50')), ('Lunch', Decimal('450.00'))],
        )

    def test_bulk_save_rejects_invalid_rows_without_partial_creation(self):
        response = self.client.post(
            reverse('earnings:add_expenses_bulk'),
            {
                'expenses[]': '[{"description":"Fuel","amount":"1200"},{"description":"","amount":"450"}]',
                'date': '2026-09-27',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        self.assertEqual(Expense.objects.count(), 0)