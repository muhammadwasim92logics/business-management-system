from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json

from .models import Expense, OpeningBalance, DailyEarningSummary, PartnerAccountBalance

# Import your existing models
try:
    from apps.suppliers.models import Supplier, Purchase
except ImportError:
    try:
        from suppliers.models import Supplier, Purchase
    except ImportError:
        Supplier = None
        Purchase = None

try:
    from apps.customers.models import Customer
except ImportError:
    try:
        from customers.models import Customer
    except ImportError:
        Customer = None

try:
    from apps.deliveries.models import Delivery
except ImportError:
    try:
        from deliveries.models import Delivery
    except ImportError:
        Delivery = None


@login_required
def earning_dashboard(request):
    """Main dashboard for viewing daily earnings"""
    context = {
        'today': timezone.now().date().isoformat(),
    }
    return render(request, 'earnings/dashboard.html', context)


@login_required
def get_earning_details(request):
    """AJAX endpoint to get earning details for a date range"""
    try:
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date = timezone.now().date()
            
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = timezone.now().date()
        
        # Get income from deliveries (only paid amounts, not loans)
        income_data = get_income_data(start_date, end_date)
        
        # Get purchase payments (actual amounts paid, not loans)
        purchase_data = get_purchase_data(start_date, end_date)
        
        # Get expenses
        expenses = Expense.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).order_by('-date')

        account_balances = PartnerAccountBalance.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        )

        opening_balance = OpeningBalance.objects.filter(date__lte=end_date).order_by('-date', '-created_at').first()
        opening_amount = opening_balance.amount if opening_balance else Decimal('0.00')
        
        # Calculate totals
        total_income = income_data['total'] if income_data else Decimal('0.00')
        total_purchases = purchase_data['total'] if purchase_data else Decimal('0.00')
        total_expenses = expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
        net_cash = opening_amount + total_income - total_purchases - total_expenses
        
        response_data = {
            'success': True,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'income': {
                'data': income_data['details'],
                'total': str(total_income),
                'count': income_data['count']
            },
            'purchases': {
                'data': purchase_data['details'],
                'total': str(total_purchases),
                'count': purchase_data['count']
            },
            'expenses': {
                'data': [
                    {
                        'id': exp.id,
                        'description': exp.description,
                        'amount': str(exp.amount),
                        'date': exp.date.strftime('%Y-%m-%d')
                    }
                    for exp in expenses
                ],
                'total': str(total_expenses),
                'count': expenses.count()
            },
            'partner_accounts': [
                {
                    'id': account.id,
                    'partner_name': account.partner_name,
                    'bank_name': account.bank_name,
                    'amount': str(account.account_amount),
                    'description': account.description,
                    'date': account.date.strftime('%Y-%m-%d'),
                    'updated_at': account.updated_at.strftime('%Y-%m-%d %H:%M'),
                }
                for account in account_balances
            ],
            'opening_balance': {
                'id': opening_balance.id if opening_balance else None,
                'amount': str(opening_amount),
                'date': opening_balance.date.strftime('%Y-%m-%d') if opening_balance else None,
            },
            'net_cash': str(net_cash),
        }
        
        # Update daily summary
        update_daily_summary(start_date, total_income, total_purchases, total_expenses, net_cash)
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


def get_income_data(start_date, end_date):
    """Get income data from deliveries (only paid amounts)"""
    details = []
    total = Decimal('0.00')
    count = 0
    
    if Delivery:
        # Using payment_amount field from your Delivery model
        deliveries = Delivery.objects.filter(
            delivery_date__gte=start_date,
            delivery_date__lte=end_date,
            payment_amount__gt=0  # Only where payment was made
        ).values('customer__name', 'customer__id').annotate(
            total_paid=Sum('payment_amount')
        ).order_by('-total_paid')
        
        for delivery in deliveries:
            customer_name = delivery['customer__name'] or 'Unknown Customer'
            details.append({
                'customer_id': delivery['customer__id'],
                'customer_name': customer_name,
                'amount': str(delivery['total_paid'])
            })
        
        total = deliveries.aggregate(total_paid_sum=Sum('total_paid'))['total_paid_sum'] or Decimal('0.00')
        count = deliveries.count()
    
    return {
        'details': details,
        'total': total,
        'count': count
    }


def get_purchase_data(start_date, end_date):
    """Get purchase data from suppliers (only actual payments)"""
    details = []
    total = Decimal('0.00')
    count = 0
    
    if Purchase:
        # Using paid_amount field from your Purchase model
        purchases = Purchase.objects.filter(
            purchase_date__gte=start_date,
            purchase_date__lte=end_date,
            paid_amount__gt=0  # Only where payment was made
        ).values('supplier__name', 'supplier__id').annotate(
            total_paid=Sum('paid_amount')
        ).order_by('-total_paid')
        
        for purchase in purchases:
            supplier_name = purchase['supplier__name'] or 'Unknown Supplier'
            details.append({
                'supplier_id': purchase['supplier__id'],
                'supplier_name': supplier_name,
                'amount': str(purchase['total_paid'])
            })
        
        total = purchases.aggregate(total_paid_sum=Sum('total_paid'))['total_paid_sum'] or Decimal('0.00')
        count = purchases.count()
    
    return {
        'details': details,
        'total': total,
        'count': count
    }


@login_required
def add_expense(request):
    """Add a single expense"""
    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        amount = request.POST.get('amount', '0')
        date_str = request.POST.get('date', '')
        
        if not description:
            return JsonResponse({'success': False, 'error': 'Description is required'}, status=400)
        
        try:
            amount = Decimal(amount)
            if amount <= 0:
                return JsonResponse({'success': False, 'error': 'Amount must be greater than 0'}, status=400)
        except:
            return JsonResponse({'success': False, 'error': 'Invalid amount'}, status=400)
        
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
        except:
            date = timezone.now().date()
        
        expense = Expense.objects.create(
            description=description,
            amount=amount,
            date=date,
            created_by=request.user if request.user.is_authenticated else None
        )
        
        # Update daily summary
        update_daily_summary_for_date(date)
        
        return JsonResponse({
            'success': True,
            'expense': {
                'id': expense.id,
                'description': expense.description,
                'amount': str(expense.amount),
                'date': expense.date.strftime('%Y-%m-%d')
            }
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


def _partner_account_payload(request):
    partner_name = request.POST.get('partner_name', '').strip()
    bank_name = request.POST.get('bank_name', '').strip()
    description = request.POST.get('description', '').strip()
    date_str = request.POST.get('date', '').strip()

    if not partner_name or not bank_name:
        raise ValueError('Partner name and bank name are required')
    amount = Decimal(request.POST.get('amount', '0'))
    if amount < 0:
        raise ValueError('Amount cannot be negative')
    account_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
    return partner_name, bank_name, amount, description, account_date


@login_required
def add_partner_account(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    try:
        partner_name, bank_name, amount, description, account_date = _partner_account_payload(request)
        account = PartnerAccountBalance.objects.create(
            partner_name=partner_name,
            bank_name=bank_name,
            account_amount=amount,
            description=description,
            date=account_date,
            created_by=request.user,
        )
        return JsonResponse({'success': True, 'id': account.id})
    except (ValueError, TypeError, ArithmeticError):
        return JsonResponse({'success': False, 'error': 'Enter valid partner, bank, amount, and date'}, status=400)


@login_required
def update_partner_account(request, account_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    try:
        account = get_object_or_404(PartnerAccountBalance, pk=account_id)
        partner_name, bank_name, amount, description, account_date = _partner_account_payload(request)
        account.partner_name = partner_name
        account.bank_name = bank_name
        account.account_amount = amount
        account.description = description
        account.date = account_date
        account.save()
        return JsonResponse({'success': True})
    except (ValueError, TypeError, ArithmeticError):
        return JsonResponse({'success': False, 'error': 'Enter valid partner, bank, amount, and date'}, status=400)


@login_required
def delete_partner_account(request, account_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    account = get_object_or_404(PartnerAccountBalance, pk=account_id)
    account.delete()
    return JsonResponse({'success': True})


@login_required
def save_opening_balance(request):
    """Create or replace the opening cash balance."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)

    try:
        amount = Decimal(request.POST.get('amount', '0'))
        if amount < 0:
            raise ValueError
        date_str = request.POST.get('date', '')
        date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
    except (ValueError, TypeError, ArithmeticError):
        return JsonResponse({'success': False, 'error': 'Enter a valid non-negative amount and date'}, status=400)

    opening_balance = OpeningBalance.objects.order_by('date', 'created_at').first()
    if opening_balance:
        opening_balance.amount = amount
        opening_balance.date = date
        opening_balance.created_by = request.user
        opening_balance.save()
    else:
        opening_balance = OpeningBalance.objects.create(
            amount=amount,
            date=date,
            created_by=request.user
        )

    update_daily_summary_for_date(date)
    return JsonResponse({'success': True, 'amount': str(opening_balance.amount), 'date': date.strftime('%Y-%m-%d')})


@login_required
def delete_opening_balance(request):
    """Remove the opening cash balance."""
    if request.method == 'POST':
        opening_balance = OpeningBalance.objects.order_by('date', 'created_at').first()
        if opening_balance:
            date = opening_balance.date
            opening_balance.delete()
            update_daily_summary_for_date(date)
        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@login_required
def add_expenses_bulk(request):
    """Add multiple expenses at once"""
    if request.method == 'POST':
        expenses_data = request.POST.getlist('expenses[]')
        date_str = request.POST.get('date', '')
        
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
        except:
            date = timezone.now().date()
        
        expenses = []
        for expense_data in expenses_data:
            try:
                parsed_data = json.loads(expense_data) if isinstance(expense_data, str) else expense_data
                if isinstance(parsed_data, list):
                    expenses.extend(parsed_data)
                elif isinstance(parsed_data, dict):
                    expenses.append(parsed_data)
                else:
                    raise ValueError('Each expense must be an object.')
            except (json.JSONDecodeError, TypeError, ValueError):
                return JsonResponse({'success': False, 'error': 'Invalid expenses data.'}, status=400)

        if not expenses:
            return JsonResponse({'success': False, 'error': 'Add at least one valid expense.'}, status=400)

        validated_expenses = []
        for expense_data in expenses:
            if not isinstance(expense_data, dict):
                return JsonResponse({'success': False, 'error': 'Each expense must be an object.'}, status=400)

            description = str(expense_data.get('description', '')).strip()
            if not description:
                return JsonResponse({'success': False, 'error': 'Every expense requires a description.'}, status=400)

            try:
                amount = Decimal(str(expense_data.get('amount', '0')))
            except (InvalidOperation, TypeError, ValueError):
                return JsonResponse({'success': False, 'error': 'Every expense must have a valid amount.'}, status=400)
            if not amount.is_finite() or amount <= 0:
                return JsonResponse({'success': False, 'error': 'Every expense amount must be greater than 0.'}, status=400)

            validated_expenses.append((description, amount))

        created_expenses = []
        total_amount = Decimal('0.00')
        with transaction.atomic():
            for description, amount in validated_expenses:
                expense = Expense.objects.create(
                    description=description,
                    amount=amount,
                    date=date,
                    created_by=request.user,
                )
                created_expenses.append({
                    'id': expense.id,
                    'description': expense.description,
                    'amount': str(expense.amount)
                })
                total_amount += amount
        
        # Update daily summary
        update_daily_summary_for_date(date)
        
        return JsonResponse({
            'success': True,
            'expenses': created_expenses,
            'total': str(total_amount),
            'count': len(created_expenses)
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@login_required
def delete_expense(request, expense_id):
    """Delete an expense"""
    if request.method == 'POST':
        expense = get_object_or_404(Expense, id=expense_id)
        date = expense.date
        expense.delete()
        
        # Update daily summary
        update_daily_summary_for_date(date)
        
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


def update_daily_summary_for_date(date):
    """Update daily summary for a specific date"""
    # Get income data for the date
    income_data = get_income_data(date, date)
    total_income = income_data['total'] if income_data else Decimal('0.00')
    
    # Get purchase data for the date
    purchase_data = get_purchase_data(date, date)
    total_purchases = purchase_data['total'] if purchase_data else Decimal('0.00')
    
    # Get expenses for the date
    total_expenses = Expense.objects.filter(
        date=date
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
    
    opening_balance = OpeningBalance.objects.filter(date__lte=date).order_by('-date', '-created_at').first()
    opening_amount = opening_balance.amount if opening_balance else Decimal('0.00')
    net_cash = opening_amount + total_income - total_purchases - total_expenses
    
    # Update or create summary
    update_daily_summary(date, total_income, total_purchases, total_expenses, net_cash)


def update_daily_summary(date, total_income, total_purchases, total_expenses, net_cash):
    """Update or create daily summary"""
    summary, created = DailyEarningSummary.objects.get_or_create(
        date=date,
        defaults={
            'total_income': total_income,
            'total_purchases': total_purchases,
            'total_expenses': total_expenses,
            'net_cash': net_cash
        }
    )
    
    if not created:
        summary.total_income = total_income
        summary.total_purchases = total_purchases
        summary.total_expenses = total_expenses
        summary.net_cash = net_cash
        summary.save()
    
    return summary