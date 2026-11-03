from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, TemplateView
from django.urls import reverse, reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.db.models import Max, Sum, Q
from datetime import datetime, timedelta
from urllib.parse import urlencode
from django.utils import timezone
import logging
import pytz
import re

from apps.customers.models import Customer
from apps.products.models import Product
from apps.payments.models import Payment
from apps.cylinders.models import CylinderLedger
from .models import Delivery
from .forms import DeliveryForm

# Pakistan Timezone
PKT = pytz.timezone('Asia/Karachi')
logger = logging.getLogger(__name__)


def stock_quantity_for_delivery(product, quantity):
    """Convert a sale quantity to the units stored in Product.stock_quantity."""
    quantity = Decimal(str(quantity or 0))
    product_name = (product.name or '').upper()
    if 'LPG' in product_name or 'CO2' in product_name or 'CARBON DIOXIDE' in product_name:
        match = re.search(r'(\d+(?:\.\d+)?)\s*KG', product_name)
        if match:
            return quantity * Decimal(match.group(1))
    return quantity


def _apply_delivery_stock_change(delivery, direction):
    product = Product.objects.select_for_update().get(pk=delivery.product_id)
    net_stock_change = delivery.full_returned - delivery.quantity
    product.stock_quantity += int(stock_quantity_for_delivery(product, net_stock_change)) * direction
    if not product.is_quantity_only and not product.is_filling_only:
        product.empty_stock_quantity += delivery.empty_returned * direction
    product.stock_weight_kg += product.unit_weight_kg * net_stock_change * direction
    product.save()


def create_payment_safely(customer, amount, payment_type, notes, payment_date, created_by, invoice_no='', delivery=None):
    """
    Creates a Payment record safely with duplicate prevention.
    If an identical payment (same customer, amount, payment_date, and user) was created
    within the last 15 seconds, returns the existing payment instead of creating a duplicate.
    """
    recent_cutoff = timezone.now() - timedelta(seconds=15)
    existing = Payment.objects.filter(
        customer=customer,
        amount=amount,
        payment_date=payment_date,
        created_by=created_by,
        delivery=delivery,
        created_at__gte=recent_cutoff
    ).first()
    
    if existing:
        print(f"[De-duplication] Blocked duplicate payment creation for customer '{customer.name}', amount PKR {amount}")
        return existing, False
    
    payment = Payment.objects.create(
        customer=customer,
        amount=amount,
        payment_type=payment_type,
        notes=notes,
        invoice_no=invoice_no,
        created_by=created_by,
        payment_date=payment_date,
        delivery=delivery,
    )
    return payment, True


def _link_legacy_delivery_payments(delivery):
    linked_payments = list(delivery.payments.all())
    linked_positive = any(payment.amount > 0 for payment in linked_payments)
    linked_negative = any(payment.amount < 0 for payment in linked_payments)

    expected_payments = []
    if delivery.payment_amount and delivery.payment_amount > 0 and not linked_positive:
        invoice = delivery.invoice_no or 'N/A'
        expected_payments.append((
            delivery.payment_amount,
            f'Payment for {delivery.product.name} on {delivery.delivery_date} (Invoice: {invoice})',
            delivery.invoice_no or '',
        ))
    if (
        delivery.full_returned_paid
        and delivery.full_returned_value
        and delivery.full_returned_value > 0
        and not linked_negative
    ):
        expected_payments.append((
            -delivery.full_returned_value,
            f'Cash paid for full cylinder return - {delivery.product.name} ({delivery.full_returned} Full Returned)',
            '',
        ))

    for amount, notes, invoice_no in expected_payments:
        if amount > 0:
            matching_deliveries = Delivery.objects.filter(
                customer_id=delivery.customer_id,
                product_id=delivery.product_id,
                delivery_date=delivery.delivery_date,
                payment_amount=amount,
            )
        else:
            matching_deliveries = Delivery.objects.filter(
                customer_id=delivery.customer_id,
                product_id=delivery.product_id,
                delivery_date=delivery.delivery_date,
                full_returned_paid=True,
                full_returned_value=-amount,
            )
        if matching_deliveries.exclude(pk=delivery.pk).exists():
            continue

        candidates = Payment.objects.filter(
            delivery__isnull=True,
            customer_id=delivery.customer_id,
            payment_date=delivery.delivery_date,
            amount=amount,
            notes__startswith=(
                f'Payment for {delivery.product.name} on {delivery.delivery_date}'
                if amount > 0
                else f'Cash paid for full cylinder return - {delivery.product.name}'
            ),
        )
        candidate = candidates.order_by('created_at', 'id').first() if candidates.count() == 1 else None
        if candidate is None and amount > 0 and invoice_no:
            invoice_candidates = Payment.objects.filter(
                delivery__isnull=True,
                customer_id=delivery.customer_id,
                amount=amount,
                notes__startswith=f'Payment for {delivery.product.name} on ',
                notes__contains=f'(Invoice: {invoice_no})',
            )
            invoice_deliveries = Delivery.objects.filter(
                customer_id=delivery.customer_id,
                invoice_no=invoice_no,
                payment_amount=amount,
            )
            if invoice_candidates.count() == 1 and not invoice_deliveries.exclude(pk=delivery.pk).exists():
                candidate = invoice_candidates.first()
        if candidate:
            candidate.delivery = delivery
            candidate.save(update_fields=['delivery', 'updated_at'])
            linked_payments.append(candidate)

    return linked_payments


def _sync_delivery_payments(delivery, created_by=None):
    linked_payments = _link_legacy_delivery_payments(delivery)
    positive_payments = [payment for payment in linked_payments if payment.amount > 0]
    negative_payments = [payment for payment in linked_payments if payment.amount < 0]

    expected_payments = (
        (positive_payments, delivery.payment_amount or 0, delivery.payment_type or 'cash',
         delivery.invoice_no or '',
         f'Payment for {delivery.product.name} on {delivery.delivery_date} '
         f'(Invoice: {delivery.invoice_no or "N/A"})'),
        (negative_payments,
         -delivery.full_returned_value if delivery.full_returned_paid else 0,
         'cash', '',
         f'Cash paid for full cylinder return - {delivery.product.name} '
         f'({delivery.full_returned} Full Returned)'),
    )

    for payments, amount, payment_type, invoice_no, notes in expected_payments:
        payment = payments.pop(0) if payments else None
        if amount:
            if payment is None:
                payment = Payment(
                    delivery=delivery,
                    customer=delivery.customer,
                    created_by=created_by or delivery.created_by,
                )
            payment.delivery = delivery
            payment.customer = delivery.customer
            payment.amount = amount
            payment.payment_type = payment_type
            payment.payment_date = delivery.delivery_date
            payment.invoice_no = invoice_no
            payment.notes = notes
            payment.save()
        elif payment is not None:
            payment.delete()
        for duplicate in payments:
            duplicate.delete()


def _refresh_customer_last_activity(*customers):
    for customer in {customer for customer in customers if customer is not None}:
        latest_delivery = customer.deliveries.aggregate(latest=Max('delivery_date'))['latest']
        latest_payment = customer.payments.aggregate(latest=Max('payment_date'))['latest']
        activity_dates = [activity_date for activity_date in (latest_delivery, latest_payment) if activity_date]
        latest_activity = max(activity_dates) if activity_dates else None
        if customer.last_activity_date != latest_activity:
            customer.last_activity_date = latest_activity
            customer.save(update_fields=['last_activity_date', 'updated_at'])


def _delete_delivery_entry(delivery):
    _link_legacy_delivery_payments(delivery)
    product = delivery.product
    net_stock_change = delivery.full_returned - delivery.quantity
    product.stock_quantity -= int(stock_quantity_for_delivery(product, net_stock_change))
    if not product.is_quantity_only and not product.is_filling_only:
        product.empty_stock_quantity -= delivery.empty_returned
    product.stock_weight_kg -= product.unit_weight_kg * net_stock_change
    product.save()

    CylinderLedger.objects.filter(delivery=delivery).delete()
    customer = delivery.customer
    delivery.delete()
    _refresh_customer_last_activity(customer)


class DeliveryListView(LoginRequiredMixin, ListView):
    model = Delivery
    template_name = 'deliveries/list.html'
    context_object_name = 'deliveries'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Get filter parameters
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        customer = self.request.GET.get('customer', '')
        product = self.request.GET.get('product', '')
        
        # Apply filters
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(delivery_date__gte=date_from_obj)
            except ValueError:
                pass
        
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(delivery_date__lte=date_to_obj)
            except ValueError:
                pass
        
        if customer:
            queryset = queryset.filter(customer__name__icontains=customer)
        
        if product:
            queryset = queryset.filter(product__name__icontains=product)
        
        # Default: show today's deliveries if no filters applied
        if not (date_from or date_to or customer or product):
            today = timezone.now().astimezone(PKT).date()
            queryset = queryset.filter(delivery_date=today)
        
        return queryset.order_by('-delivery_date', '-created_at')
    
    
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter values for template
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        context['customer_filter'] = self.request.GET.get('customer', '')
        context['product_filter'] = self.request.GET.get('product', '')
        
        # Get all products for filter dropdown
        context['all_products'] = Product.objects.all().order_by('name')
        
        # Calculate summary for filtered deliveries
        queryset = self.get_queryset()
        
        # Total deliveries count
        context['total_deliveries'] = queryset.count()
        
        # Total amount
        total_amount = queryset.aggregate(total=Sum('delivery_amount'))['total'] or 0
        context['total_amount'] = total_amount
        
        # Total quantity
        total_quantity = queryset.aggregate(total=Sum('quantity'))['total'] or 0
        context['total_quantity'] = total_quantity
        
        # Total empty returned
        total_empty = queryset.aggregate(total=Sum('empty_returned'))['total'] or 0
        context['total_empty'] = total_empty
        
        # Product-wise summary for filtered deliveries
        product_summary = {}
        for delivery in queryset:
            product_name = delivery.product.name
            if product_name not in product_summary:
                product_summary[product_name] = {
                    'name': product_name,
                    'quantity': 0,
                    'amount': 0,
                    'returns': 0
                }
            product_summary[product_name]['quantity'] += delivery.quantity
            product_summary[product_name]['amount'] += float(delivery.delivery_amount)
            product_summary[product_name]['returns'] += delivery.empty_returned
        
        context['product_summary'] = product_summary.values()
        
        # Daily breakdown (for charts)
        daily_data = {}
        for delivery in queryset:
            date_str = delivery.delivery_date.strftime('%Y-%m-%d')
            if date_str not in daily_data:
                daily_data[date_str] = {
                    'date': date_str,
                    'count': 0,
                    'amount': 0,
                    'quantity': 0
                }
            daily_data[date_str]['count'] += 1
            daily_data[date_str]['amount'] += float(delivery.delivery_amount)
            daily_data[date_str]['quantity'] += delivery.quantity
        
        context['daily_data'] = sorted(daily_data.values(), key=lambda x: x['date'], reverse=True)
        
        # Check if filter is applied
        context['has_filter'] = bool(self.request.GET)
        
        return context


class DeliveryCreateView(LoginRequiredMixin, CreateView):
    model = Delivery
    form_class = DeliveryForm
    template_name = 'deliveries/form.html'
    success_url = reverse_lazy('deliveries:list')
    
    def get_initial(self):
        initial = super().get_initial()
        customer_id = self.request.GET.get('customer')
        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
                initial['customer'] = customer
            except Customer.DoesNotExist:
                pass
        return initial
    
    def form_valid(self, form):
        with transaction.atomic():
            form.instance.created_by = self.request.user
            response = super().form_valid(form)
            
            product = form.cleaned_data['product']
            product.stock_quantity -= int(stock_quantity_for_delivery(product, form.cleaned_data['quantity']))
            if not product.is_quantity_only:
                product.empty_stock_quantity += form.cleaned_data['empty_returned']
            product.save()
            
            # Update customer last activity with PKT timezone
            customer = form.cleaned_data['customer']
            customer.last_activity_date = timezone.now().astimezone(PKT).date()
            customer.save(update_fields=['last_activity_date', 'updated_at'])
            
            messages.success(self.request, f'Delivery {self.object.delivery_no} created successfully!')
            return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = False
        context['page_title'] = 'New Delivery'
        context['products'] = Product.objects.filter(stock_quantity__gt=0)
        
        # Pre-select customer if provided
        customer_id = self.request.GET.get('customer')
        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
                context['selected_customer'] = customer
            except Customer.DoesNotExist:
                pass
        
        return context


def validate_stock(request):
    product_id = request.GET.get('product_id')
    quantity = int(request.GET.get('quantity', 0))
    product = get_object_or_404(Product, pk=product_id)
    return JsonResponse({
        'valid': quantity <= product.stock_quantity,
        'available': product.stock_quantity,
        'product_name': product.name
    })


class DailyEntriesView(LoginRequiredMixin, ListView):
    model = Delivery
    template_name = 'deliveries/daily_entries.html'
    context_object_name = 'deliveries'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Get date from URL parameter or use today (PKT)
        date_str = self.request.GET.get('date', '')
        product_filter = self.request.GET.get('product', '')
        
        if date_str:
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                queryset = queryset.filter(delivery_date=date_obj)
            except ValueError:
                queryset = queryset.filter(delivery_date=timezone.now().astimezone(PKT).date())
        else:
            queryset = queryset.filter(delivery_date=timezone.now().astimezone(PKT).date())
        
        # Filter by product name if specified
        if product_filter:
            queryset = queryset.filter(product__name=product_filter)
        
        # Sort oldest to newest (top to bottom)
        return queryset.order_by('created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get date from URL parameter or use today (PKT)
        date_str = self.request.GET.get('date', '')
        selected_date = timezone.now().astimezone(PKT).date()
        
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().astimezone(PKT).date()
        
        # Calculate previous and next dates for navigation
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)
        today = timezone.now().astimezone(PKT).date()
        
        context['selected_date'] = selected_date
        context['prev_date'] = prev_date
        context['next_date'] = next_date
        context['today'] = today
        context['has_next'] = next_date <= today
        
        context['products'] = Product.objects.all().order_by('name')
        context['customers'] = Customer.objects.all().order_by('name')
        
        # Get entries for the selected date
        deliveries = Delivery.objects.filter(delivery_date=selected_date).order_by('created_at')
        payments = Payment.objects.filter(payment_date=selected_date).order_by('created_at')
        
        # Combine activities
        activities = []
        
        # Track matched payments
        matched_payment_ids = set()
        
        # ============================================================
        # MAINTAIN BALANCES PER CUSTOMER
        # ============================================================
        customer_cylinder_balance = {}
        customer_financial_balance = {}
        
        # Initialize financial and cylinder balances for ALL customers up to selected_date
        all_customers = set()
        for delivery in deliveries:
            all_customers.add(delivery.customer_id)
        for payment in payments:
            all_customers.add(payment.customer_id)
        
        for customer_id in all_customers:
            customer = Customer.objects.get(pk=customer_id)
            customer_financial_balance[customer_id] = customer.get_balance_before_date(selected_date)
            customer_cylinder_balance[customer_id] = customer.get_cylinders_before_date(selected_date)
        
        # Process deliveries using only explicitly linked payments.
        for delivery in deliveries:
            created_at_pkt = delivery.created_at.astimezone(PKT) if delivery.created_at else None

            linked_payments = [payment for payment in payments if payment.delivery_id == delivery.pk]
            matched_payment_ids.update(payment.id for payment in linked_payments)
            matching_payment = linked_payments[0] if linked_payments else None
            
            # Get customer ID
            customer_id = delivery.customer_id
            
            # Get current cylinder balance for this customer
            current_balance = customer_cylinder_balance.get(customer_id, {})
            
            # Get old cylinder breakdown for display (before this transaction)
            old_cylinders_breakdown = current_balance.copy()
            old_cylinders_total = sum(old_cylinders_breakdown.values())
            
            # Calculate new balance after this transaction
            product_name = delivery.product.name
            product_key = next(
                (existing for existing in current_balance if existing.casefold() == product_name.casefold()),
                product_name,
            )
            ownership_quantity = delivery.cylinderledger_set.filter(
                ownership_movement__in=('customer_received', 'customer_returned')
            ).values_list('ownership_quantity', flat=True).first() or 0
            if delivery.cylinder_movement_type == 'customer_returned':
                net_change = ownership_quantity
            elif delivery.cylinder_movement_type == 'customer_received':
                net_change = -ownership_quantity
            else:
                net_change = delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0)
            
            # Update the balance for this product
            if product_key not in current_balance:
                current_balance[product_key] = 0
            current_balance[product_key] += net_change
            
            # Get new cylinder breakdown (after this transaction)
            new_cylinders_breakdown = current_balance.copy()
            new_cylinders_total = sum(new_cylinders_breakdown.values())
            
            # Format breakdown for display
            old_cylinders_parts = []
            new_cylinders_parts = []
            
            for prod_name, balance in old_cylinders_breakdown.items():
                if balance != 0:
                    old_cylinders_parts.append(f"{prod_name}: {balance}")
            old_cylinders_display = ' | '.join(old_cylinders_parts) if old_cylinders_parts else '0'
            
            for prod_name, balance in new_cylinders_breakdown.items():
                if balance != 0:
                    new_cylinders_parts.append(f"{prod_name}: {balance}")
            new_cylinders_display = ' | '.join(new_cylinders_parts) if new_cylinders_parts else '0'
            
            # ============================================================
            # FINANCIAL BALANCE CALCULATION
            # ============================================================
            old_balance = customer_financial_balance.get(customer_id, 0)
            delivery_amount = float(delivery.delivery_amount)
            payment_amount = sum(float(payment.amount) for payment in linked_payments)
            
            new_balance = old_balance + delivery_amount - payment_amount
            customer_financial_balance[customer_id] = new_balance
            
            delivery_charges = float(delivery.delivery_charges) if delivery.delivery_charges else 0
            total_before_delivery_charges = delivery_amount - delivery_charges
            display_empty_returned = delivery.empty_returned or 0
            if delivery.cylinder_movement_type in ('customer_received', 'customer_returned'):
                display_empty_returned = delivery.cylinderledger_set.filter(
                    ownership_movement=delivery.cylinder_movement_type
                ).values_list('ownership_quantity', flat=True).first() or 0
            
            # Create items list
            items = [{
                'product': delivery.product.name,
                'quantity': delivery.quantity,
                'empty_returned': display_empty_returned,
                'amount': float(delivery.delivery_amount),
                'delivery_no': delivery.delivery_no,
                'unit_price': float(delivery.unit_price),
                'personal_details': '',
                'is_quantity_only': delivery.product.is_quantity_only
            }]
            
            invoice_no = delivery.invoice_no or delivery.delivery_no

            activity = {
                'id': str(delivery.id),
                'type': 'delivery',
                'customer': delivery.customer,
                'customer_name': delivery.customer.name,
                'customer_mobile': delivery.customer.mobile,
                'customer_code': delivery.customer.customer_code,
                'items': items,
                'total_quantity': delivery.quantity,
                'total_empty': display_empty_returned,
                'delivery_amount': delivery_amount,
                'delivery_charges': delivery_charges,
                'total_before_delivery_charges': total_before_delivery_charges,
                'total_after_delivery_charges': delivery_amount,
                'created_at': delivery.created_at,
                'created_time': created_at_pkt.strftime('%I:%M %p') if created_at_pkt else 'N/A',
                'created_date': created_at_pkt.strftime('%Y-%m-%d') if created_at_pkt else 'N/A',
                'has_payment': matching_payment is not None,
                'payment_amount': payment_amount,
                'payment_type': matching_payment.get_payment_type_display() if matching_payment else None,
                'old_balance': old_balance,
                'new_balance': new_balance,
                'old_cylinders_total': old_cylinders_total,
                'new_cylinders_total': new_cylinders_total,
                'old_cylinders_display': old_cylinders_display,
                'new_cylinders_display': new_cylinders_display,
                'old_cylinders_breakdown': old_cylinders_breakdown,
                'new_cylinders_breakdown': new_cylinders_breakdown,
                'is_payment_only': False,
                'invoice_no': invoice_no,
                'unit_price': float(delivery.unit_price),
                'damage_charges': float(delivery.damage_charges) if delivery.damage_charges else 0,
                'low_pressure_details': delivery.low_pressure_details or [],
                'full_returned': delivery.full_returned or 0,
                'full_returned_value': float(delivery.full_returned_value) if delivery.full_returned_value else 0,
                'full_returned_paid': delivery.full_returned_paid or False,
                'calculation_details': delivery.calculation_details,
                'return_details': delivery.return_details,
            }
            activities.append(activity)
        
        # ============================================================
        # ADD PAYMENT ONLY ENTRIES
        # ============================================================
        for payment in payments:
            if payment.id in matched_payment_ids:
                continue
            
            created_at_pkt = payment.created_at.astimezone(PKT) if payment.created_at else None
            
            customer_id = payment.customer_id
            
            current_balance = customer_cylinder_balance.get(customer_id, {})
            old_cylinders_breakdown = current_balance.copy()
            old_cylinders_total = sum(old_cylinders_breakdown.values())
            old_cylinders_parts = []
            for prod_name, balance in old_cylinders_breakdown.items():
                if balance != 0:
                    old_cylinders_parts.append(f"{prod_name}: {balance}")
            old_cylinders_display = ' | '.join(old_cylinders_parts) if old_cylinders_parts else '0'
            
            old_balance = customer_financial_balance.get(customer_id, 0)
            payment_amount = float(payment.amount)
            new_balance = old_balance - payment_amount
            customer_financial_balance[customer_id] = new_balance
            
            activity = {
                'id': str(payment.id),  
                'type': 'payment_only',
                'customer': payment.customer,
                'customer_name': payment.customer.name,
                'customer_mobile': payment.customer.mobile,
                'customer_code': payment.customer.customer_code,
                'items': [],
                'total_quantity': 0,
                'total_empty': 0,
                'delivery_amount': 0,
                'delivery_charges': 0,
                'created_at': payment.created_at,
                'created_time': created_at_pkt.strftime('%I:%M %p') if created_at_pkt else 'N/A',
                'created_date': created_at_pkt.strftime('%Y-%m-%d') if created_at_pkt else 'N/A',
                'has_payment': True,
                'payment_amount': payment_amount,
                'payment_type': payment.get_payment_type_display(),
                'old_balance': old_balance,
                'new_balance': new_balance,
                'old_cylinders_total': old_cylinders_total,
                'new_cylinders_total': old_cylinders_total,
                'old_cylinders_display': old_cylinders_display,
                'new_cylinders_display': old_cylinders_display,
                'old_cylinders_breakdown': old_cylinders_breakdown,
                'new_cylinders_breakdown': old_cylinders_breakdown,
                'is_payment_only': True,
                'invoice_no': payment.invoice_no or payment.payment_no,
                'unit_price': 0,
                'description': '',
            }
            activities.append(activity)
        
        # Sort by created_at (oldest first)
        activities.sort(key=lambda x: x['created_at'])

        transaction_filters = self.request.GET.getlist('transaction_filter')
        valid_transaction_filters = {'full_no_empty', 'credit', 'partial_payment'}
        transaction_filters = [value for value in transaction_filters if value in valid_transaction_filters]

        def matches_transaction_filter(activity):
            if activity['type'] != 'delivery':
                return False
            item = activity['items'][0] if activity['items'] else {}
            is_cylinder_delivery = not item.get('is_quantity_only', False)
            payment_amount = float(activity.get('payment_amount') or 0)
            delivery_amount = float(activity.get('total_after_delivery_charges') or activity.get('delivery_amount') or 0)

            if 'full_no_empty' in transaction_filters and is_cylinder_delivery and float(activity.get('total_quantity') or 0) > 0 and float(activity.get('total_empty') or 0) == 0:
                return True
            if 'credit' in transaction_filters and delivery_amount > 0 and payment_amount <= 0:
                return True
            if 'partial_payment' in transaction_filters and delivery_amount > 0 and payment_amount > 0 and (
                    payment_amount < delivery_amount or
                    float(activity.get('new_balance') or 0) > 0
                ):
                return True
            return False

        if transaction_filters:
            activities = [activity for activity in activities if matches_transaction_filter(activity)]
        
        context['activities'] = activities
        context['transaction_filters'] = transaction_filters
        context['transaction_filter_query'] = urlencode([('transaction_filter', value) for value in transaction_filters])
        context['transaction_filter_choices'] = [
            ('', 'All transactions'),
            ('full_no_empty', 'Full cylinders delivered, no empties returned'),
            ('credit', 'Credit: no immediate payment'),
            ('partial_payment', 'Partial payment: balance remains'),
        ]

        customer_groups = {}
        for activity in activities:
            customer_id = str(activity['customer'].pk)
            group = customer_groups.setdefault(customer_id, {
                'customer': activity['customer'],
                'customer_name': activity['customer_name'],
                'customer_mobile': activity['customer_mobile'],
                'activities': [],
                'total_before_delivery_charges': 0,
                'total_delivery_charges': 0,
                'total_delivery_amount': 0,
                'total_payments': 0,
                'total_amount': 0,
            })
            group['activities'].append(activity)
            if activity['type'] == 'delivery':
                group['total_before_delivery_charges'] += activity['total_before_delivery_charges']
                group['total_delivery_charges'] += activity['delivery_charges']
                group['total_delivery_amount'] += activity['delivery_amount']
            if activity['has_payment']:
                group['total_payments'] += activity['payment_amount']
            group['total_amount'] = group['total_delivery_amount'] - group['total_payments']

        context['customer_data'] = list(customer_groups.values())
        
        # Calculate totals
        context['total_activities'] = len(activities)
        context['total_deliveries'] = len([a for a in activities if a['type'] == 'delivery'])
        context['total_payments'] = len([a for a in activities if a['type'] == 'payment_only'])
        context['total_quantity'] = sum([a['total_quantity'] for a in activities if a['type'] == 'delivery'])
        context['total_empty'] = sum([a['total_empty'] for a in activities if a['type'] == 'delivery'])
        context['total_delivery_amount'] = sum([a['delivery_amount'] for a in activities if a['type'] == 'delivery'])
        context['total_delivery_charges'] = sum([a['delivery_charges'] for a in activities if a['type'] == 'delivery'])
        context['total_damage_charges'] = sum([a.get('damage_charges', 0) for a in activities if a['type'] == 'delivery'])
        context['total_payment_amount'] = sum(a['payment_amount'] for a in activities if a['has_payment'])
        
        return context

class DailyEntryCreateView(LoginRequiredMixin, TemplateView):
    template_name = 'deliveries/daily_entry_add.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['products'] = Product.objects.all().order_by('name')
        context['customers'] = Customer.objects.all().order_by('name')
        context['today'] = timezone.now().astimezone(PKT).date()
        return context



def get_customer_balance(request):
    """API endpoint to get customer balance with cylinder details and last rates"""
    customer_id = request.GET.get('customer_id')
    if not customer_id:
        return JsonResponse({'error': 'No customer ID provided'}, status=400)
    
    try:
        customer = get_object_or_404(Customer, pk=customer_id)
        
        # ============================================================
        # CALCULATE OUTSTANDING (Using centralized model method)
        # ============================================================
        outstanding = customer.get_outstanding_balance()
        total_billed = customer.get_total_amount()
        total_paid = customer.get_total_payments()
        bf_balance = float(customer.bf_balance or 0)
        previous_balance = float(customer.previous_balance or 0)
        
        # ============================================================
        # GET CYLINDER BALANCE PER PRODUCT (Using centralized model method)
        # ============================================================
        cylinders = customer.get_cylinder_balance()
        
        # ============================================================
        # GET LAST RATE PER PRODUCT
        # ============================================================
        last_rates = {}
        for delivery in customer.deliveries.all().order_by('-created_at'):
            product_name = delivery.product.name if delivery.product else 'Unknown'
            if product_name not in last_rates:
                last_rates[product_name] = float(delivery.unit_price) if delivery.unit_price else 0
        
        # ============================================================
        # GET LAST ACTIVITY DATE
        # ============================================================
        last_activity = None
        if customer.last_activity_date:
            last_activity = customer.last_activity_date.strftime('%Y-%m-%d')
        
        return JsonResponse({
            'customer_name': customer.name,
            'customer_code': customer.customer_code,
            'customer_mobile': customer.mobile,
            'outstanding': float(outstanding),
            'total_billed': float(total_billed),
            'total_paid': float(total_paid),
            'previous_balance': float(previous_balance),
            'bf_balance': float(bf_balance),
            'last_activity': last_activity,
            'cylinders': cylinders,
            'last_rates': last_rates
        })
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

class PaymentOnlyView(LoginRequiredMixin, TemplateView):
    template_name = 'deliveries/payment_only.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customers'] = Customer.objects.all().order_by('name')
        context['today'] = timezone.now().astimezone(PKT).date()
        return context
    
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            customer_id = request.POST.get('customer_id')
            payment_amount = request.POST.get('payment_amount')
            payment_type = request.POST.get('payment_type', 'cash')
            notes = request.POST.get('notes', '')
            
            if not customer_id or not payment_amount:
                messages.error(request, 'Please select a customer and enter payment amount.')
                return redirect('deliveries:payment_only')
            
            try:
                payment_amount = Decimal(payment_amount)
            except (ValueError, TypeError):
                messages.error(request, 'Please enter a valid payment amount.')
                return redirect('deliveries:payment_only')
            
            if payment_amount <= 0:
                messages.error(request, 'Payment amount must be greater than zero.')
                return redirect('deliveries:payment_only')
            
            customer = get_object_or_404(Customer, pk=customer_id)
            outstanding = Decimal(str(customer.get_outstanding_balance() or 0))
            
            selected_date_str = request.POST.get('selected_date', '')
            try:
                payment_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
            except (TypeError, ValueError):
                payment_date = timezone.now().astimezone(PKT).date()
            
            payment, _ = create_payment_safely(
                customer=customer,
                amount=payment_amount,
                payment_type=payment_type,
                notes=notes or f"Payment Only on {payment_date}",
                created_by=request.user,
                payment_date=payment_date
            )
            
            customer.last_activity_date = payment_date
            customer.save(update_fields=['last_activity_date', 'updated_at'])
            
            new_outstanding = outstanding - payment_amount
            
            if new_outstanding <= 0:
                if new_outstanding < 0:
                    messages.success(
                        request, 
                        f'✅ Payment of PKR {payment_amount:,.2f} recorded for {customer.name}!\n'
                        f'💰 Advance balance: PKR {abs(new_outstanding):,.2f}'
                    )
                else:
                    messages.success(
                        request, 
                        f'✅ Payment of PKR {payment_amount:,.2f} recorded for {customer.name}!\n'
                        f'🎉 All dues cleared!'
                    )
            else:
                messages.success(
                    request, 
                    f'✅ Payment of PKR {payment_amount:,.2f} recorded for {customer.name}!\n'
                    f'📊 Remaining outstanding: PKR {new_outstanding:,.2f}'
                )
            
            return redirect(f'{reverse("deliveries:daily_entry")}?date={payment_date.isoformat()}')
        
     
     
# ============================================================
# CRUD API ENDPOINTS - Add these to your views.py
# ============================================================

import json
import uuid
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def save_entry_api(request):
    """API endpoint to save a single entry via AJAX without page reload"""
    try:
        data = json.loads(request.body)
        date_str = data.get('date')
        entry_data = data.get('data')
        entry_id = data.get('entry_id')
        
        if not entry_data:
            return JsonResponse({'success': False, 'error': 'No data provided'})

        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().astimezone(PKT).date()
        
        customer_id = entry_data.get('customer_id')
        customer_type = entry_data.get('customer_type', 'existing')
        
        if customer_type == 'new':
            name = entry_data.get('new_name', '')
            mobile = (entry_data.get('new_mobile') or '').strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Name is required for new customer'})
            
            security_deposit = entry_data.get('new_security', 0)
            personal_cylinders = entry_data.get('new_personal_cylinders', 0)
            
            customer = Customer.objects.create(
                name=name,
                mobile=mobile,
                security_deposit=security_deposit,
                personal_cylinders=personal_cylinders,
                last_activity_date=selected_date
            )
        else:
            if not customer_id:
                return JsonResponse({'success': False, 'error': 'Customer is required'})
            customer = get_object_or_404(Customer, pk=customer_id)
        
        products_data = entry_data.get('products', [])
        first_product = products_data[0] if products_data else None
        
        if not first_product or not first_product.get('product_id'):
            return JsonResponse({'success': False, 'error': 'At least one product is required'})
        
        product = get_object_or_404(Product, pk=first_product['product_id'])
        quantity = first_product.get('full', 0)
        unit_price = first_product.get('rate', 0)
        empty_returned = first_product.get('empty', 0)

        if product.is_quantity_only or product.is_filling_only:
            empty_returned = 0
        
        cylinder_movement_type = entry_data.get('cylinder_movement_type', '')
        if quantity <= 0 and not cylinder_movement_type:
            return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0'})
        
        invoice_no = entry_data.get('invoice_no', '')
        delivery_charges = entry_data.get('delivery_charges', 0)
        payment_amount = entry_data.get('payment', 0)
        payment_type = entry_data.get('payment_type', 'cash')
        description = entry_data.get('description', '')
        
        delivery_amount = (quantity * unit_price) + delivery_charges
        
        delivery = None
        if entry_id:
            try:
                delivery = Delivery.objects.get(pk=uuid.UUID(entry_id), created_by=request.user)
            except (ValueError, Delivery.DoesNotExist):
                delivery = None
        
        old_customer = None
        if delivery:
            _link_legacy_delivery_payments(delivery)
            old_customer = delivery.customer
            _apply_delivery_stock_change(delivery, -1)
            delivery.customer = customer
            delivery.product = product
            delivery.quantity = quantity
            delivery.unit_price = unit_price
            delivery.empty_returned = empty_returned
            delivery.full_delivered = quantity
            delivery.delivery_date = selected_date
            delivery.invoice_no = invoice_no
            delivery.delivery_charges = delivery_charges
            delivery.payment_amount = payment_amount
            delivery.payment_type = payment_type
            delivery.description = description
            delivery.delivery_amount = delivery_amount
            delivery.save()
        else:
            delivery = Delivery.objects.create(
                customer=customer,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                empty_returned=empty_returned,
                full_delivered=quantity,
                delivery_date=selected_date,
                invoice_no=invoice_no,
                delivery_charges=delivery_charges,
                payment_amount=payment_amount,
                payment_type=payment_type,
                description=description,
                delivery_amount=delivery_amount,
                
                created_by=request.user,
            )

        delivery.cylinder_movement_type = cylinder_movement_type
        delivery.save(update_fields=['cylinder_movement_type', 'updated_at', 'has_returns', 'delivery_amount'])
        _sync_delivery_payments(delivery, request.user)
        _refresh_customer_last_activity(old_customer, customer)
        ledger = delivery.cylinderledger_set.first()
        if product.is_quantity_only or product.is_filling_only:
            if ledger:
                ledger.delete()
        elif delivery.quantity > 0 or delivery.empty_returned or delivery.full_returned or cylinder_movement_type:
            if ledger is None:
                ledger = CylinderLedger(customer=customer, product=product, delivery=delivery)
            ledger.customer = customer
            ledger.product = product
            ledger.full_out = delivery.quantity
            ledger.empty_in = delivery.empty_returned + delivery.full_returned
            ledger.ownership_movement = cylinder_movement_type
            ledger.ownership_quantity = abs(int(empty_returned or 0)) if cylinder_movement_type else 0
            ledger.notes = delivery.remarks or f'Updated entry {delivery.delivery_no}'
            ledger.save()
        elif ledger:
            ledger.delete()

        _apply_delivery_stock_change(delivery, 1)
        
        customer.last_activity_date = selected_date
        customer.save(update_fields=['last_activity_date', 'updated_at'])
        
        return JsonResponse({
            'success': True,
            'entry_id': str(delivery.id),
            'message': 'Entry saved successfully',
            'entry': {
                'id': str(delivery.id),
                'customer_id': str(customer.id),
                'customer_name': customer.name,
                'invoice_no': delivery.invoice_no,
                'delivery_charges': float(delivery.delivery_charges),
                'payment': float(delivery.payment_amount),
                'payment_type': delivery.payment_type,
                'description': delivery.description,
                'products': [
                    {
                        'product_id': str(delivery.product_id),
                        'product_name': delivery.product.name,
                        'empty': delivery.empty_returned,
                        'full': delivery.quantity,
                        'rate': float(delivery.unit_price),
                        'total': float(delivery.delivery_amount),
                    }
                ]
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_daily_entries_api(request):
    """API endpoint to get entries for a specific date"""
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'entries': []})
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'entries': []})
    
    deliveries = Delivery.objects.filter(
        delivery_date=date_obj
    ).order_by('created_at')
    
    entries = []
    for delivery in deliveries:
        entry_data = {
            'id': str(delivery.id),
            'type': 'delivery',
            'customer_id': str(delivery.customer_id),
            'customer_name': delivery.customer.name,
            'invoice_no': delivery.invoice_no or '',
            'delivery_charges': float(delivery.delivery_charges or 0),
            'damage_charges': float(delivery.damage_charges or 0),
            'damage_description': delivery.damage_description or '',
            'payment': float(delivery.payment_amount or 0),  # Use delivery.payment_amount
            'payment_type': delivery.payment_type or 'cash',  # Use delivery.payment_type
            'description': delivery.description or '',
            'products': [
                {
                    'product_id': str(delivery.product_id),
                    'product_name': delivery.product.name,
                    'empty': delivery.empty_returned or 0,
                    'full': delivery.quantity or 0,
                    'rate': float(delivery.unit_price or 0),
                    'total': float(delivery.delivery_amount or 0),
                    'full_returned': delivery.full_returned or 0,
                    'full_returned_value': float(delivery.full_returned_value or 0),
                    'full_returned_paid': delivery.full_returned_paid,
                    'cylinder_movement_type': delivery.cylinder_movement_type or '',
                    'low_pressure_details': delivery.low_pressure_details or [],
                    'damage_charges': float(delivery.damage_charges or 0),
                    'damage_description': delivery.damage_description or '',
                }
            ]
        }
        entries.append(entry_data)
        
    payments = Payment.objects.filter(
        payment_date=date_obj,
        delivery__isnull=True,
    ).order_by('created_at')
    
    for payment in payments:
        entry_data = {
            'id': str(payment.id),
            'type': 'payment_only',
            'customer_id': str(payment.customer_id),
            'customer_name': payment.customer.name,
            'invoice_no': payment.payment_no or '',
            'delivery_charges': 0,
            'payment': float(payment.amount or 0),
            'payment_type': payment.payment_type or 'cash',
            'description': payment.notes or '',
            'products': []
        }
        entries.append(entry_data)
    
    return JsonResponse({'entries': entries})


def get_or_create_walkin_customer():
    """Get or create the canonical walk-in customer without multiplying rows."""
    return Customer.get_or_create_walkin(
        name='Walk-in Customer',
        mobile='',
        security_deposit=0,
        personal_cylinders=0,
        last_activity_date=timezone.now().astimezone(PKT).date(),
    )


@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def update_entry_api(request):
    """API endpoint to update an existing entry via AJAX"""
    error_location = 'Edited entry details'
    entry_id = None
    try:
        data = json.loads(request.body)
        entry_id = data.get('entry_id')
        entry_data = data.get('data')
        
        print("=" * 60)
        print("UPDATE ENTRY API CALLED")
        print(f"Entry ID: {entry_id}")
        print(f"Entry Data: {json.dumps(entry_data, indent=2)}")
        print("=" * 60)
        
        if not entry_id or not entry_data:
            return JsonResponse({'success': False, 'error': 'Entry ID and data are required'})
        
        try:
            delivery = Delivery.objects.get(pk=uuid.UUID(entry_id))
            is_delivery = True
        except Delivery.DoesNotExist:
            try:
                payment = Payment.objects.get(pk=uuid.UUID(entry_id))
                is_delivery = False
            except Payment.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Entry not found'})

        old_customer = delivery.customer if is_delivery else payment.customer
        if is_delivery:
            _link_legacy_delivery_payments(delivery)
        
        print(f"Before update:")
        if is_delivery:
            print(f"  - payment_amount: {delivery.payment_amount}")
            print(f"  - payment_type: {delivery.payment_type}")
            print(f"  - delivery_amount: {delivery.delivery_amount}")
            print(f"  - quantity: {delivery.quantity}")
            print(f"  - unit_price: {delivery.unit_price}")
        else:
            print(f"  - payment_amount: {payment.amount}")

        # Get customer
        error_location = 'Customer'
        customer_id = entry_data.get('customer_id')
        if customer_id:
            customer = get_object_or_404(Customer, pk=customer_id)
            if is_delivery:
                delivery.customer = customer
            else:
                payment.customer = customer
                
        # Update delivery_date if provided
        parsed_date = None
        delivery_date_str = entry_data.get('delivery_date')
        if delivery_date_str:
            try:
                parsed_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
                
        if not is_delivery:
            error_location = 'Payment amount / payment type'
            payment_amount = entry_data.get('payment_amount')
            if payment_amount is not None:
                try:
                    payment.amount = float(payment_amount)
                except (ValueError, TypeError):
                    pass
            payment_type = entry_data.get('payment_type')
            if payment_type:
                payment.payment_type = payment_type
            payment.notes = entry_data.get('description', payment.notes)
            if parsed_date:
                payment.payment_date = parsed_date
            payment.save()
            _refresh_customer_last_activity(old_customer, payment.customer)
            return JsonResponse({
                'success': True,
                'message': 'Payment updated successfully',
                'entry': {
                    'id': str(payment.id),
                    'customer_id': str(payment.customer_id),
                    'customer_name': payment.customer.name,
                    'invoice_no': payment.invoice_no or payment.payment_no,
                    'delivery_charges': 0,
                    'payment': float(payment.amount or 0),
                    'payment_type': payment.payment_type or 'cash',
                    'description': payment.notes,
                    'products': []
                }
            })
        
        # Get product and restore the old net stock movement before applying edits.
        error_location = 'Product'
        product_id = entry_data.get('product_id')
        old_product = delivery.product
        old_net_stock_change = delivery.full_returned - delivery.quantity
        old_stock_change = stock_quantity_for_delivery(old_product, old_net_stock_change)
        old_product.stock_quantity -= int(old_stock_change)
        if not old_product.is_quantity_only and not old_product.is_filling_only:
            old_product.empty_stock_quantity -= delivery.empty_returned
        old_product.stock_weight_kg -= old_product.unit_weight_kg * old_net_stock_change
        old_product.save()

        if product_id:
            # Update to new product
            product = get_object_or_404(Product, pk=product_id)
            delivery.product = product
        else:
            product = old_product
        
        # Update all fields
        error_location = 'Quantity / rate / cylinder returns'
        delivery.quantity = int(entry_data.get('quantity', delivery.quantity))
        delivery.unit_price = float(entry_data.get('unit_price', delivery.unit_price))
        delivery.empty_returned = int(entry_data.get('empty_returned', delivery.empty_returned))
        cylinder_movement_type = entry_data.get('cylinder_movement_type', '')
        if entry_data.get('return_empty_to_customer', False):
            cylinder_movement_type = 'customer_returned'
        delivery.cylinder_movement_type = cylinder_movement_type
        if cylinder_movement_type in ('customer_received', 'customer_returned'):
            delivery.quantity = 0
            delivery.unit_price = 0
            delivery.empty_returned = 0
            delivery.full_returned = 0
            delivery.full_returned_value = 0
            delivery.full_returned_paid = False
            delivery.delivery_charges = 0
            delivery.damage_charges = 0
            delivery.payment_amount = 0
        else:
            delivery.empty_returned = abs(delivery.empty_returned)
        if product.is_quantity_only or product.is_filling_only:
            delivery.empty_returned = 0
        delivery.full_delivered = delivery.quantity
        delivery.full_returned = max(0, int(entry_data.get('full_returned', delivery.full_returned) or 0))
        delivery.full_returned_value = max(0, float(entry_data.get('full_returned_value', delivery.full_returned_value) or 0))
        delivery.full_returned_paid = bool(entry_data.get('full_returned_paid', delivery.full_returned_paid))
        delivery.low_pressure_details = entry_data.get('low_pressure_details', delivery.low_pressure_details or [])
        error_location = 'Damage / delivery charges'
        delivery.damage_charges = max(0, float(entry_data.get('damage_charges', delivery.damage_charges) or 0))
        delivery.damage_description = entry_data.get('damage_description', delivery.damage_description or '')
        delivery.invoice_no = entry_data.get('invoice_no', delivery.invoice_no)
        delivery.delivery_charges = float(entry_data.get('delivery_charges', delivery.delivery_charges))
        delivery.description = entry_data.get('description', delivery.description)
        
        if parsed_date:
            delivery.delivery_date = parsed_date
        
        # ============================================================
        # CRITICAL FIX: Update payment_amount - This is the main issue
        # ============================================================
        # Get payment_amount from request data
        payment_amount = entry_data.get('payment_amount')
        error_location = 'Payment amount'
        print(f"Payment amount from request: {payment_amount} (type: {type(payment_amount)})")
        
        if payment_amount is not None:
            try:
                # Convert to float and assign
                delivery.payment_amount = float(payment_amount)
                print(f"Payment amount set to: {delivery.payment_amount}")
            except (ValueError, TypeError) as e:
                print(f"Error converting payment_amount: {e}")
                delivery.payment_amount = 0.0
        else:
            print("No payment_amount provided, keeping existing value")
            # Keep existing value
            delivery.payment_amount = delivery.payment_amount or 0.0
        
        # Update payment_type
        payment_type = entry_data.get('payment_type')
        if payment_type:
            delivery.payment_type = payment_type
            print(f"Payment type set to: {delivery.payment_type}")
        
        # Apply the edited net stock movement.
        new_net_stock_change = delivery.full_returned - delivery.quantity
        new_stock_change = stock_quantity_for_delivery(product, new_net_stock_change)
        product.stock_quantity += int(new_stock_change)
        if not product.is_quantity_only and not product.is_filling_only:
            product.empty_stock_quantity += delivery.empty_returned
        product.stock_weight_kg += product.unit_weight_kg * new_net_stock_change
        product.save()

        # Keep the cylinder ledger synchronized with the edited delivery.
        ledger = delivery.cylinderledger_set.first()
        if product.is_quantity_only or product.is_filling_only:
            if ledger:
                ledger.delete()
        elif (
            delivery.quantity > 0
            or delivery.empty_returned != 0
            or delivery.full_returned > 0
            or delivery.cylinder_movement_type
        ):
            if ledger is None:
                ledger = CylinderLedger(customer=delivery.customer, product=product, delivery=delivery)
            ledger.customer = delivery.customer
            ledger.product = product
            ledger.full_out = delivery.quantity
            ledger.empty_in = delivery.empty_returned + delivery.full_returned
            ledger.ownership_movement = delivery.cylinder_movement_type
            ledger.ownership_quantity = abs(int(entry_data.get('empty_returned', 0) or 0)) if delivery.cylinder_movement_type else 0
            ledger.notes = delivery.remarks or f'Updated entry {delivery.delivery_no}'
            ledger.save()
        elif ledger:
            ledger.delete()
        
        print(f"After update:")
        print(f"  - payment_amount: {delivery.payment_amount}")
        print(f"  - payment_type: {delivery.payment_type}")
        print(f"  - delivery_amount: {delivery.delivery_amount}")
        print(f"  - quantity: {delivery.quantity}")
        print(f"  - unit_price: {delivery.unit_price}")
        
        # Save the delivery
        delivery.save()
        print("Delivery saved successfully")

        _sync_delivery_payments(delivery, request.user)
        _refresh_customer_last_activity(old_customer, delivery.customer)
        
        # Verify save by refreshing from database
        delivery.refresh_from_db()
        print(f"After refresh from DB - payment_amount: {delivery.payment_amount}")
        
        return JsonResponse({
            'success': True,
            'message': 'Entry updated successfully',
            'entry': {
                'id': str(delivery.id),
                'customer_id': str(delivery.customer_id),
                'customer_name': delivery.customer.name,
                'invoice_no': delivery.invoice_no,
                'delivery_charges': float(delivery.delivery_charges),
                'payment': float(delivery.payment_amount or 0),
                'payment_type': delivery.payment_type or 'cash',
                'description': delivery.description,
                'products': [
                    {
                        'product_id': str(delivery.product_id),
                        'product_name': delivery.product.name,
                        'empty': delivery.empty_returned,
                        'full': delivery.quantity,
                        'rate': float(delivery.unit_price),
                        'total': float(delivery.delivery_amount),
                        'full_returned': delivery.full_returned,
                        'full_returned_value': float(delivery.full_returned_value),
                        'full_returned_paid': delivery.full_returned_paid,
                        'cylinder_movement_type': delivery.cylinder_movement_type,
                        'low_pressure_details': delivery.low_pressure_details or [],
                    }
                ]
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        transaction.set_rollback(True)
        return JsonResponse({
            'success': False,
            'entry_number': entry_id or 'Edited record',
            'location': error_location,
            'error': str(e) or e.__class__.__name__,
        })
    
    

@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def delete_entry_api(request):
    """API endpoint to delete a single entry"""
    try:
        data = json.loads(request.body)
        entry_id = data.get('entry_id')
        
        if not entry_id:
            return JsonResponse({'success': False, 'error': 'Entry ID is required'})
        
        try:
            delivery = Delivery.objects.get(pk=uuid.UUID(entry_id))
            _delete_delivery_entry(delivery)
        except Delivery.DoesNotExist:
            payment = get_object_or_404(Payment.objects.select_related('delivery', 'customer'), pk=uuid.UUID(entry_id))
            customer = payment.customer
            if payment.delivery_id:
                delivery = payment.delivery
                if payment.amount > 0:
                    delivery.payment_amount = 0
                elif payment.amount < 0:
                    delivery.full_returned_paid = False
                delivery.save()
            payment.delete()
            _refresh_customer_last_activity(customer)
        
        return JsonResponse({
            'success': True,
            'message': 'Entry deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def clear_entries_api(request):
    """API endpoint to clear entries for a specific date"""
    try:
        data = json.loads(request.body)
        date_str = data.get('date')
        entry_ids = data.get('entry_ids', [])
        
        if date_str:
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                deliveries = Delivery.objects.filter(
                    delivery_date=date_obj,
                    created_by=request.user
                ).select_related('customer', 'product')
                for delivery in deliveries:
                    _delete_delivery_entry(delivery)

                payments = list(Payment.objects.filter(
                    payment_date=date_obj,
                    created_by=request.user,
                    delivery__isnull=True,
                ).select_related('customer'))
                for payment in payments:
                    customer = payment.customer
                    payment.delete()
                    _refresh_customer_last_activity(customer)
                return JsonResponse({'success': True, 'message': 'All entries cleared for this date'})
            except ValueError:
                pass
        
        if entry_ids:
            for entry_id in entry_ids:
                try:
                    delivery = Delivery.objects.filter(
                        id=uuid.UUID(entry_id),
                        created_by=request.user
                    ).select_related('customer', 'product').first()
                    if delivery:
                        _delete_delivery_entry(delivery)
                        continue

                    payment = Payment.objects.filter(
                        id=uuid.UUID(entry_id),
                        created_by=request.user,
                    ).select_related('delivery', 'customer').first()
                    if payment:
                        customer = payment.customer
                        if payment.delivery_id:
                            if payment.amount > 0:
                                payment.delivery.payment_amount = 0
                            elif payment.amount < 0:
                                payment.delivery.full_returned_paid = False
                            payment.delivery.save()
                        payment.delete()
                        _refresh_customer_last_activity(customer)
                except (ValueError, Delivery.DoesNotExist):
                    pass
            return JsonResponse({'success': True, 'message': 'Entries cleared'})
        
        return JsonResponse({'success': False, 'error': 'No entries specified'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@csrf_exempt
@require_http_methods(["POST"])
def save_payment_api(request):
    """API endpoint to save payment only"""
    try:
        data = json.loads(request.body)
        
        customer_id = data.get('customer_id')
        if not customer_id:
            return JsonResponse({'success': False, 'error': 'Customer is required'})
        
        customer = get_object_or_404(Customer, pk=customer_id)
        date_str = data.get('date')
        
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            date_obj = timezone.now().astimezone(PKT).date()
        
        amount = data.get('amount', 0)
        payment_type = data.get('payment_type', 'cash')
        
        payment, _ = create_payment_safely(
            customer=customer,
            amount=amount,
            payment_type=payment_type,
            notes=f"Payment Only on {date_obj}",
            created_by=request.user,
            payment_date=date_obj
        )
        
        customer.last_activity_date = date_obj
        customer.save(update_fields=['last_activity_date', 'updated_at'])
        
        return JsonResponse({
            'success': True,
            'message': 'Payment saved successfully',
            'payment_id': str(payment.id)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
    
 
    
class DailyEntryView(LoginRequiredMixin, TemplateView):
    template_name = 'deliveries/daily_entry_combined.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get date from URL parameter or use today (PKT)
        date_str = self.request.GET.get('date', '')
        selected_date = timezone.now().astimezone(PKT).date()
        
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().astimezone(PKT).date()
        
        # Calculate previous and next dates for navigation
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)
        today = timezone.now().astimezone(PKT).date()
        
        context['selected_date'] = selected_date
        context['prev_date'] = prev_date
        context['next_date'] = next_date
        context['today'] = today
        context['has_next'] = next_date <= today
        
        context['products'] = Product.objects.all().order_by('name')
        context['customers'] = Customer.objects.all().order_by('name')
        
        # Get entries for the selected date
        deliveries = Delivery.objects.filter(delivery_date=selected_date).order_by('created_at')
        payments = Payment.objects.filter(payment_date=selected_date).order_by('created_at')
        
        # Combine activities
        activities = []
        
        # Track matched payments
        matched_payment_ids = set()
        
        # ============================================================
        # MAINTAIN BALANCES PER CUSTOMER
        # ============================================================
        customer_cylinder_balance = {}
        customer_financial_balance = {}
        
        # Initialize financial balances from customer's previous_balance + bf_balance
        all_customers = set()
        for delivery in deliveries:
            all_customers.add(delivery.customer_id)
        for payment in payments:
            all_customers.add(payment.customer_id)
        
        for customer_id in all_customers:
            customer = Customer.objects.get(pk=customer_id)
            customer_financial_balance[customer_id] = customer.get_balance_before_date(selected_date)
            customer_cylinder_balance[customer_id] = customer.get_cylinders_before_date(selected_date)
        
        # Process each delivery as separate row
        for delivery in deliveries:
            created_at_pkt = delivery.created_at.astimezone(PKT) if delivery.created_at else None
            
            linked_payments = [payment for payment in payments if payment.delivery_id == delivery.pk]
            matched_payment_ids.update(payment.id for payment in linked_payments)
            matching_payment = linked_payments[0] if linked_payments else None
            
            # Get customer ID
            customer_id = delivery.customer_id
            
            # Get current cylinder balance for this customer
            current_balance = customer_cylinder_balance.get(customer_id, {})
            
            # Get old cylinder breakdown for display (before this transaction)
            old_cylinders_breakdown = current_balance.copy()
            old_cylinders_total = sum(old_cylinders_breakdown.values())
            
            # Calculate new balance after this transaction (only for cylinder exchange products)
            product_name = delivery.product.name
            if delivery.product and not delivery.is_sale_only:
                product_key = next(
                    (existing for existing in current_balance if existing.casefold() == product_name.casefold()),
                    product_name,
                )
                ownership_quantity = delivery.cylinderledger_set.filter(
                    ownership_movement__in=('customer_received', 'customer_returned')
                ).values_list('ownership_quantity', flat=True).first() or 0
                if delivery.cylinder_movement_type == 'customer_returned':
                    net_change = ownership_quantity
                elif delivery.cylinder_movement_type == 'customer_received':
                    net_change = -ownership_quantity
                else:
                    net_change = delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0)
                # Update the balance for this product
                if product_key not in current_balance:
                    current_balance[product_key] = 0
                current_balance[product_key] += net_change
            
            # Get new cylinder breakdown (after this transaction)
            new_cylinders_breakdown = current_balance.copy()
            new_cylinders_total = sum(new_cylinders_breakdown.values())
            
            # Format breakdown for display
            old_cylinders_parts = []
            new_cylinders_parts = []
            
            for prod_name, balance in old_cylinders_breakdown.items():
                if balance != 0:
                    old_cylinders_parts.append(f"{prod_name}: {balance}")
            old_cylinders_display = ' | '.join(old_cylinders_parts) if old_cylinders_parts else '0'
            
            for prod_name, balance in new_cylinders_breakdown.items():
                if balance != 0:
                    new_cylinders_parts.append(f"{prod_name}: {balance}")
            new_cylinders_display = ' | '.join(new_cylinders_parts) if new_cylinders_parts else '0'
            
            # ============================================================
            # FINANCIAL BALANCE CALCULATION
            # ============================================================
            # Get current financial balance for this customer
            old_balance = customer_financial_balance.get(customer_id, 0)
            
            # Calculate new balance after this transaction
            delivery_amount = float(delivery.delivery_amount)
            delivery_charges = float(delivery.delivery_charges) if delivery.delivery_charges else 0
            total_before_delivery_charges = delivery_amount - delivery_charges
            
            # IMPORTANT: Use delivery.payment_amount (not matching payment)
            payment_amount = sum(float(payment.amount) for payment in linked_payments)
            
            # Total includes delivery charges
            new_balance = old_balance + delivery_amount - payment_amount
            
            # Update financial balance for this customer
            customer_financial_balance[customer_id] = new_balance
            
            # Create items list
            display_empty_returned = delivery.empty_returned or 0
            if delivery.cylinder_movement_type in ('customer_received', 'customer_returned'):
                display_empty_returned = delivery.cylinderledger_set.filter(
                    ownership_movement=delivery.cylinder_movement_type
                ).values_list('ownership_quantity', flat=True).first() or 0

            items = [{
                'product': delivery.product.name,
                'quantity': delivery.quantity,
                'empty_returned': display_empty_returned,
                'amount': float(delivery.delivery_amount),
                'delivery_no': delivery.delivery_no,
                'unit_price': float(delivery.unit_price),
                'personal_details': '',
                'is_quantity_only': delivery.is_sale_only
            }]
            
            invoice_no = delivery.invoice_no or delivery.delivery_no

            # ============================================================
            # CRITICAL FIX: Use delivery.payment_amount and delivery.payment_type
            # ============================================================
            display_empty_returned = delivery.empty_returned or 0
            if delivery.cylinder_movement_type in ('customer_received', 'customer_returned'):
                display_empty_returned = delivery.cylinderledger_set.filter(
                    ownership_movement=delivery.cylinder_movement_type
                ).values_list('ownership_quantity', flat=True).first() or 0

            activity = {
                'id': str(delivery.id),
                'type': 'delivery',
                'customer': delivery.customer,
                'customer_name': delivery.customer.name,
                'customer_mobile': delivery.customer.mobile,
                'customer_code': delivery.customer.customer_code,
                'items': items,
                'total_quantity': delivery.quantity,
                'total_empty': display_empty_returned,
                'delivery_amount': delivery_amount,
                'delivery_charges': delivery_charges,
                'damage_charges': float(delivery.damage_charges) if delivery.damage_charges else 0,  # ✅ ADD THIS
                'total_before_delivery_charges': total_before_delivery_charges,
                'total_after_delivery_charges': delivery_amount,
                'created_at': delivery.created_at,
                'created_time': created_at_pkt.strftime('%I:%M %p') if created_at_pkt else 'N/A',
                'created_date': created_at_pkt.strftime('%Y-%m-%d') if created_at_pkt else 'N/A',
                'has_payment': delivery.payment_amount > 0,
                'payment_amount': payment_amount,
                'payment_type': delivery.payment_type or 'cash',
                'old_balance': old_balance,
                'new_balance': new_balance,
                'old_cylinders_total': old_cylinders_total,
                'new_cylinders_total': new_cylinders_total,
                'old_cylinders_display': old_cylinders_display,
                'new_cylinders_display': new_cylinders_display,
                'old_cylinders_breakdown': old_cylinders_breakdown,
                'new_cylinders_breakdown': new_cylinders_breakdown,
                'is_payment_only': False,
                'invoice_no': invoice_no,
                'unit_price': float(delivery.unit_price),
                'description': delivery.description or '',
                'low_pressure_details': delivery.low_pressure_details or [],
                'full_returned': delivery.full_returned or 0,
                'full_returned_value': float(delivery.full_returned_value) if delivery.full_returned_value else 0,
                'full_returned_paid': delivery.full_returned_paid or False,
                'calculation_details': delivery.calculation_details,
                'return_details': delivery.return_details,
            }
            activities.append(activity)
        
        # Add payment only entries (for payments that were NOT matched to any delivery)
        for payment in payments:
            if payment.id in matched_payment_ids:
                continue
            
            created_at_pkt = payment.created_at.astimezone(PKT) if payment.created_at else None
            
            customer_id = payment.customer_id
            
            # Get current cylinder balance
            current_balance = customer_cylinder_balance.get(customer_id, {})
            old_cylinders_breakdown = current_balance.copy()
            old_cylinders_total = sum(old_cylinders_breakdown.values())
            old_cylinders_parts = []
            for prod_name, balance in old_cylinders_breakdown.items():
                if balance != 0:
                    old_cylinders_parts.append(f"{prod_name}: {balance}")
            old_cylinders_display = ' | '.join(old_cylinders_parts) if old_cylinders_parts else '0'
            
            # Financial balance - payment reduces balance
            old_balance = customer_financial_balance.get(customer_id, 0)
            payment_amount = float(payment.amount)
            new_balance = old_balance - payment_amount
            customer_financial_balance[customer_id] = new_balance
            
            activity = {
                'id': str(payment.id),
                'type': 'payment_only',
                'customer': payment.customer,
                'customer_name': payment.customer.name,
                'customer_mobile': payment.customer.mobile,
                'customer_code': payment.customer.customer_code,
                'items': [],
                'total_quantity': 0,
                'total_empty': 0,
                'delivery_amount': 0,
                'delivery_charges': 0,
                'created_at': payment.created_at,
                'created_time': created_at_pkt.strftime('%I:%M %p') if created_at_pkt else 'N/A',
                'created_date': created_at_pkt.strftime('%Y-%m-%d') if created_at_pkt else 'N/A',
                'has_payment': True,
                'payment_amount': payment_amount,
                'payment_type': payment.get_payment_type_display(),
                'old_balance': old_balance,
                'new_balance': new_balance,
                'old_cylinders_total': old_cylinders_total,
                'new_cylinders_total': old_cylinders_total,
                'old_cylinders_display': old_cylinders_display,
                'new_cylinders_display': old_cylinders_display,
                'old_cylinders_breakdown': old_cylinders_breakdown,
                'new_cylinders_breakdown': old_cylinders_breakdown,
                'is_payment_only': True,
                'invoice_no': payment.invoice_no or payment.payment_no,
                'unit_price': 0,
                'description': '',
            }
            activities.append(activity)
        
        # Sort by created_at (oldest first)
        activities.sort(key=lambda x: x['created_at'])

        transaction_filters = self.request.GET.getlist('transaction_filter')
        valid_transaction_filters = {'full_no_empty', 'credit', 'partial_payment'}
        transaction_filters = [value for value in transaction_filters if value in valid_transaction_filters]

        def matches_transaction_filter(activity):
            if activity['type'] != 'delivery':
                return False
            item = activity['items'][0] if activity['items'] else {}
            is_cylinder_delivery = not item.get('is_quantity_only', False)
            payment_amount = float(activity.get('payment_amount') or 0)
            delivery_amount = float(activity.get('total_after_delivery_charges') or activity.get('delivery_amount') or 0)

            if 'full_no_empty' in transaction_filters and is_cylinder_delivery and float(activity.get('total_quantity') or 0) > 0 and float(activity.get('total_empty') or 0) == 0:
                return True
            if 'credit' in transaction_filters and delivery_amount > 0 and payment_amount <= 0:
                return True
            if 'partial_payment' in transaction_filters and delivery_amount > 0 and payment_amount > 0 and (
                    payment_amount < delivery_amount or
                    float(activity.get('new_balance') or 0) > 0
                ):
                return True
            return False

        if transaction_filters:
            activities = [activity for activity in activities if matches_transaction_filter(activity)]

        context['activities'] = activities
        context['transaction_filters'] = transaction_filters
        context['transaction_filter_query'] = urlencode([('transaction_filter', value) for value in transaction_filters])
        context['transaction_filter_choices'] = [
            ('', 'All transactions'),
            ('full_no_empty', 'Full cylinders delivered, no empties returned'),
            ('credit', 'Credit: no immediate payment'),
            ('partial_payment', 'Partial payment: balance remains'),
        ]
        
        # Calculate totals
        # Calculate totals
        context['total_activities'] = len(activities)
        context['total_deliveries'] = len([a for a in activities if a['type'] == 'delivery'])
        context['total_payments'] = len([a for a in activities if a['type'] == 'payment_only'])
        context['total_quantity'] = sum([a['total_quantity'] for a in activities if a['type'] == 'delivery' and not a['items'][0].get('is_quantity_only')])
        context['total_empty'] = sum([a['total_empty'] for a in activities if a['type'] == 'delivery' and not a['items'][0].get('is_quantity_only')])
        context['total_sale_quantity'] = sum([a['total_quantity'] for a in activities if a['type'] == 'delivery' and a['items'][0].get('is_quantity_only')])
        context['total_delivery_amount'] = sum([a['delivery_amount'] for a in activities if a['type'] == 'delivery'])
        context['total_delivery_charges'] = sum([a['delivery_charges'] for a in activities if a['type'] == 'delivery'])
        context['total_damage_charges'] = sum([a.get('damage_charges', 0) for a in activities if a['type'] == 'delivery'])  # ✅ Already there
        context['total_before_delivery_charges'] = sum([a.get('total_before_delivery_charges', a.get('delivery_amount', 0)) for a in activities if a['type'] == 'delivery'])
        context['total_after_delivery_charges'] = sum([a.get('total_after_delivery_charges', a.get('delivery_amount', 0)) for a in activities if a['type'] == 'delivery'])
        context['total_payment_amount'] = sum([a['payment_amount'] for a in activities if a['type'] == 'delivery' or a['type'] == 'payment_only'])        
        return context
    
    def _save_individual_entry(self, request, data):
        
        """Save a single individual entry via AJAX JSON request"""
        entry_data = data.get('entry_data', {})
        entry_number = entry_data.get('entry_number') or 1

        def entry_error(error, location):
            return JsonResponse({
                'success': False,
                'entry_number': entry_number,
                'location': location,
                'error': error,
            }, status=400)

        if not entry_data:
            return entry_error('No entry data provided.', 'Entry details')
        
        selected_date_str = entry_data.get('selected_date', '')
        if selected_date_str:
            try:
                selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().astimezone(PKT).date()
        else:
            selected_date = timezone.now().astimezone(PKT).date()
        
        is_existing = entry_data.get('is_existing', True)
        is_walkin = entry_data.get('is_walkin', False)
        product_items = entry_data.get('products', [])
        
        with transaction.atomic():
            # Handle Walk-in Customer
            request.daily_entry_location = 'Customer details'
            if is_walkin:
                walkin_name = (entry_data.get('walkin_name') or entry_data.get('walkin_customer_name') or '').strip()
                walkin_mobile = (entry_data.get('walkin_mobile') or entry_data.get('walkin_customer_mobile') or '').strip()
                if walkin_mobile == 'N/A':
                    walkin_mobile = ''
                security_deposit = float(entry_data.get('security_deposit', 0) or 0)
                personal_cylinders = int(entry_data.get('personal_cylinders', 0) or 0)

                customer_name = walkin_name if walkin_name else 'Walk-in Customer'
                customer = Customer.get_or_create_walkin(
                    name=customer_name,
                    mobile=walkin_mobile,
                    security_deposit=security_deposit,
                    personal_cylinders=personal_cylinders,
                    last_activity_date=selected_date,
                )
                customer_name = customer.name
            elif is_existing:
                customer_id = entry_data.get('customer_id')
                if not customer_id:
                    return entry_error('Please select a customer.', 'Customer')
                customer = get_object_or_404(Customer, pk=customer_id)
                customer_name = customer.name
            else:
                new_name = entry_data.get('new_customer_name', '').strip()
                new_mobile = entry_data.get('new_customer_mobile', '').strip()
                if not new_name:
                    return entry_error('Customer name is required for a new customer.', 'New customer name')
                
                security_deposit = float(entry_data.get('security_deposit', 0) or 0)
                personal_cylinders = int(entry_data.get('personal_cylinders', 0) or 0)
                
                customer = Customer.objects.create(
                    name=new_name,
                    mobile=new_mobile,
                    security_deposit=security_deposit,
                    personal_cylinders=personal_cylinders,
                    last_activity_date=selected_date
                )
                customer_name = customer.name
            
            products_data = product_items
            if not products_data:
                return entry_error('Add a product or payment before saving.', 'Product / payment details')
            
            deliveries_created = 0
            payments_created = 0
            
            for product_row, item in enumerate(products_data, start=1):
                request.daily_entry_location = f'Product row {product_row} / Product'
                product_id = item.get('product_id')
                item_payment_amount = float(item.get('payment_amount', 0) or 0)
                item_payment_type = item.get('payment_type', 'cash')
                item_invoice_no = (item.get('invoice_no') or '').strip()
                if not product_id:
                    if item_payment_amount > 0:
                        payment_notes = f'Payment Only on {selected_date}'
                        if item_invoice_no:
                            payment_notes += f' (Invoice: {item_invoice_no})'
                        payment, created = create_payment_safely(
                            customer=customer,
                            amount=item_payment_amount,
                            payment_type=item_payment_type,
                            invoice_no=item_invoice_no,
                            notes=payment_notes,
                            created_by=request.user,
                            payment_date=selected_date,
                        )
                        if created:
                            payments_created += 1
                    continue
                
                product = get_object_or_404(Product, pk=product_id)
                request.daily_entry_location = f'Product row {product_row} / Sale quantity'
                sale_quantity = float(item.get('sale_quantity', 0) or 0)
                request.daily_entry_location = f'Product row {product_row} / Full quantity'
                full_quantity = float(item.get('quantity', 0) or 0)
                request.daily_entry_location = f'Product row {product_row} / Empty returned'
                empty_returned_val = float(item.get('empty_returned', 0) or 0)
                # FILLING-ONLY products treat entered weight as the gas amount (kg) and
                # intentionally do not exchange an empty cylinder from customer to company.
                if product.is_filling_only:
                    full_quantity = max(full_quantity, sale_quantity)
                    empty_returned_val = 0
                cylinder_movement_type = item.get('cylinder_movement_type', '')
                if item.get('return_empty_to_customer', False):
                    cylinder_movement_type = 'customer_returned'
                
                # NEW: Get damage charges
                request.daily_entry_location = f'Product row {product_row} / Damage charges'
                damage_charges = float(item.get('damage_charges', 0) or 0)
                            
                if sale_quantity > 0 or product.is_quantity_only or product.is_filling_only:
                    quantity = sale_quantity if sale_quantity > 0 else full_quantity
                    empty_returned = 0
                    is_sale_only_item = True
                else:
                    quantity = full_quantity
                    empty_returned = empty_returned_val
                    is_sale_only_item = False

                if cylinder_movement_type in ('customer_received', 'customer_returned'):
                    quantity = 0
                    empty_returned = 0
                    is_sale_only_item = False
                    ownership_quantity = abs(int(empty_returned_val))
                    if ownership_quantity < 1:
                        return JsonResponse({
                            'success': False,
                            'entry_number': entry_number,
                            'location': f'Product row {product_row} / Customer-owned cylinder quantity',
                            'error': 'Enter the customer-owned cylinder quantity.',
                        }, status=400)
                    company_held_from_bf = max(
                        -sum(
                            int(quantity or 0)
                            for name, quantity in (customer.bf_cylinders or {}).items()
                            if name.casefold() == product.name.casefold()
                        ),
                        0
                    )
                    ownership_ledger_balance = sum(
                        entry.ownership_quantity if entry.ownership_movement == 'customer_received' else -entry.ownership_quantity
                        for entry in CylinderLedger.objects.filter(customer=customer, product=product)
                        if entry.ownership_movement in ('customer_received', 'customer_returned')
                    )
                    available_for_return = company_held_from_bf + ownership_ledger_balance
                    if cylinder_movement_type == 'customer_returned' and ownership_quantity > available_for_return:
                        return JsonResponse({
                            'success': False,
                            'entry_number': entry_number,
                            'location': f'Product row {product_row} / Customer-owned cylinder return',
                            'error': f'The customer does not have {ownership_quantity} customer-owned {product.name} cylinders held by the company.'
                        }, status=400)
                    damage_charges = 0
                    full_returned = 0
                    full_returned_value = 0
                    full_returned_paid = False
                    delivery_charges = 0
                    payment_amount = 0
                
                request.daily_entry_location = f'Product row {product_row} / Rate'
                unit_price = float(item.get('rate', 0) or 0) or float(product.unit_price)
                request.daily_entry_location = f'Product row {product_row} / Delivery charges'
                delivery_charges = float(item.get('delivery_charges', 0) or 0)
                request.daily_entry_location = f'Product row {product_row} / Payment amount'
                payment_amount = float(item.get('payment_amount', 0) or 0)
                payment_type = item.get('payment_type', 'cash')
                invoice_no = item.get('invoice_no', '')
                description = item.get('description', '')
                low_pressure_details = item.get('low_pressure_details', [])
                
                # Full returned cylinder fields
                request.daily_entry_location = f'Product row {product_row} / Full return quantity'
                full_returned = int(item.get('full_returned', 0) or 0)
                request.daily_entry_location = f'Product row {product_row} / Full return value'
                full_returned_value = float(item.get('full_returned_value', 0) or 0)
                full_returned_paid = bool(item.get('full_returned_paid', False))

                if full_returned < 0 or full_returned_value < 0:
                    return JsonResponse({
                        'success': False,
                        'entry_number': entry_number,
                        'location': f'Product row {product_row} / Full return quantity or value',
                        'error': 'Full return quantity and value cannot be negative.',
                    }, status=400)
                if full_returned == 0:
                    full_returned_value = 0
                
                if quantity <= 0 and empty_returned == 0 and damage_charges <= 0 and len(low_pressure_details) == 0 and full_returned <= 0 and not cylinder_movement_type:
                    continue
                
                remarks = f"Individual Entry on {selected_date}"
                if is_walkin:
                    remarks += " (Walk-in)"
                if invoice_no:
                    remarks += f" | Invoice: {invoice_no}"
                if cylinder_movement_type == 'customer_received':
                    remarks += f" | Customer-owned Empty Cylinder Received: {ownership_quantity}"
                elif cylinder_movement_type == 'customer_returned':
                    remarks += f" | Customer-owned Empty Cylinder Returned: {ownership_quantity}"
                if full_returned > 0:
                    remarks += f" | Full Returned: {full_returned}"
                
                # ============================================================
                # CREATE DELIVERY RECORD
                # ============================================================
                delivery = Delivery.objects.create(
                    customer=customer,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    empty_returned=empty_returned,
                    full_delivered=quantity,
                    full_returned=full_returned,
                    full_returned_value=full_returned_value,
                    full_returned_paid=full_returned_paid,
                    delivery_date=selected_date,
                    remarks=remarks,
                    invoice_no=invoice_no,
                    description=description,
                    delivery_charges=delivery_charges,
                    damage_charges=damage_charges,
                    low_pressure_details=low_pressure_details,
                    payment_amount=payment_amount,
                    payment_type=payment_type,
                    cylinder_movement_type=cylinder_movement_type,
                    created_by=request.user
                )
                deliveries_created += 1
                
                # Update stock (Full returned cylinders INCREASE stock, quantity given DECREASES stock)
                net_stock_change = full_returned - int(quantity)
                if net_stock_change != 0:
                    product.stock_quantity += int(stock_quantity_for_delivery(product, net_stock_change))
                    product.stock_weight_kg += product.unit_weight_kg * net_stock_change
                if not is_sale_only_item:
                    product.empty_stock_quantity += empty_returned
                product.save()
                
                # Cylinder Ledger (empty_in includes both empty_returned and full_returned)
                total_returned = empty_returned + full_returned
                if not is_sale_only_item and (quantity > 0 or total_returned != 0 or cylinder_movement_type):
                    CylinderLedger.objects.create(
                        customer=customer,
                        product=product,
                        full_out=quantity,
                        empty_in=total_returned,
                        delivery=delivery,
                        ownership_movement=cylinder_movement_type,
                        ownership_quantity=ownership_quantity if cylinder_movement_type else 0,
                        notes=remarks
                    )
                
                # A cash-paid return is a cash outflow; an unpaid return is already
                # represented by the credit deducted from delivery_amount.
                if full_returned_value > 0 and full_returned_paid:
                    payment, created = create_payment_safely(
                        customer=customer,
                        amount=-full_returned_value,
                        payment_type='cash',
                        notes=f"Cash paid for full cylinder return - {product.name} ({full_returned} Full Returned)",
                        payment_date=selected_date,
                        created_by=request.user,
                        delivery=delivery,
                    )
                    if created:
                        payments_created += 1
                
                # Payment
                if payment_amount > 0:
                    payment, created = create_payment_safely(
                        customer=customer,
                        amount=payment_amount,
                        payment_type=payment_type,
                        notes=f"Payment for {product.name} on {selected_date} (Invoice: {invoice_no if invoice_no else 'N/A'})",
                        created_by=request.user,
                        payment_date=selected_date,
                        invoice_no=invoice_no or '',
                        delivery=delivery,
                    )
                    if created:
                        payments_created += 1
            
            if deliveries_created > 0 or payments_created > 0:
                customer.last_activity_date = selected_date
                customer.save(update_fields=['last_activity_date', 'updated_at'])
                return JsonResponse({
                    'success': True, 
                    'message': f'✅ {"Walk-in " if is_walkin else ""}Entry saved successfully for {customer_name}!'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'entry_number': entry_number,
                    'location': 'Product / payment details',
                    'error': 'No valid products or payments were saved. Enter a product quantity, return, damage charge, or payment.',
                }, status=400)
            
    
    def post(self, request, *args, **kwargs):
        try:
            return self._post_daily_entries(request, *args, **kwargs)
        except Exception as exc:
            entry_number = getattr(request, 'daily_entry_number', None) or 1
            location = getattr(request, 'daily_entry_location', 'Entry details')
            reason = str(exc).strip() or exc.__class__.__name__
            logger.exception(
                'Daily entry save failed at entry #%s, %s',
                entry_number,
                location,
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'entry_number': entry_number,
                    'location': location,
                    'error': reason,
                }, status=400)

            messages.error(
                request,
                f'Entry #{entry_number} could not be saved at {location}: {reason}',
                extra_tags='daily-entry-error',
            )
            selected_date = request.POST.get('selected_date', '')
            return redirect(f'{request.path}?date={selected_date}')

    def _post_daily_entries(self, request, *args, **kwargs):
        """Handle POST requests for adding multiple entries with different customers"""
        
        # ============================================================
        # HANDLE JSON REQUESTS FOR INDIVIDUAL ENTRY SAVES
        # ============================================================
        if request.content_type == 'application/json':
            import json
            try:
                data = json.loads(request.body)
                save_type = data.get('save_type', 'all')
                
                if save_type == 'individual':
                    request.daily_entry_number = data.get('entry_data', {}).get('entry_number') or 1
                    request.daily_entry_location = 'Customer details'
                    return self._save_individual_entry(request, data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        
        # ============================================================
        # HANDLE REGULAR FORM POSTS FOR SAVING ALL ENTRIES
        # ============================================================
        with transaction.atomic():
            entries_created = 0
            total_deliveries = []
            total_payments_made = 0
            
            # Get the selected date from form or use today
            selected_date_str = request.POST.get('selected_date', '')
            if selected_date_str:
                try:
                    selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
                except ValueError:
                    selected_date = timezone.now().astimezone(PKT).date()
            else:
                selected_date = timezone.now().astimezone(PKT).date()
            
            # Debug: Print all POST data
            print("=" * 50)
            print(f"POST DATA RECEIVED for date: {selected_date}")
            for key, value in request.POST.items():
                print(f"  {key}: {value}")
            print("=" * 50)
            
            # Find all entry blocks (up to 200)
            entry_numbers_with_data = []
            for entry_num in range(1, 201):
                customer_type_key = f'customer_type_{entry_num}'
                is_walkin = request.POST.get(f'walkin_flag_{entry_num}') == 'true'
                if customer_type_key not in request.POST and not is_walkin:
                    continue
                
                request.daily_entry_number = entry_num
                request.daily_entry_location = 'Customer details'
                print(f"\n--- Processing Entry #{entry_num} ---")
                entry_fields = (
                    'customer_type', 'customer_id', 'new_name', 'new_mobile',
                    'new_security', 'new_personal_cylinders', 'walkin_flag',
                    'walkin_name', 'walkin_mobile', 'walkin_security',
                    'walkin_personal', 'invoice_numbers', 'product_ids',
                    'personal_details', 'empty_returns', 'cylinder_movements', 'quantities',
                    'sale_quantities', 'product_prices', 'delivery_charges',
                    'damage_charges', 'payment_amount', 'payment_type',
                    'description', 'low_pressure_json', 'full_returned',
                    'full_returned_value', 'full_returned_paid',
                )
                array_fields = {
                    'invoice_numbers', 'product_ids', 'personal_details', 'empty_returns',
                    'cylinder_movements', 'quantities', 'sale_quantities',
                    'product_prices', 'delivery_charges', 'damage_charges',
                    'payment_amount', 'payment_type', 'description',
                    'low_pressure_json', 'full_returned', 'full_returned_value',
                    'full_returned_paid',
                }
                ignored_values = {'', '0', '0.0', '0.00', 'false', 'cash', 'existing', '[]'}
                entry_has_data = any(
                    value.strip().casefold() not in ignored_values
                    for field in entry_fields
                    for value in request.POST.getlist(
                        f'{field}_{entry_num}' + ('[]' if field in array_fields else '')
                    )
                    if isinstance(value, str)
                )
                if not entry_has_data:
                    continue
                if entry_has_data:
                    entry_numbers_with_data.append(entry_num)
                
                # Get customer for this entry
                customer_type = request.POST.get(customer_type_key)
                
                if is_walkin:
                    walkin_name = request.POST.get(f'walkin_name_{entry_num}', '').strip()
                    walkin_mobile = request.POST.get(f'walkin_mobile_{entry_num}', '').strip()
                    if walkin_mobile == 'N/A':
                        walkin_mobile = ''
                    security_deposit = request.POST.get(f'walkin_security_{entry_num}', '0')
                    personal_cylinders = request.POST.get(f'walkin_personal_{entry_num}', '0')
                    
                    try:
                        security_deposit = float(security_deposit) if security_deposit else 0
                    except (ValueError, TypeError):
                        security_deposit = 0
                    try:
                        personal_cylinders = int(personal_cylinders) if personal_cylinders else 0
                    except (ValueError, TypeError):
                        personal_cylinders = 0
                        
                    customer_name = walkin_name or "Walk-in Customer"
                    customer = Customer.get_or_create_walkin(
                        name=customer_name,
                        mobile=walkin_mobile,
                        security_deposit=security_deposit,
                        personal_cylinders=personal_cylinders,
                        last_activity_date=selected_date,
                    )
                    print(f"  Customer (Walk-in): {customer.name}, Mobile: {walkin_mobile}, Security: {security_deposit}, Personal: {personal_cylinders}")
                elif customer_type == 'existing':
                    customer_id = request.POST.get(f'customer_id_{entry_num}')
                    if not customer_id:
                        if entry_has_data:
                            request.daily_entry_location = 'Customer'
                            raise ValueError('Select a customer before entering products or payments.')
                        continue
                    customer = get_object_or_404(Customer, pk=customer_id)
                    print(f"  Customer (Existing): {customer.name} (ID: {customer_id})")
                else:
                    name = request.POST.get(f'new_name_{entry_num}', '').strip()
                    mobile = request.POST.get(f'new_mobile_{entry_num}', '').strip()
                    if not name:
                        if entry_has_data:
                            request.daily_entry_location = 'Customer name'
                            raise ValueError('Enter a customer name before entering products or payments.')
                        continue
                    
                    # Get new fields - Security Deposit and Personal Cylinders
                    security_deposit = request.POST.get(f'new_security_{entry_num}', '0')
                    personal_cylinders = request.POST.get(f'new_personal_cylinders_{entry_num}', '0')
                    
                    try:
                        security_deposit = float(security_deposit) if security_deposit else 0
                    except (ValueError, TypeError):
                        security_deposit = 0
                    
                    try:
                        personal_cylinders = int(personal_cylinders) if personal_cylinders else 0
                    except (ValueError, TypeError):
                        personal_cylinders = 0
                    
                    customer = Customer.objects.create(
                        name=name,
                        mobile=mobile,
                        security_deposit=security_deposit if security_deposit else 0,
                        personal_cylinders=personal_cylinders if personal_cylinders else 0,
                        last_activity_date=selected_date
                    )
                    print(f"  Customer (New): {customer.name}, Security: {security_deposit}, Personal: {personal_cylinders}")
                
                # Get products for this entry
                # Get products for this entry
                product_ids = request.POST.getlist(f'product_ids_{entry_num}[]')
                quantities = request.POST.getlist(f'quantities_{entry_num}[]')
                sale_quantities = request.POST.getlist(f'sale_quantities_{entry_num}[]')
                empty_returns = request.POST.getlist(f'empty_returns_{entry_num}[]')
                cylinder_movements = request.POST.getlist(f'cylinder_movements_{entry_num}[]')
                product_prices = request.POST.getlist(f'product_prices_{entry_num}[]')
                invoice_numbers = request.POST.getlist(f'invoice_numbers_{entry_num}[]')
                personal_details = request.POST.getlist(f'personal_details_{entry_num}[]')
                delivery_charges = request.POST.getlist(f'delivery_charges_{entry_num}[]')
                damage_charges = request.POST.getlist(f'damage_charges_{entry_num}[]')  # ✅ This must be here
                payment_amounts = request.POST.getlist(f'payment_amount_{entry_num}[]')
                payment_types = request.POST.getlist(f'payment_type_{entry_num}[]')
                descriptions = request.POST.getlist(f'description_{entry_num}[]')
                low_pressure_jsons = request.POST.getlist(f'low_pressure_json_{entry_num}[]')
                full_returns = request.POST.getlist(f'full_returned_{entry_num}[]')
                full_return_values = request.POST.getlist(f'full_returned_value_{entry_num}[]')
                full_return_paids = request.POST.getlist(f'full_returned_paid_{entry_num}[]')

                print(f"  Product IDs: {product_ids}")
                print(f"  Quantities: {quantities}")
                print(f"  Sale Quantities: {sale_quantities}")
                print(f"  Delivery Charges: {delivery_charges}")
                print(f"  Damage Charges: {damage_charges}")
                print(f"  Payment Amounts: {payment_amounts}")
                print(f"  Payment Types: {payment_types}")

                deliveries_created = []
                payments_before_entry = total_payments_made

                row_count = max(len(product_ids), len(invoice_numbers), len(payment_amounts), len(payment_types))
                for i in range(row_count):
                    request.daily_entry_location = f'Product row {i + 1} / Product'
                    product_id = product_ids[i] if i < len(product_ids) else ''
                    invoice_no = invoice_numbers[i].strip() if i < len(invoice_numbers) else ''
                    try:
                        row_payment_amount = float(payment_amounts[i]) if i < len(payment_amounts) and payment_amounts[i] else 0
                    except (ValueError, TypeError):
                        row_payment_amount = 0
                    row_payment_type = payment_types[i] if i < len(payment_types) and payment_types[i] else 'cash'

                    if not product_id:
                        if row_payment_amount > 0:
                            payment_notes = f'Payment Only on {selected_date}'
                            if invoice_no:
                                payment_notes += f' (Invoice: {invoice_no})'
                            payment, created = create_payment_safely(
                                customer=customer,
                                amount=row_payment_amount,
                                payment_type=row_payment_type,
                                invoice_no=invoice_no,
                                notes=payment_notes,
                                created_by=request.user,
                                payment_date=selected_date,
                            )
                            if created:
                                total_payments_made += 1
                        else:
                            row_fields = (
                                ('invoice_numbers', invoice_numbers),
                                ('personal_details', personal_details),
                                ('quantities', quantities),
                                ('sale_quantities', sale_quantities),
                                ('empty_returns', empty_returns),
                                ('cylinder_movements', cylinder_movements),
                                ('product_prices', product_prices),
                                ('delivery_charges', delivery_charges),
                                ('damage_charges', damage_charges),
                                ('descriptions', descriptions),
                                ('low_pressure_json', low_pressure_jsons),
                                ('full_returned', full_returns),
                                ('full_returned_value', full_return_values),
                            )
                            row_has_data = any(
                                values[i].strip().casefold() not in ignored_values
                                for _, values in row_fields
                                if i < len(values)
                            )
                            if row_has_data:
                                request.daily_entry_location = f'Product row {i + 1} / Product or payment amount'
                                raise ValueError('Select a product or enter a payment amount for this row.')
                        continue
                    
                    product = get_object_or_404(Product, pk=product_id)
                    
                    try:
                        request.daily_entry_location = f'Product row {i + 1} / Sale quantity'
                        sq_val = float(sale_quantities[i]) if i < len(sale_quantities) and sale_quantities[i] else 0
                    except (ValueError, TypeError):
                        sq_val = 0
                        
                    try:
                        request.daily_entry_location = f'Product row {i + 1} / Full quantity'
                        fq_val = float(quantities[i]) if i < len(quantities) and quantities[i] else 0
                    except (ValueError, TypeError):
                        fq_val = 0
                        
                    try:
                        request.daily_entry_location = f'Product row {i + 1} / Empty returned'
                        eq_val = float(empty_returns[i]) if i < len(empty_returns) and empty_returns[i] else 0
                    except (ValueError, TypeError):
                        eq_val = 0

                    cylinder_movement_type = (
                        cylinder_movements[i] if i < len(cylinder_movements) else ''
                    )
                    
                    # Full returned cylinder values
                    try:
                        full_returned_val = int(full_returns[i]) if i < len(full_returns) and full_returns[i] else 0
                    except (ValueError, TypeError):
                        full_returned_val = 0
                        
                    try:
                        full_returned_val_amount = float(full_return_values[i]) if i < len(full_return_values) and full_return_values[i] else 0
                    except (ValueError, TypeError):
                        full_returned_val_amount = 0
                        
                    full_returned_paid_val = (full_return_paids[i] == 'true') if i < len(full_return_paids) and full_return_paids[i] else False

                    if full_returned_val < 0 or full_returned_val_amount < 0:
                        request.daily_entry_location = f'Product row {i + 1} / Full return quantity or value'
                        raise ValueError('Full return quantity and value cannot be negative.')
                    if full_returned_val == 0:
                        full_returned_val_amount = 0
                    
                    # ============================================================
                    # GET DAMAGE CHARGES VALUE
                    # ============================================================
                    damage_charges_value = 0
                    if i < len(damage_charges) and damage_charges[i]:
                        try:
                            damage_charges_value = float(damage_charges[i])
                        except (ValueError, TypeError):
                            damage_charges_value = 0
                    
                    # ============================================================
                    # GET LOW PRESSURE DETAILS VALUE
                    # ============================================================
                    low_pressure_details = []
                    if i < len(low_pressure_jsons) and low_pressure_jsons[i]:
                        try:
                            low_pressure_details = json.loads(low_pressure_jsons[i])
                        except (TypeError, ValueError) as exc:
                            request.daily_entry_location = f'Product row {i + 1} / Low pressure details'
                            raise ValueError('Low pressure details contain invalid data.') from exc
                    
                    # ============================================================
                    # CHECK: quantity, empty returns, damage charges, low pressure, OR full returned
                    # ============================================================
                    if sq_val > 0 or product.is_quantity_only or product.is_filling_only:
                        quantity = sq_val if sq_val > 0 else fq_val
                        empty_returned = 0
                        is_sale_only_item = True
                    else:
                        quantity = fq_val
                        empty_returned = eq_val
                        is_sale_only_item = False

                    ownership_quantity = abs(int(eq_val))
                    if cylinder_movement_type in ('customer_received', 'customer_returned'):
                        quantity = 0
                        empty_returned = 0
                        is_sale_only_item = False
                        if ownership_quantity < 1:
                            request.daily_entry_location = f'Product row {i + 1} / Customer-owned cylinder quantity'
                            raise ValueError('Enter the customer-owned cylinder quantity.')
                        if cylinder_movement_type == 'customer_returned':
                            company_held_from_bf = max(-sum(
                                int(value or 0)
                                for name, value in (customer.bf_cylinders or {}).items()
                                if name.casefold() == product.name.casefold()
                            ), 0)
                            ownership_ledger_balance = sum(
                                entry.ownership_quantity if entry.ownership_movement == 'customer_received'
                                else -entry.ownership_quantity
                                for entry in CylinderLedger.objects.filter(customer=customer, product=product)
                                if entry.ownership_movement in ('customer_received', 'customer_returned')
                            )
                            if ownership_quantity > company_held_from_bf + ownership_ledger_balance:
                                request.daily_entry_location = f'Product row {i + 1} / Customer-owned cylinder return'
                                raise ValueError(
                                    f'The customer does not have {ownership_quantity} customer-owned '
                                    f'{product.name} cylinders held by the company.'
                                )
                    
                    # ============================================================
                    # VALIDATE ENTRY
                    # ============================================================
                    if quantity <= 0 and empty_returned <= 0 and damage_charges_value <= 0 and len(low_pressure_details) == 0 and full_returned_val <= 0 and not cylinder_movement_type:
                        request.daily_entry_location = f'Product row {i + 1} / Quantity or return details'
                        raise ValueError(
                            'Enter a quantity, empty return, damage charge, low-pressure detail, '
                            'full return, or cylinder movement for the selected product.'
                        )
                    
                    # ============================================================
                    # GET OTHER VALUES
                    # ============================================================
                    request.daily_entry_location = f'Product row {i + 1} / Rate'
                    unit_price = float(product_prices[i]) if i < len(product_prices) and product_prices[i] else float(product.unit_price)
                    personal_note = personal_details[i] if i < len(personal_details) and personal_details[i] else ''
                    invoice_no = invoice_numbers[i] if i < len(invoice_numbers) and invoice_numbers[i] else ''
                    description = descriptions[i] if i < len(descriptions) and descriptions[i] else ''
                    request.daily_entry_location = f'Product row {i + 1} / Delivery charges'
                    delivery_charges_value = float(delivery_charges[i]) if i < len(delivery_charges) and delivery_charges[i] else 0
                    
                    # Get payment for this product
                    payment_amount = 0
                    payment_type = 'cash'
                    if i < len(payment_amounts) and payment_amounts[i]:
                        try:
                            payment_amount = float(payment_amounts[i])
                        except (ValueError, TypeError):
                            payment_amount = 0
                    if i < len(payment_types) and payment_types[i]:
                        payment_type = payment_types[i]
                    
                    print(f"  Product {i+1}: {product.name}, Qty: {quantity}, Empty: {empty_returned}, Full Returned: {full_returned_val}, Payment: {payment_amount}")
                    
                    remarks = f"Entry on {selected_date}"
                    if personal_note:
                        remarks += f" | Personal: {personal_note}"
                    if invoice_no:
                        remarks += f" | Invoice: {invoice_no}"
                    if full_returned_val > 0:
                        remarks += f" | Full Returned: {full_returned_val}"
                    
                    # Create delivery with selected date
                    delivery = Delivery.objects.create(
                        customer=customer,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        empty_returned=empty_returned,
                        full_delivered=quantity,
                        full_returned=full_returned_val,
                        full_returned_value=full_returned_val_amount,
                        full_returned_paid=full_returned_paid_val,
                        delivery_date=selected_date,
                        remarks=remarks,
                        invoice_no=invoice_no,
                        description=description,
                        delivery_charges=delivery_charges_value,
                        damage_charges=damage_charges_value,
                        low_pressure_details=low_pressure_details,
                        payment_amount=payment_amount,
                        payment_type=payment_type,
                        cylinder_movement_type=cylinder_movement_type,
                        created_by=request.user
                    )
                    deliveries_created.append(delivery)
                    total_deliveries.append(delivery)
                                    
                    # Update stock (Full returned cylinders INCREASE stock, quantity given DECREASES stock)
                    net_stock_change = full_returned_val - int(quantity)
                    if net_stock_change != 0:
                        product.stock_quantity += int(stock_quantity_for_delivery(product, net_stock_change))
                        product.stock_weight_kg += product.unit_weight_kg * net_stock_change
                    if not is_sale_only_item:
                        product.empty_stock_quantity += empty_returned
                    product.save()
                    
                    # Create cylinder ledger entry (empty_in includes both empty_returned and full_returned)
                    total_returned = empty_returned + full_returned_val
                    if not is_sale_only_item and (quantity > 0 or total_returned > 0 or cylinder_movement_type):
                        CylinderLedger.objects.create(
                            customer=customer,
                            product=product,
                            full_out=quantity,
                            empty_in=total_returned,
                            delivery=delivery,
                            ownership_movement=cylinder_movement_type,
                            ownership_quantity=ownership_quantity if cylinder_movement_type else 0,
                            notes=remarks
                        )
                    
                    # A cash-paid return is a cash outflow; an unpaid return is already
                    # represented by the credit deducted from delivery_amount.
                    if full_returned_val_amount > 0 and full_returned_paid_val:
                        payment, created = create_payment_safely(
                            customer=customer,
                            amount=-full_returned_val_amount,
                            payment_type='cash',
                            notes=f"Cash paid for full cylinder return - {product.name} ({full_returned_val} Full Returned)",
                            payment_date=selected_date,
                            created_by=request.user,
                            delivery=delivery,
                        )
                        if created:
                            total_payments_made += 1
                    
                    # Process payment for this product if amount > 0
                    if payment_amount > 0:
                        payment_obj, created = create_payment_safely(
                            customer=customer,
                            amount=payment_amount,
                            payment_type=payment_type,
                            notes=f"Payment for {product.name} on {selected_date} (Invoice: {invoice_no if invoice_no else 'N/A'})",
                            created_by=request.user,
                            payment_date=selected_date,
                            invoice_no=invoice_no or '',
                            delivery=delivery,
                        )
                        if created:
                            total_payments_made += 1
                        print(f"  Payment created: PKR {payment_amount} ({payment_type})")
                payments_created_for_entry = total_payments_made - payments_before_entry
                if deliveries_created or payments_created_for_entry:
                    customer.last_activity_date = selected_date
                    customer.save(update_fields=['last_activity_date', 'updated_at'])
                    entries_created += 1
                    print(
                        f"  Entry #{entry_num} completed: "
                        f"{len(deliveries_created)} deliveries, {payments_created_for_entry} payments"
                    )
                else:
                    request.daily_entry_location = 'Product / payment details'
                    raise ValueError(
                        'This entry has customer details but no valid product or payment to save.'
                    )
            
            if total_deliveries or total_payments_made:
                msg = f'✅ {len(total_deliveries)} deliveries and {total_payments_made} payments saved for {selected_date}!'
                if total_payments_made > 0:
                    msg += f' 💳 {total_payments_made} payments recorded!'
                if selected_date != timezone.now().astimezone(PKT).date():
                    msg += f' 📅 (Backdated entry for {selected_date})'
                messages.success(request, msg)
                print(
                    f"\n{len(total_deliveries)} deliveries and "
                    f"{total_payments_made} payments saved for {selected_date}!"
                )
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True, 'message': msg})
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    if not entry_numbers_with_data:
                        return JsonResponse({
                            'success': False,
                            'entry_number': None,
                            'location': 'No populated entries',
                            'error': 'There are no entries with data to save.',
                        }, status=400)
                    entry_number = next(
                        iter(entry_numbers_with_data),
                        None,
                    )
                    if entry_number is None:
                        entry_number = next(
                            (number for number in range(1, 201) if f'customer_type_{number}' in request.POST),
                            1,
                        )
                    return JsonResponse({
                        'success': False,
                        'entry_number': entry_number,
                        'location': 'Product / payment details',
                        'error': 'No valid product, invoice, or payment was provided for this entry.',
                    }, status=400)
                messages.warning(request, 'No valid entries found. Please fill a product entry or an invoice and payment.')
                print("\nNo valid entries found!")
            
            # Redirect back with the date parameter
            return redirect(f'{request.path}?date={selected_date.strftime("%Y-%m-%d")}')