from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.generic import TemplateView
from django.views import View
from django.http import JsonResponse
from django.db import transaction
from django.urls import reverse
from django.db.models import Sum
from django.utils import timezone
from urllib.parse import urlencode
from datetime import datetime, timedelta
from apps.customers.models import Customer
from apps.deliveries.models import Delivery, DeliveryInvoiceSequence
from apps.payments.models import Payment
from apps.products.models import Product
from apps.cylinders.models import CylinderLedger
from apps.deliveries.views import stock_quantity_for_delivery
from apps.fbr.models import FBRCustomerSetting, FBRInvoice
from apps.fbr.invoice_numbers import get_fbr_category as get_shared_fbr_category
import re
import json


class ManageFBRInvoiceNumbersView(LoginRequiredMixin, View):
    """Reset or sequentially assign invoice numbers for rows in the current report."""

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        customer_ids = list(dict.fromkeys(request.POST.getlist('customer_id')))
        submitted_groups = request.POST.getlist('delivery_group')
        delivery_groups = []
        if submitted_groups:
            try:
                delivery_groups = [
                    [delivery_id.strip() for delivery_id in group.split(',') if delivery_id.strip()]
                    for group in submitted_groups
                ]
            except AttributeError:
                delivery_groups = []
        else:
            delivery_groups = [[delivery_id] for delivery_id in request.POST.getlist('delivery_id')]
        delivery_ids = [
            delivery_id
            for group in delivery_groups
            for delivery_id in group
        ]
        date_from = request.POST.get('date_from', '')
        date_to = request.POST.get('date_to', '')
        gst_rate = request.POST.get('gst_rate', '')
        divisor_value = request.POST.get('divisor_value', '')
        redirect_params = [('customer_id', customer_id) for customer_id in customer_ids]
        if date_from:
            redirect_params.append(('date_from', date_from))
        if date_to:
            redirect_params.append(('date_to', date_to))
        if gst_rate:
            redirect_params.append(('gst_rate', gst_rate))
        if divisor_value:
            redirect_params.append(('divisor_value', divisor_value))

        def finish_with_message(level, message):
            messages.add_message(request, level, message)
            query = urlencode(redirect_params)
            return redirect(f'{reverse("fbr:invoices")}?{query}' if query else reverse('fbr:invoices'))

        if action not in {'reset', 'assign'}:
            return finish_with_message(messages.ERROR, 'Invalid invoice-number action.')
        if not customer_ids or not delivery_ids:
            return finish_with_message(messages.ERROR, 'Select customers and ensure the report contains invoice rows.')

        valid_customer_ids = set(
            str(customer_id)
            for customer_id in Customer.objects.filter(pk__in=customer_ids).values_list('pk', flat=True)
        )
        if len(valid_customer_ids) != len(customer_ids):
            return finish_with_message(messages.ERROR, 'The selected customer list is invalid. Refresh the report and try again.')

        deliveries = Delivery.objects.filter(customer_id__in=valid_customer_ids)
        try:
            if date_from:
                deliveries = deliveries.filter(delivery_date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
            if date_to:
                deliveries = deliveries.filter(delivery_date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
        except ValueError:
            return finish_with_message(messages.ERROR, 'The report date range is invalid. Refresh the report and try again.')

        deliveries = list(deliveries.select_related('customer', 'product'))
        report_view = FBRInvoicesView()
        eligible_deliveries = {
            str(delivery.pk): delivery
            for delivery in deliveries
            if report_view._get_fbr_category(delivery.product.name if delivery.product else 'Unknown')
            and get_fbr_base_amount(delivery) > Decimal('0')
        }
        if (
            not delivery_ids
            or len(delivery_ids) != len(set(delivery_ids))
            or not set(delivery_ids).issubset(eligible_deliveries)
        ):
            return finish_with_message(messages.ERROR, 'The report rows have changed. Refresh the page before updating invoice numbers.')

        report_groups = {}
        for delivery_id, delivery in eligible_deliveries.items():
            category = report_view._get_fbr_category(
                delivery.product.name if delivery.product else 'Unknown'
            )
            group_key = (
                str(delivery.customer_id),
                delivery.delivery_date,
                category,
            )
            report_groups.setdefault(group_key, set()).add(delivery_id)
        submitted_group_sets = [set(group) for group in delivery_groups]
        if (
            any(not group for group in submitted_group_sets)
            or len(submitted_group_sets) != len(set(frozenset(group) for group in submitted_group_sets))
            or set(frozenset(group) for group in submitted_group_sets)
            != {
                frozenset(group)
                for group in report_groups.values()
                if group.issubset(set(delivery_ids))
            }
        ):
            return finish_with_message(messages.ERROR, 'The report rows have changed. Refresh the page before updating invoice numbers.')

        start_number = None
        if action == 'assign':
            try:
                start_number = int(request.POST.get('start_number', ''))
                if start_number < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return finish_with_message(messages.ERROR, 'Enter a positive whole number to start invoice numbering.')

            assigned_numbers = [str(start_number + offset) for offset in range(len(delivery_groups))]
            if any(len(invoice_number) > 50 for invoice_number in assigned_numbers):
                return finish_with_message(messages.ERROR, 'The sequential invoice numbers exceed the allowed length.')

        with transaction.atomic():
            sequence, _ = DeliveryInvoiceSequence.objects.select_for_update().get_or_create(pk=1)
            if action == 'assign':
                conflicts = Delivery.objects.filter(
                    fbr_invoice_no__in=assigned_numbers
                ).exclude(pk__in=delivery_ids)
                if conflicts.exists():
                    return finish_with_message(messages.ERROR, 'One or more invoice numbers in that sequence are already assigned outside this report.')
            Delivery.objects.filter(pk__in=delivery_ids).update(fbr_invoice_no=None)
            if action == 'assign':
                for delivery_group, invoice_number in zip(delivery_groups, assigned_numbers):
                    Delivery.objects.filter(pk__in=delivery_group).update(fbr_invoice_no=invoice_number)
                sequence.next_number = max(sequence.next_number, start_number + len(delivery_groups))
                sequence.save(update_fields=['next_number'])

        if action == 'reset':
            return finish_with_message(messages.SUCCESS, f'Invoice numbers were cleared for {len(delivery_groups)} displayed rows.')
        return finish_with_message(messages.SUCCESS, f'Sequential invoice numbers were assigned to {len(delivery_groups)} displayed rows.')


def _truncate_to_two_place_decimal(value):
    """Round a Decimal-like value to exactly the two visible digits after the point using standard financial rounding.

    This prevents hidden precision while ensuring arithmetic matches expected totals.
    """
    try:
        return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (TypeError, ValueError, ArithmeticError):
        return Decimal('0')


def get_fbr_base_amount(delivery):
    """Return the taxable product amount for FBR without delivery charges and damage charges.

    This ensures FBR invoice total values match the delivery total in the customer ledger.
    """
    delivery_amount = _truncate_to_two_place_decimal(delivery.delivery_amount or 0)
    delivery_charges = _truncate_to_two_place_decimal(delivery.delivery_charges or 0)
    damage_charges = _truncate_to_two_place_decimal(delivery.damage_charges or 0)
    
    product_base = delivery_amount - delivery_charges - damage_charges
    if product_base > Decimal('0'):
        return product_base
        
    quantity = _truncate_to_two_place_decimal(delivery.quantity or 0)
    unit_price = _truncate_to_two_place_decimal(delivery.unit_price or 0)
    return _truncate_to_two_place_decimal(quantity * unit_price)


class SaveFBRSelectedCustomersView(LoginRequiredMixin, View):
    """Persist the current FBR customer selection for other reports."""

    def post(self, request, *args, **kwargs):
        customer_ids = [
            str(customer_id) for customer_id in request.POST.getlist('customer_id')
            if customer_id
        ]
        valid_customer_ids = set(
            str(customer_id) for customer_id in Customer.objects.filter(
                pk__in=customer_ids
            ).values_list('pk', flat=True)
        )
        request.session['fbr_selected_customer_ids'] = [
            customer_id for customer_id in customer_ids
            if customer_id in valid_customer_ids
        ]
        request.session.modified = True
        return JsonResponse({'success': True, 'count': len(request.session['fbr_selected_customer_ids'])})

class DeleteFBRDeliveryView(LoginRequiredMixin, View):
    """Delete a delivery selected from the FBR ledger and restore source stock."""

    def post(self, request, pk):
        with transaction.atomic():
            delivery = get_object_or_404(
                Delivery.objects.select_related('product'),
                pk=pk,
            )
            product = delivery.product
            net_stock_change = delivery.full_returned - delivery.quantity
            product.stock_quantity -= int(stock_quantity_for_delivery(product, net_stock_change))
            if not product.is_quantity_only:
                product.empty_stock_quantity -= delivery.empty_returned
            product.stock_weight_kg -= product.unit_weight_kg * net_stock_change
            product.save()
            CylinderLedger.objects.filter(delivery=delivery).delete()
            customer_id = delivery.customer_id
            delivery.delete()

        return redirect(f'{reverse("fbr:ledger")}?customer_id={customer_id}')

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

class FBRInvoicesView(LoginRequiredMixin, TemplateView):
    """Display FBR invoices for multiple selected customers."""
    template_name = 'fbr/invoices.html'

    def _extract_kg_from_product(self, product_name):
        """Extract KG value from product name like 'CO2 25KG' → 25"""
        if not product_name:
            return 1
        match = re.search(r'(\d+)\s*KG', product_name.upper())
        if match:
            return int(match.group(1))
        return 1

    def _get_fbr_category(self, product_name):
        """Get FBR category for product grouping: CO2, LPG, OXYGEN LIQUID only."""
        return get_shared_fbr_category(product_name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        all_customers = Customer.objects.all().order_by('name')
        
        clear_customer_selection = self.request.GET.get('clear_customer_selection') == '1'
        if clear_customer_selection:
            self.request.session.pop('fbr_selected_customer_ids', None)
            selected_customer_ids = []
        elif 'customer_id' in self.request.GET:
            selected_customer_ids = self.request.GET.getlist('customer_id', [])
            self.request.session['fbr_selected_customer_ids'] = selected_customer_ids
        else:
            selected_customer_ids = self.request.session.get('fbr_selected_customer_ids', [])
        
        context['customers'] = all_customers
        context['selected_customer_ids'] = selected_customer_ids
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        
        context['selected_customers'] = []
        context['customer_fbr_settings'] = {}
        context['customer_fbr_settings_json'] = '{}'
        context['invoice_rows'] = []
        context['total_rows'] = 0
        
        # Get GST rate
        try:
            gst_rate = Decimal(str(self.request.GET.get('gst_rate', '18.00')))
            if gst_rate < 0 or gst_rate > 100:
                raise ValueError
        except (TypeError, ValueError, ArithmeticError):
            gst_rate = Decimal('18.00')
        context['gst_rate'] = gst_rate
        
        # Get divisor value for OXYGEN LIQUID
        try:
            divisor_value = Decimal(str(self.request.GET.get('divisor_value', '115')))
            if divisor_value <= 0:
                raise ValueError
        except (TypeError, ValueError, ArithmeticError):
            divisor_value = Decimal('115')
        context['divisor_value'] = divisor_value
        
        if not selected_customer_ids:
            return context

        selected_customers = list(Customer.objects.filter(pk__in=selected_customer_ids).order_by('name'))
        context['selected_customers'] = selected_customers
        
        # Load FBR settings for each customer (STN, NTN only)
        customer_fbr_settings = {}
        for customer in selected_customers:
            try:
                fbr_setting = FBRCustomerSetting.objects.get(customer=customer)
                customer_fbr_settings[str(customer.pk)] = {
                    'stn': fbr_setting.stn or '',
                    'ntn': fbr_setting.ntn or '',
                }
            except FBRCustomerSetting.DoesNotExist:
                customer_fbr_settings[str(customer.pk)] = {
                    'stn': '',
                    'ntn': '',
                }
        
        context['customer_fbr_settings'] = customer_fbr_settings
        context['customer_fbr_settings_json'] = json.dumps(customer_fbr_settings)

        invoice_rows = []
        sr_no = 1
        date_from = context['date_from']
        date_to = context['date_to']
        
        for customer in selected_customers:
            deliveries = Delivery.objects.filter(customer=customer)
            
            if date_from:
                try:
                    deliveries = deliveries.filter(delivery_date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
                except ValueError:
                    pass
            
            if date_to:
                try:
                    deliveries = deliveries.filter(delivery_date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
                except ValueError:
                    pass

            deliveries = deliveries.select_related('customer', 'product').order_by('delivery_date', 'created_at')
            
            category_data = {}
            
            fbr_settings = customer_fbr_settings.get(str(customer.pk), {})

            for delivery in deliveries:
                product_name = delivery.product.name if delivery.product else 'Unknown'
                category = self._get_fbr_category(product_name)

                # Skip products that don't match CO2, LPG, or OXYGEN LIQUID
                if category is None:
                    continue

                kg_per_cylinder = self._extract_kg_from_product(product_name)

                base_amount = get_fbr_base_amount(delivery)

                # Use dynamic divisor value for OXYGEN LIQUID
                if category == 'OXYGEN LIQUID':
                    # For OXYGEN LIQUID, calculate only from the two visible decimals
                    gst_multiplier = Decimal('1') + (gst_rate / Decimal('100'))
                    ex_value = _truncate_to_two_place_decimal(base_amount / gst_multiplier)
                    total_kg = _truncate_to_two_place_decimal(ex_value / divisor_value)
                    unit = 'M3'
                else:
                    total_kg = _truncate_to_two_place_decimal(
                        _truncate_to_two_place_decimal(delivery.quantity) * Decimal(str(kg_per_cylinder or 1))
                    )
                    unit = 'KG'

                category_data[delivery.pk] = {
                    'date': delivery.delivery_date,
                    'category': category,
                    'customer_id': customer.pk,
                    'customer_name': customer.name,
                    'invoice_no': delivery.fbr_invoice_no or '',
                    'delivery_id': str(delivery.pk),
                    'created_at': delivery.created_at,
                    'total_kg': total_kg,
                    'unit': unit,
                    'total_value': base_amount,
                    'delivery': delivery,
                }
            
            for agg_key in sorted(category_data.keys()):
                data = category_data[agg_key]
                
                # Get the total value
                total_value = data['total_value']
                total_kg = data['total_kg']
                
                # Skip zero-value entries where total value or quantity is zero
                if total_value <= Decimal('0') and total_kg <= Decimal('0'):
                    continue
                if total_value <= Decimal('0'):
                    continue
                
                # Keep the ledger total authoritative and derive the tax-exclusive amount from it.
                gst_multiplier = Decimal('1') + (gst_rate / Decimal('100'))
                ex_value = _truncate_to_two_place_decimal(total_value / gst_multiplier)

                # Calculate RATE = EX Value / Quantity
                rate = _truncate_to_two_place_decimal((ex_value / total_kg) if total_kg > 0 else Decimal('0'))
                rate_display = rate

                # The displayed subtotal follows the displayed quantity and rate.
                subtotal = _truncate_to_two_place_decimal(rate_display * total_kg)

                # GST is the residual so the invoice total always matches the ledger total.
                gst_amount = _truncate_to_two_place_decimal(total_value - subtotal)
                total_value_final = total_value

                row_key = str(data['delivery'].pk)

                row = {
                    'sr_no': sr_no,
                    'customer_id': customer.pk,
                    'row_key': row_key,
                    'delivery_id': str(data['delivery'].pk),
                    'delivery_ids': [str(data['delivery'].pk)],
                    'date': data['date'],
                    'created_at': data['created_at'],
                    'invoice_no': data['invoice_no'],
                    'ntn': fbr_settings.get('ntn') or customer.ntn or '-',
                    'stn': fbr_settings.get('stn') or customer.stn or '-',
                    'customer_name': data['customer_name'],
                    'item_description': data['category'],
                    'quantity': total_kg,
                    'unit': data['unit'],
                    'rate': rate_display,
                    'ex_value': subtotal,  # SUBTOTAL = QUANTITY × RATE (floor)
                    'gst_amount': gst_amount,  # GST = SUBTOTAL × GST%
                    'total_value': total_value_final,  # TOTAL = SUBTOTAL + GST
                }
                invoice_rows.append(row)
                sr_no += 1
        
        grouped_invoice_rows = {}
        for row in invoice_rows:
            grouping_key = (
                row['customer_id'],
                row['date'],
                row['item_description'],
            )
            grouped_row = grouped_invoice_rows.get(grouping_key)
            if grouped_row is None:
                grouped_row = row.copy()
                grouped_row['delivery_ids'] = []
                grouped_row['total_value'] = Decimal('0')
                grouped_row['_quantity_total'] = Decimal('0')
                grouped_invoice_rows[grouping_key] = grouped_row
            grouped_row['delivery_ids'].append(row['delivery_id'])
            grouped_row['total_value'] += row['total_value']
            grouped_row['_quantity_total'] += row['quantity']
            if row['created_at'] < grouped_row['created_at']:
                grouped_row['created_at'] = row['created_at']

        gst_multiplier = Decimal('1') + (Decimal(str(gst_rate)) / Decimal('100'))
        for row in grouped_invoice_rows.values():
            ex_value_before_rate = _truncate_to_two_place_decimal(row['total_value'] / gst_multiplier)
            if row['item_description'] == 'OXYGEN LIQUID':
                row['quantity'] = _truncate_to_two_place_decimal(
                    ex_value_before_rate / Decimal(str(divisor_value))
                )
            else:
                row['quantity'] = row.pop('_quantity_total')
            row.pop('_quantity_total', None)
            row['rate'] = _truncate_to_two_place_decimal(
                ex_value_before_rate / row['quantity'] if row['quantity'] > 0 else Decimal('0')
            )
            row['ex_value'] = _truncate_to_two_place_decimal(row['rate'] * row['quantity'])
            row['gst_amount'] = _truncate_to_two_place_decimal(row['total_value'] - row['ex_value'])
            row['delivery_id'] = row['delivery_ids'][0]
            row['row_key'] = row['delivery_id']

        invoice_rows = list(grouped_invoice_rows.values())

        # Sort by transaction date, then invoice number within that date.
        def get_invoice_number(row):
            try:
                match = re.search(r'\d+', str(row['invoice_no'] or ''))
                return int(match.group()) if match else 999999
            except (ValueError, TypeError):
                return 999999
        
        invoice_rows.sort(key=lambda row: (row['date'], get_invoice_number(row), row['item_description']))

        # Re-assign SR NO after sorting
        for idx, row in enumerate(invoice_rows, start=1):
            row['sr_no'] = idx
        
        context['invoice_rows'] = invoice_rows
        context['total_rows'] = len(invoice_rows)
        context['total_gst'] = sum(
            (row['gst_amount'] for row in invoice_rows),
            Decimal('0'),
        )
        
        return context

class FBRLedgerView(LoginRequiredMixin, TemplateView):
    """FBR Ledger - Shows all customer transactions in FBR format"""
    template_name = 'fbr/ledger.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        customer_id = self.request.GET.get('customer_id')
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        gst_rate = self.request.GET.get('gst_rate', '18.00')
        deduction_percent = self.request.GET.get('deduction_percent', '0')
        
        try:
            deduction_percent_value = float(deduction_percent)
        except (TypeError, ValueError):
            deduction_percent_value = 0.0
        
        context['customers'] = Customer.objects.all().order_by('name')
        context['date_from'] = date_from
        context['date_to'] = date_to
        context['gst_rate'] = float(gst_rate) if gst_rate else 18.00
        context['deduction_percent'] = deduction_percent_value
        context['today'] = timezone.now().date()
        context['week_ago'] = context['today'] - timedelta(days=7)
        context['month_ago'] = context['today'] - timedelta(days=30)

        def money(value):
            return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        if customer_id:
            customer = get_object_or_404(Customer, pk=customer_id)
            context['selected_customer'] = customer
            
            # Load FBR settings for this customer (STN, NTN only)
            context['customer_fbr_settings'] = {}
            try:
                fbr_setting = FBRCustomerSetting.objects.get(customer=customer)
                context['customer_fbr_settings'] = {
                    str(customer.pk): {
                        'stn': fbr_setting.stn or '',
                        'ntn': fbr_setting.ntn or '',
                    }
                }
            except FBRCustomerSetting.DoesNotExist:
                context['customer_fbr_settings'] = {
                    str(customer.pk): {
                        'stn': '',
                        'ntn': '',
                    }
                }
            
            deliveries = Delivery.objects.filter(customer=customer)
            
            if date_from:
                try:
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                    deliveries = deliveries.filter(delivery_date__gte=date_from_obj)
                except ValueError:
                    pass
            
            if date_to:
                try:
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                    deliveries = deliveries.filter(delivery_date__lte=date_to_obj)
                except ValueError:
                    pass
            
            deliveries = deliveries.order_by('delivery_date', 'created_at')
            
            payments = Payment.objects.filter(customer=customer)
            if date_from:
                payments = payments.filter(payment_date__gte=date_from_obj)
            if date_to:
                payments = payments.filter(payment_date__lte=date_to_obj)
            
            gst_rate = context['gst_rate']
            gst_decimal = Decimal(str(gst_rate))
            gst_multiplier = Decimal('1') + (gst_decimal / Decimal('100'))


            # ============================================================
            # HELPER FUNCTIONS
            # ============================================================
            def extract_kg_from_product(product_name):
                """Extract KG value from product name like 'CO2 25KG' → 25"""
                if not product_name:
                    return 1
                match = re.search(r'(\d+)\s*KG', product_name.upper())
                if match:
                    return int(match.group(1))
                return 1
            
            def get_fbr_category(product_name):
                return get_shared_fbr_category(product_name)
            
            # ============================================================
            # AGGREGATE DELIVERIES BY PRODUCT NAME
            # ============================================================
            product_data = {}  # key: product_name → aggregated data
            
            for delivery in deliveries:
                product_name = delivery.product.name if delivery.product else 'Unknown'
                category = get_fbr_category(product_name)
                
                # Skip products that don't match CO2, LPG, or OXYGEN LIQUID
                if category is None:
                    continue
                
                kg_per_cylinder = extract_kg_from_product(product_name)
                
                # Calculate base amount first using the same two-place truncation
                # that the FBR page is meant to show.
                total_amount_without_charges = get_fbr_base_amount(delivery)

                # EX.VALUE = Total Amount ÷ 1.18, then trim to the two visible decimals
                ex_value = _truncate_to_two_place_decimal(total_amount_without_charges / gst_multiplier)

                # QUANTITY CALCULATION - SPECIAL RULE FOR OXYGEN LIQUID
                if category == 'OXYGEN LIQUID':
                    # Quantity = EX.VALUE ÷ divisor and keep only the displayed two decimals
                    total_kg = _truncate_to_two_place_decimal(ex_value / Decimal('115'))
                    unit = 'M3'
                else:
                    # Quantity = Cylinders × KG per cylinder from visible two decimals only
                    total_kg = _truncate_to_two_place_decimal(
                        _truncate_to_two_place_decimal(delivery.quantity) * Decimal(str(kg_per_cylinder or 1))
                    )
                    unit = 'KG'

                # Total Amount includes GST (Total Value = Total Amount)
                total_amount_with_gst = _truncate_to_two_place_decimal(total_amount_without_charges)
                
                if product_name not in product_data:
                    product_data[product_name] = {
                        'product_name': product_name,
                        'category': category,
                        'total_kg': Decimal('0'),
                        'unit': unit,
                        'total_cylinders': 0,
                        'total_ex_value': Decimal('0'),
                        'total_amount_with_gst': Decimal('0'),
                        'invoice_no': delivery.fbr_invoice_no or '',
                        'first_date': delivery.delivery_date,
                        'source_deliveries': [],
                    }
                
                # Aggregate totals for this product
                product_data[product_name]['total_kg'] += total_kg
                product_data[product_name]['total_cylinders'] += delivery.quantity
                product_data[product_name]['total_ex_value'] += ex_value
                product_data[product_name]['total_amount_with_gst'] += total_amount_with_gst
                product_data[product_name]['source_deliveries'].append(delivery)
            
            # Calculate total payments
            total_delivery_payments = sum((Decimal(str(d.payment_amount or 0)) for d in deliveries), Decimal('0'))
            total_standalone_payments = sum((Decimal(str(p.amount or 0)) for p in payments), Decimal('0'))
            total_payments_amount = total_delivery_payments + total_standalone_payments

            # Build source rows first, then consolidate matching invoice lines.
            ledger_rows = []
            for product_name, data in product_data.items():
                for delivery in data['source_deliveries']:
                    total_amount_with_gst = _truncate_to_two_place_decimal(get_fbr_base_amount(delivery))
                    total_ex_value = _truncate_to_two_place_decimal(total_amount_with_gst / gst_multiplier)

                    if data['category'] == 'OXYGEN LIQUID':
                        total_kg = _truncate_to_two_place_decimal(total_ex_value / Decimal('115'))
                    else:
                        total_kg = _truncate_to_two_place_decimal(
                            _truncate_to_two_place_decimal(delivery.quantity)
                            * Decimal(str(extract_kg_from_product(product_name) or 1))
                        )

                    if total_amount_with_gst <= Decimal('0'):
                        continue

                    gst_amount = _truncate_to_two_place_decimal(total_ex_value * (gst_decimal / Decimal('100')))
                    total_value = _truncate_to_two_place_decimal(total_ex_value + gst_amount)
                    if abs(total_value - total_amount_with_gst) <= Decimal('0.05'):
                        total_value = total_amount_with_gst
                        gst_amount = _truncate_to_two_place_decimal(total_value - total_ex_value)

                    deduction_percent_decimal = Decimal(str(context['deduction_percent']))
                    value_after_deduction = _truncate_to_two_place_decimal(
                        total_value * (Decimal('1') - (deduction_percent_decimal / Decimal('100')))
                        if context['deduction_percent'] else total_value
                    )
                    rate = _truncate_to_two_place_decimal(
                        (total_ex_value / Decimal(str(total_kg))) if total_kg > 0 else Decimal('0')
                    )

                    ledger_rows.append({
                        'date': delivery.delivery_date.strftime('%d/%m/%Y') if delivery.delivery_date else '',
                        'sort_date': delivery.delivery_date,
                        'sort_created_at': delivery.created_at,
                        'row_key': str(delivery.pk),
                        'invoice_no': delivery.fbr_invoice_no or '',
                        'customer_name': customer.name,
                        'item_description': product_name,
                        'category': data['category'],
                        'kg': total_kg,
                        'cylinders': delivery.quantity,
                        'unit': data['unit'],
                        'rate': rate,
                        'ex_value': total_ex_value,
                        'gst_amount': gst_amount,
                        'gst_rate': gst_rate,
                        'delivery_charges': Decimal('0'),
                        'total_value': total_value,
                        'value_after_deduction': value_after_deduction,
                        'deduction_amount': total_value - value_after_deduction,
                        'payment_received': Decimal(str(delivery.payment_amount or 0)),
                        'balance': Decimal('0'),
                        'is_payment': False,
                        'is_quantity_only': bool(delivery.product and delivery.product.is_quantity_only),
                        'source_delivery': delivery,
                        'source_deliveries': [delivery],
                    })

            grouped_ledger_rows = {}
            for row in ledger_rows:
                grouping_key = (
                    row['sort_date'],
                    row['category'],
                )
                grouped_row = grouped_ledger_rows.get(grouping_key)
                if grouped_row is None:
                    grouped_row = row.copy()
                    grouped_row['source_deliveries'] = []
                    grouped_row['total_value'] = Decimal('0')
                    grouped_row['payment_received'] = Decimal('0')
                    grouped_row['cylinders'] = Decimal('0')
                    grouped_row['_quantity_total'] = Decimal('0')
                    grouped_ledger_rows[grouping_key] = grouped_row
                grouped_row['source_deliveries'].extend(row['source_deliveries'])
                grouped_row['total_value'] += row['total_value']
                grouped_row['payment_received'] += row['payment_received']
                grouped_row['cylinders'] += row['cylinders']
                grouped_row['_quantity_total'] += row['kg']
                if row['sort_created_at'] < grouped_row['sort_created_at']:
                    grouped_row['sort_created_at'] = row['sort_created_at']

            ledger_rows = list(grouped_ledger_rows.values())
            for row in ledger_rows:
                ex_value_before_rate = _truncate_to_two_place_decimal(
                    row['total_value'] / gst_multiplier
                )
                if row['category'] == 'OXYGEN LIQUID':
                    row['kg'] = _truncate_to_two_place_decimal(ex_value_before_rate / Decimal('115'))
                else:
                    row['kg'] = row.pop('_quantity_total')
                row.pop('_quantity_total', None)
                row['item_description'] = row['category']
                row['ex_value'] = ex_value_before_rate
                row['gst_amount'] = _truncate_to_two_place_decimal(
                    row['total_value'] - row['ex_value']
                )
                row['rate'] = _truncate_to_two_place_decimal(
                    row['ex_value'] / row['kg'] if row['kg'] > 0 else Decimal('0')
                )
                row['deduction_amount'] = _truncate_to_two_place_decimal(
                    row['total_value'] * (Decimal(str(context['deduction_percent'])) / Decimal('100'))
                )
                row['value_after_deduction'] = _truncate_to_two_place_decimal(
                    row['total_value'] - row['deduction_amount']
                )
                row['source_delivery'] = row['source_deliveries'][0]
                row['row_key'] = ','.join(str(delivery.pk) for delivery in row['source_deliveries'])

            ledger_rows.sort(
                key=lambda row: (
                    row['sort_date'],
                    row['sort_created_at'],
                    row['category'],
                    row['item_description'],
                )
            )
            running_balance = Decimal('0')
            running_payments = Decimal('0')
            for row in ledger_rows:
                running_balance += row['total_value']
                running_payments += row['payment_received']
                row['balance'] = running_balance - running_payments

            if ledger_rows:
                # Keep payments not recorded on a delivery visible without
                # repeating the customer's total payment on every row.
                payment_adjustment = total_payments_amount - running_payments
                ledger_rows[-1]['payment_received'] += payment_adjustment
                ledger_rows[-1]['balance'] -= payment_adjustment
            
            fbr_entries = ledger_rows
            
            # ============================================================
            # BUILD PRODUCT SUMMARY
            # ============================================================
            product_summary = {}
            for product_name, data in product_data.items():
                category = data['category']
                if category not in product_summary:
                    product_summary[category] = {
                        'category': category,
                        'total_kg': 0,
                        'total_cylinders': 0,
                        'total_ex_value': 0,
                        'total_amount_with_gst': 0,
                        'products': [],
                    }
                
                product_summary[category]['total_kg'] += data['total_kg']
                product_summary[category]['total_cylinders'] += data['total_cylinders']
                product_summary[category]['total_ex_value'] += data['total_ex_value']
                product_summary[category]['total_amount_with_gst'] += data['total_amount_with_gst']
                product_summary[category]['products'].append({
                    'name': product_name,
                    'kg': data['total_kg'],
                    'cylinders': data['total_cylinders'],
                    'ex_value': data['total_ex_value'],
                    'amount_with_gst': data['total_amount_with_gst'],
                })
            
            product_summary_list = list(product_summary.values())
            product_summary_list.sort(key=lambda x: x['category'])
            
            context['fbr_entries'] = fbr_entries
            
            total_ex_value = sum((e['ex_value'] for e in fbr_entries), Decimal('0'))
            total_gst = sum((e['gst_amount'] for e in fbr_entries), Decimal('0'))
            total_value = sum((e['total_value'] for e in fbr_entries), Decimal('0'))
            deduction_amount = total_value * (Decimal(str(context['deduction_percent'])) / Decimal('100')) if context['deduction_percent'] else Decimal('0')
            total_value_before_deduction = total_value
            total_value_after_deduction = total_value - deduction_amount
            
            context['total_ex_value'] = total_ex_value
            context['total_gst'] = total_gst
            context['total_value'] = total_value
            context['deduction_amount'] = deduction_amount
            context['total_deduction'] = deduction_amount
            context['total_value_before_deduction'] = total_value_before_deduction
            context['total_value_after_deduction'] = total_value_after_deduction
            context['total_payments'] = total_payments_amount
            context['total_entries'] = len(fbr_entries)
            context['net_balance'] = running_balance - total_payments_amount
            context['product_summary'] = product_summary_list
        
        return context


class SaveFBRCustomerSettingView(LoginRequiredMixin, View):
    """Save FBR customer settings (STN, NTN) to database"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            customer_id = data.get('customer_id')
            stn = data.get('stn', '').strip()
            ntn = data.get('ntn', '').strip()
            
            customer = Customer.objects.get(pk=customer_id)
            
            fbr_setting, created = FBRCustomerSetting.objects.get_or_create(customer=customer)
            
            fbr_setting.stn = stn if stn else None
            fbr_setting.ntn = ntn if ntn else None
            fbr_setting.save()
            
            return JsonResponse({
                'status': 'success',
                'message': 'Settings saved successfully'
            })
        except Customer.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Customer not found'
            }, status=404)
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)
