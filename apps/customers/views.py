from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DetailView, TemplateView
from django.urls import reverse_lazy, reverse
from django.db.models import DateField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from django.http import JsonResponse  # <-- ADD THIS IMPORT
from django.core.paginator import Paginator
from uuid import UUID
from .models import Customer
from apps.products.models import Product
from apps.deliveries.models import Delivery
from apps.payments.models import Payment
from apps.cylinders.models import CylinderLedger
from apps.fbr.models import FBRInvoiceItem
from apps.notifications.models import Notification
import pytz
import json

# Pakistan Timezone
PKT = pytz.timezone('Asia/Karachi')


def _get_delivery_payment_map(deliveries, payments):
    payment_rows_by_delivery = {}
    for payment in payments:
        if payment.delivery_id:
            payment_rows_by_delivery.setdefault(payment.delivery_id, []).append(payment)

    delivery_payment_amounts = {}
    matched_payment_ids = set()
    for delivery in deliveries:
        linked_payments = payment_rows_by_delivery.get(delivery.pk, [])
        if linked_payments:
            delivery_payment_amounts[delivery.pk] = sum(float(payment.amount) for payment in linked_payments)
            matched_payment_ids.update(payment.pk for payment in linked_payments)

    return delivery_payment_amounts, matched_payment_ids


@login_required
def update_bf(request, pk):
    """Update B.F (Bring Forward) for a customer"""
    customer = get_object_or_404(Customer, pk=pk)
    
    if request.method == 'POST':
        bf_balance = request.POST.get('bf_balance', '0')
        bf_cylinders = request.POST.get('bf_cylinders', '{}')
        bf_description = request.POST.get('bf_description', '').strip()
        
        try:
            bf_balance = float(bf_balance)
        except (ValueError, TypeError):
            bf_balance = 0

        bf_date_text = request.POST.get('bf_date', '').strip()
        try:
            bf_date = datetime.strptime(bf_date_text, '%Y-%m-%d').date() if bf_date_text else timezone.localdate()
        except ValueError:
            messages.error(request, 'Invalid B.F date.')
            return redirect(f'{reverse("customers:ledger")}?customer_id={customer.pk}')
        
        if not bf_cylinders or bf_cylinders.strip() == '':
            bf_cylinders_dict = {}
        else:
            try:
                bf_cylinders_dict = json.loads(bf_cylinders)
                if not isinstance(bf_cylinders_dict, dict):
                    raise ValueError("Must be a dictionary")
                for key, value in bf_cylinders_dict.items():
                    bf_cylinders_dict[key] = int(value)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                messages.error(request, f'Invalid JSON format for cylinders: {str(e)}. Please use format: {{"Product Name": quantity}}')
                return redirect(f'{reverse("customers:ledger")}?customer_id={customer.pk}')
        
        customer.bf_balance = bf_balance
        customer.bf_date = bf_date
        customer.bf_cylinders = bf_cylinders_dict
        customer.bf_description = bf_description
        customer.save()
        
        messages.success(request, f'✅ B.F updated successfully for {customer.name}!')
        return redirect(f'{reverse("customers:ledger")}?customer_id={customer.pk}')
    
    return redirect(f'{reverse("customers:ledger")}?customer_id={customer.pk}')


@login_required  # <-- FIXED: Only one decorator
def bf_setup(request):
    """B.F (Bring Forward) Setup page - Add up to 100 customers with opening balance and cylinders"""
    
    if request.method == 'POST':
        with transaction.atomic():
            customers_created = 0
            total_bf_balance = 0
            customer_names = []
            errors = []
            
            for i in range(1, 101):
                name_key = f'customer_name_{i}'
                if name_key not in request.POST:
                    continue
                
                name = request.POST.get(name_key, '').strip()
                if not name:
                    continue
                
                mobile = request.POST.get(f'customer_mobile_{i}', '').strip()
                bf_balance = request.POST.get(f'bf_balance_{i}', '0')
                previous_balance = request.POST.get(f'previous_balance_{i}', '0')
                security_deposit = request.POST.get(f'security_deposit_{i}', '0')
                personal_cylinders = request.POST.get(f'personal_cylinders_{i}', '0')
                bf_description = request.POST.get(f'bf_description_{i}', '').strip()
                bf_date_text = request.POST.get(f'bf_date_{i}', '').strip()
                
                try:
                    bf_balance = float(bf_balance) if bf_balance else 0
                except (ValueError, TypeError):
                    bf_balance = 0
                
                try:
                    previous_balance = float(previous_balance) if previous_balance else 0
                except (ValueError, TypeError):
                    previous_balance = 0
                
                try:
                    security_deposit = float(security_deposit) if security_deposit else 0
                except (ValueError, TypeError):
                    security_deposit = 0
                
                try:
                    personal_cylinders = int(personal_cylinders) if personal_cylinders else 0
                except (ValueError, TypeError):
                    personal_cylinders = 0

                try:
                    bf_date = datetime.strptime(bf_date_text, '%Y-%m-%d').date() if bf_date_text else timezone.localdate()
                except ValueError:
                    bf_date = timezone.localdate()
                
                bf_cylinders = {}
                for j in range(1, 21):
                    product_key = f'bf_product_{j}_{i}'
                    qty_key = f'bf_quantity_{j}_{i}'
                    
                    product_name = request.POST.get(product_key, '').strip()
                    if not product_name:
                        continue
                    
                    quantity = request.POST.get(qty_key, '0')
                    try:
                        quantity = int(quantity) if quantity else 0
                    except (ValueError, TypeError):
                        quantity = 0
                    
                    if quantity != 0:
                        bf_cylinders[product_name] = quantity
                
                duplicate_filter = Q(name__iexact=name)
                if mobile:
                    duplicate_filter &= Q(mobile=mobile)
                else:
                    duplicate_filter &= (Q(mobile='') | Q(mobile__isnull=True))

                if Customer.objects.filter(duplicate_filter).exists():
                    errors.append(f'Customer "{name}" with mobile "{mobile}" is already registered (Row {i})')
                    continue
                
                customer = Customer.objects.create(
                    name=name,
                    mobile=mobile,
                    bf_balance=bf_balance,
                    bf_cylinders=bf_cylinders,
                    bf_description=bf_description,
                    previous_balance=previous_balance,
                    security_deposit=security_deposit,
                    personal_cylinders=personal_cylinders,
                    bf_date=bf_date,
                    last_activity_date=timezone.now().astimezone(PKT).date()
                )
                
                customers_created += 1
                total_bf_balance += bf_balance
                customer_names.append(name)
            
            if customers_created > 0:
                msg = f'✅ {customers_created} customers created successfully!\n'
                msg += f'💰 Total B.F Balance: PKR {total_bf_balance:,.2f}\n'
                if customer_names:
                    display_names = customer_names[:5]
                    if len(customer_names) > 5:
                        msg += f'📊 Customers: {", ".join(display_names)} and {len(customer_names) - 5} more...'
                    else:
                        msg += f'📊 Customers: {", ".join(display_names)}'
                messages.success(request, msg)
            else:
                if errors:
                    for error in errors[:3]:
                        messages.error(request, error)
                    if len(errors) > 3:
                        messages.error(request, f'And {len(errors) - 3} more errors...')
                else:
                    messages.warning(request, 'No valid customers found. Please fill at least one customer name.')
            
            # <-- FIXED: Added redirect after POST
            return redirect('customers:bf_setup')
    
    # GET request - show the form
    context = {
        'products': Product.objects.all().order_by('name'),
        'page_title': 'Bulk B.F Setup - 100 Customers',
    }
    return render(request, 'customers/bf_setup.html', context)


@login_required
def save_bf_customer_api(request):
    """API endpoint to save a single customer from B.F setup"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
            
        name = data.get('name', '').strip()
        if not name:
            return JsonResponse({'success': False, 'error': 'Customer name is required'}, status=400)
            
        mobile = data.get('mobile', '').strip()
        
        try:
            bf_balance = float(data.get('bf_balance', 0) or 0)
        except (ValueError, TypeError):
            bf_balance = 0
            
        try:
            previous_balance = float(data.get('previous_balance', 0) or 0)
        except (ValueError, TypeError):
            previous_balance = 0
            
        try:
            security_deposit = float(data.get('security_deposit', 0) or 0)
        except (ValueError, TypeError):
            security_deposit = 0
            
        try:
            personal_cylinders = int(data.get('personal_cylinders', 0) or 0)
        except (ValueError, TypeError):
            personal_cylinders = 0

        bf_description = data.get('bf_description', '').strip()
        bf_date_text = data.get('bf_date', '').strip()
        try:
            bf_date = datetime.strptime(bf_date_text, '%Y-%m-%d').date() if bf_date_text else timezone.localdate()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid B.F date'}, status=400)
        
        bf_cylinders = data.get('bf_cylinders', {})
        if isinstance(bf_cylinders, str):
            try:
                bf_cylinders = json.loads(bf_cylinders)
            except Exception:
                bf_cylinders = {}
                
        clean_cylinders = {}
        if isinstance(bf_cylinders, dict):
            for k, v in bf_cylinders.items():
                try:
                    qty = int(v)
                    if qty != 0:
                        clean_cylinders[k] = qty
                except (ValueError, TypeError):
                    pass
        
        duplicate_filter = Q(name__iexact=name)
        if mobile:
            duplicate_filter &= Q(mobile=mobile)
        else:
            duplicate_filter &= (Q(mobile='') | Q(mobile__isnull=True))

        if Customer.objects.filter(duplicate_filter).exists():
            return JsonResponse({
                'success': False,
                'error': f'Customer "{name}" with mobile "{mobile}" is already registered.'
            }, status=400)

        customer = Customer.objects.create(
            name=name,
            mobile=mobile,
            bf_balance=bf_balance,
            bf_cylinders=clean_cylinders,
            bf_description=bf_description,
            previous_balance=previous_balance,
            security_deposit=security_deposit,
            personal_cylinders=personal_cylinders,
            bf_date=bf_date,
            last_activity_date=timezone.now().astimezone(PKT).date()
        )
        action_text = "created"
            
        return JsonResponse({
            'success': True,
            'customer_id': str(customer.pk),
            'customer_name': customer.name,
            'message': f'✅ Customer "{customer.name}" {action_text} successfully with B.F!'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


class CustomerListView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/list.html'
    context_object_name = 'customers'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('deliveries__product')
        search = self.request.GET.get('search', '')
        customer_id = self.request.GET.get('customer_id', '')
        status_filter = self.request.GET.get('status', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')

        if customer_id:
            try:
                customer_id = UUID(customer_id)
            except (ValueError, AttributeError):
                customer_id = None
            if customer_id:
                queryset = queryset.filter(pk=customer_id)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(mobile__icontains=search) |
                Q(area__icontains=search) |
                Q(customer_code__icontains=search) |
                Q(is_walkin=True)
            )

        if status_filter in {'active', 'inactive', 'not_coming'}:
            today = timezone.localdate()
            queryset = queryset.annotate(
                effective_activity_date=Coalesce(
                    'last_activity_date',
                    'registration_date',
                    Value(today),
                    output_field=DateField(),
                )
            )
            if status_filter == 'active':
                queryset = queryset.filter(effective_activity_date__gt=today - timedelta(days=7))
            elif status_filter == 'inactive':
                queryset = queryset.filter(
                    effective_activity_date__lte=today - timedelta(days=7),
                    effective_activity_date__gt=today - timedelta(days=30),
                )
            elif status_filter == 'not_coming':
                queryset = queryset.filter(effective_activity_date__lte=today - timedelta(days=30))

        if date_from:
            try:
                queryset = queryset.filter(registration_date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
            except ValueError:
                pass

        if date_to:
            try:
                queryset = queryset.filter(registration_date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
            except ValueError:
                pass

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for customer in context['customers']:
            customer.cylinder_balance = customer.get_cylinder_balance()
        today = timezone.localdate()
        context['status_choices'] = [
            ('active', '🟢 Active'),
            ('inactive', '🟡 Inactive'),
            ('not_coming', '🔴 Not Coming')
        ]
        context['current_status'] = self.request.GET.get('status', '')
        context['search'] = self.request.GET.get('search', '')
        context['customer_options'] = Customer.objects.order_by('name', 'customer_code')
        context['selected_customer_id'] = self.request.GET.get('customer_id', '')
        context['date_from'] = self.request.GET.get('date_from', '')
        context['date_to'] = self.request.GET.get('date_to', '')
        context['today'] = today
        context['week_start'] = today - timedelta(days=today.weekday())
        context['month_start'] = today.replace(day=1)
        query = self.request.GET.copy()
        query.pop('page', None)
        query['print_mode'] = 'all'
        context['print_all_url'] = f"/customers/print/?{query.urlencode()}"
        return context


class CustomerPrintView(CustomerListView):
    template_name = 'customers/print.html'
    paginate_by = None

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset().order_by('name', 'customer_code')
        page_size = CustomerListView.paginate_by
        paginator = Paginator(queryset, page_size)
        mode = request.GET.get('print_mode', 'current')
        current_page = max(1, int(request.GET.get('page', 1) or 1))

        if mode == 'all':
            customers = list(queryset)
            printed_pages = f'All {paginator.num_pages} pages'
        elif mode == 'range':
            first_page = max(1, int(request.GET.get('page_from', 1) or 1))
            last_page = min(paginator.num_pages, int(request.GET.get('page_to', first_page) or first_page))
            if last_page < first_page:
                first_page, last_page = last_page, first_page
            customers = [customer for page_number in range(first_page, last_page + 1) for customer in paginator.page(page_number).object_list]
            printed_pages = f'Pages {first_page}-{last_page} of {paginator.num_pages}'
        else:
            current_page = min(current_page, max(1, paginator.num_pages))
            customers = list(paginator.page(current_page).object_list)
            printed_pages = f'Page {current_page} of {paginator.num_pages}'

        for customer in customers:
            customer.cylinder_balance = customer.get_cylinder_balance()

        return render(request, self.template_name, {
            'customers': customers,
            'printed_pages': printed_pages,
            'total_customers': len(customers),
            'page_count': paginator.num_pages,
            'current_page': current_page,
        })


class CustomerCreateView(LoginRequiredMixin, CreateView):
    model = Customer
    template_name = 'customers/form.html'
    fields = [
        'name', 'mobile', 'alternate_mobile', 'address', 'area', 'stn', 'ntn', 'notes',
        'previous_balance', 'security_deposit', 'personal_cylinders',
        'bf_balance', 'bf_cylinders', 'bf_date'
    ]
    success_url = reverse_lazy('customers:list')


class CustomerUpdateView(LoginRequiredMixin, UpdateView):
    model = Customer
    template_name = 'customers/form.html'
    fields = [
        'name', 'mobile', 'alternate_mobile', 'address', 'area', 'stn', 'ntn', 'notes',
        'previous_balance', 'security_deposit', 'personal_cylinders',
        'bf_balance', 'bf_cylinders', 'bf_date'
    ]
    success_url = reverse_lazy('customers:list')

    def form_valid(self, form):
        messages.success(self.request, 'Customer updated successfully.', extra_tags='customer-toast')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(
            self.request,
            'Customer update failed. Please correct the highlighted fields.',
            extra_tags='customer-toast',
        )
        return super().form_invalid(form)


class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = 'customers/profile.html'
    context_object_name = 'customer'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.object
        
        context['security_deposit'] = customer.security_deposit or 0
        context['personal_cylinders'] = customer.personal_cylinders or 0
        
        deliveries = Delivery.objects.filter(customer=customer).order_by('-created_at')
        payments = Payment.objects.filter(customer=customer).order_by('-created_at')
        cylinder_entries = CylinderLedger.objects.filter(customer=customer).order_by('-created_at')

        for delivery in deliveries:
            ownership_quantity = delivery.cylinderledger_set.filter(
                ownership_movement__in=('customer_received', 'customer_returned')
            ).values_list('ownership_quantity', flat=True).first() or 0
            delivery.display_empty_returned = (
                ownership_quantity
                if delivery.cylinder_movement_type in ('customer_received', 'customer_returned')
                else delivery.empty_returned or 0
            )
        
        context['deliveries'] = deliveries
        context['payments'] = payments
        context['cylinder_entries'] = cylinder_entries
        
        context['total_deliveries'] = deliveries.count()
        cylinder_deliveries = deliveries.filter(product__is_quantity_only=False)
        context['total_cylinders_taken'] = cylinder_deliveries.aggregate(total=Sum('quantity'))['total'] or 0
        context['total_cylinders_returned'] = sum(
            delivery.display_empty_returned for delivery in deliveries
            if not delivery.product.is_quantity_only
        )
        bf_cylinders = customer.bf_cylinders or {}
        bf_total = sum(int(quantity or 0) for quantity in bf_cylinders.values())
        cylinder_balance = customer.get_cylinder_balance()
        context['net_cylinders'] = sum(cylinder_balance.values())
        context['cylinders_with_customer'] = sum(
            quantity for quantity in cylinder_balance.values() if quantity > 0
        )
        context['cylinders_at_company'] = sum(
            -quantity for quantity in cylinder_balance.values() if quantity < 0
        )
        
        context['total_billed'] = customer.get_total_amount()
        context['total_paid'] = customer.get_total_payments()
        context['outstanding'] = customer.get_outstanding_balance()
        
        product_summary = {}
        for product_name, quantity in bf_cylinders.items():
            product_summary[product_name] = {
                'name': product_name,
                'opening': int(quantity or 0),
                'quantity': int(quantity or 0),
                'amount': 0,
                'returns': 0,
                'current': int(quantity or 0)
            }

        for delivery in deliveries:
            product_name = delivery.product.name
            if product_name not in product_summary:
                product_summary[product_name] = {
                    'name': product_name,
                    'opening': 0,
                    'quantity': 0,
                    'amount': 0,
                    'returns': 0,
                    'current': 0
                }
            product_summary[product_name]['quantity'] += delivery.quantity
            product_summary[product_name]['amount'] += float(delivery.delivery_amount)
            if not delivery.product.is_quantity_only:
                if delivery.cylinder_movement_type == 'customer_returned':
                    product_summary[product_name]['current'] += delivery.display_empty_returned
                    product_summary[product_name]['returns'] += delivery.display_empty_returned
                elif delivery.cylinder_movement_type == 'customer_received':
                    product_summary[product_name]['current'] -= delivery.display_empty_returned
                    product_summary[product_name]['returns'] += delivery.display_empty_returned
                else:
                    product_summary[product_name]['current'] += delivery.quantity
                    product_summary[product_name]['current'] -= delivery.display_empty_returned
                    product_summary[product_name]['current'] -= delivery.full_returned or 0
                    product_summary[product_name]['returns'] += delivery.display_empty_returned

        for product in product_summary.values():
            product['with_customer'] = max(product['current'], 0)
            product['at_company'] = max(-product['current'], 0)
        
        context['product_summary'] = product_summary.values()
        
        return context


class CustomerEntryView(LoginRequiredMixin, TemplateView):
    template_name = 'customers/entry.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['products'] = Product.objects.all().order_by('name')
        context['customers'] = Customer.objects.all().order_by('name')
        context['today'] = timezone.now().date()
        return context
    
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            customer_id = request.POST.get('customer_id')
            is_new_customer = request.POST.get('is_new_customer') == 'true'
            
            if customer_id and not is_new_customer:
                customer = get_object_or_404(Customer, pk=customer_id)
            else:
                name = request.POST.get('name')
                mobile = request.POST.get('mobile')
                alternate_mobile = request.POST.get('alternate_mobile', '')
                address = request.POST.get('address', '')
                area = request.POST.get('area', '')
                notes = request.POST.get('notes', '')
                
                if not name or not mobile:
                    messages.error(request, 'Name and Mobile are required for new customer.')
                    return redirect('customers:entry')
                
                customer = Customer.objects.create(
                    name=name,
                    mobile=mobile,
                    alternate_mobile=alternate_mobile,
                    address=address,
                    area=area,
                    notes=notes,
                    last_activity_date=timezone.now().date()
                )
                messages.success(request, f'New customer "{customer.name}" created successfully!')
            
            product_ids = request.POST.getlist('product_ids[]')
            quantities = request.POST.getlist('quantities[]')
            empty_returns = request.POST.getlist('empty_returns[]')
            product_prices = request.POST.getlist('product_prices[]')
            
            total_delivery_amount = 0
            deliveries_created = []
            
            for i in range(len(product_ids)):
                if product_ids[i] and quantities[i] and int(quantities[i]) > 0:
                    product = get_object_or_404(Product, pk=product_ids[i])
                    quantity = int(quantities[i])
                    empty_returned = int(empty_returns[i]) if empty_returns[i] else 0
                    unit_price = float(product_prices[i]) if product_prices[i] else float(product.unit_price)
                    
                    delivery = Delivery.objects.create(
                        customer=customer,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        empty_returned=empty_returned,
                        full_delivered=quantity,
                        remarks=f"Entry on {timezone.now().date()}",
                        created_by=request.user
                    )
                    deliveries_created.append(delivery)
                    total_delivery_amount += delivery.delivery_amount
                    
                    product.stock_quantity -= quantity
                    product.save()
                    
                    if quantity > 0 or empty_returned > 0:
                        CylinderLedger.objects.create(
                            customer=customer,
                            product=product,
                            full_out=quantity,
                            empty_in=empty_returned,
                            delivery=delivery,
                            notes=f"Entry on {timezone.now().date()}"
                        )
            
            payment_made = request.POST.get('payment_made') == 'on'
            payment_amount = request.POST.get('payment_amount', 0)
            payment_type = request.POST.get('payment_type', 'cash')
            
            if payment_made and float(payment_amount) > 0:
                Payment.objects.create(
                    customer=customer,
                    amount=payment_amount,
                    payment_type=payment_type,
                    notes=f"Payment on {timezone.now().date()}",
                    created_by=request.user
                )
                messages.success(request, f'Payment of PKR {payment_amount} recorded for {customer.name}!')
            
            if deliveries_created or payment_made:
                customer.last_activity_date = timezone.now().date()
                customer.save(update_fields=['last_activity_date', 'updated_at'])
            
            messages.success(request, f'Entry completed for {customer.name}! {len(deliveries_created)} deliveries added.')
            
            return redirect('customers:detail', pk=customer.pk)


class CustomerLedgerView(LoginRequiredMixin, TemplateView):
    template_name = 'customers/ledger.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        search = self.request.GET.get('search', '')
        customer_id = self.request.GET.get('customer_id', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        
        context['search'] = search
        context['date_from'] = date_from
        context['date_to'] = date_to
        
        context['today'] = timezone.now().date()
        context['week_ago'] = timezone.now().date() - timedelta(days=7)
        context['month_ago'] = timezone.now().date() - timedelta(days=30)
        
        from apps.products.models import Product
        context['all_products'] = Product.objects.all().order_by('name')
        
        # Get all customers including walk-in
        context['customers'] = Customer.objects.all().order_by('name')
        
        # Get walk-in customer ID for template
        walkin_customer = Customer.objects.filter(is_walkin=True).first()
        context['walkin_customer_id'] = str(walkin_customer.pk) if walkin_customer else ''
        
        # ============================================================
        # CHECK IF "WALK-IN" IS SELECTED
        # ============================================================
        is_walkin_view = (customer_id == 'walkin')
        
        # Get the actual walk-in customer object for the dropdown
        walkin_customer_obj = Customer.objects.filter(is_walkin=True).first()
        context['walkin_customer_obj'] = walkin_customer_obj
        
        if customer_id:
            # ============================================================
            # SPECIAL CASE: Show ALL walk-in customers combined
            # ============================================================
            if is_walkin_view:
                # Get all walk-in customers
                walkin_customers = Customer.objects.filter(is_walkin=True)
                walkin_ids = list(walkin_customers.values_list('pk', flat=True))
                
                if walkin_ids:
                    # Get all deliveries and payments for walk-in customers
                    deliveries = Delivery.objects.filter(customer_id__in=walkin_ids)
                    payments = Payment.objects.filter(customer_id__in=walkin_ids)
                    
                    # Apply date filters
                    if date_from:
                        try:
                            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                            deliveries = deliveries.filter(delivery_date__gte=date_from_obj)
                            payments = payments.filter(payment_date__gte=date_from_obj)
                        except ValueError:
                            pass
                    
                    if date_to:
                        try:
                            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                            deliveries = deliveries.filter(delivery_date__lte=date_to_obj)
                            payments = payments.filter(payment_date__lte=date_to_obj)
                        except ValueError:
                            pass
                    
                    # ============================================================
                    # CREATE VIRTUAL CUSTOMER OBJECT
                    # ============================================================
                    class VirtualCustomer:
                        def __init__(self):
                            self.pk = 'walkin'
                            self.name = '🚶 Walk-in Customers (All)'
                            self.customer_code = 'WALKIN-ALL'
                            self.mobile = 'Multiple'
                            self.bf_balance = 0
                            self.bf_cylinders = {}
                            self.previous_balance = 0
                            self.security_deposit = 0
                            self.personal_cylinders = 0
                            self.last_activity_date = None
                    
                    customer = VirtualCustomer()
                    context['selected_customer'] = customer
                    context['customer_name'] = '🚶 Walk-in Customers (All)'
                    context['is_walkin_view'] = True
                    
                    # ============================================================
                    # CALCULATE TOTALS
                    # ============================================================
                    total_quantity = deliveries.aggregate(total=Sum('quantity'))['total'] or 0
                    total_empty = deliveries.aggregate(total=Sum('empty_returned'))['total'] or 0
                    total_full_returned = deliveries.aggregate(total=Sum('full_returned'))['total'] or 0
                    net_cylinders = total_quantity - total_empty - total_full_returned
                    
                    context['net_cylinders'] = net_cylinders
                    context['personal_cylinders'] = 0
                    context['total_cylinders_at_shop'] = net_cylinders
                    
                    # ============================================================
                    # BUILD TRANSACTIONS FOR ALL WALK-IN CUSTOMERS
                    # ============================================================
                    transactions = []
                    
                    # Combined B.F for all walk-in customers
                    bf_balance = 0
                    bf_cylinders = {}
                    for wc in walkin_customers:
                        bf_balance += float(wc.bf_balance or 0) + float(wc.previous_balance or 0)
                        for k, v in (wc.bf_cylinders or {}).items():
                            bf_cylinders[k] = bf_cylinders.get(k, 0) + (v or 0)
                    
                    bf_cylinders_display = ' | '.join([f"{k}: {v}" for k, v in bf_cylinders.items() if v != 0])
                    if not bf_cylinders_display:
                        bf_cylinders_display = '0'
                    
                    bf_transaction = {
                        'type': 'bf',
                        'date': 'B.F',
                        'invoice_no': '—',
                        'item': 'Opening Balance (All Walk-in)',
                        'empty': 0,
                        'full': 0,
                        'rate': 0,
                        'total': 0,
                        'delivery_charges': 0,
                        'damage_charges': 0,
                        'payment_recv': 0,
                        'previous_balance': 0,
                        'balance': bf_balance,
                        'is_payment': False,
                        'is_bf': True,
                        'old_cylinders_display': '0',
                        'new_cylinders_display': bf_cylinders_display,
                        'old_cylinders_breakdown': {},
                        'new_cylinders_breakdown': bf_cylinders.copy(),
                            'description': ' | '.join(
                                wc.bf_description for wc in walkin_customers
                                if wc.bf_description
                            ),
                        'customer_name': 'All Walk-in Customers',
                    }
                    transactions.append(bf_transaction)
                    
                    delivery_payment_amounts, matched_payment_ids = _get_delivery_payment_map(
                        deliveries,
                        payments,
                    )

                    # Collect raw non-BF transactions
                    raw_non_bf_transactions = []
                    
                    for delivery in deliveries.order_by('delivery_date', 'created_at'):
                        payment_amount = delivery_payment_amounts.get(delivery.id, 0)
                        delivery_charges = float(delivery.delivery_charges or 0)
                        damage_charges = float(delivery.damage_charges or 0)
                        delivery_amount = float(delivery.delivery_amount)
                        total_before_delivery_charges = delivery_amount - delivery_charges - damage_charges
                        
                        product_name = delivery.product.name if delivery.product else 'Unknown'
                        is_quantity_only = delivery.product.is_quantity_only if delivery.product else False
                        ownership_quantity = delivery.cylinderledger_set.filter(
                            ownership_movement__in=('customer_received', 'customer_returned')
                        ).values_list('ownership_quantity', flat=True).first() or 0
                        display_empty_returned = (
                            ownership_quantity
                            if delivery.cylinder_movement_type in ('customer_received', 'customer_returned')
                            else delivery.empty_returned or 0
                        )
                        
                        raw_non_bf_transactions.append({
                            'id': str(delivery.id),
                            'type': 'delivery',
                            'customer_id': str(delivery.customer_id),
                            'delivery_obj': delivery,
                            'sort_date': delivery.delivery_date,
                            'created_at': delivery.created_at or timezone.now(),
                            'date': delivery.delivery_date.strftime('%d/%m/%Y') if delivery.delivery_date else 'N/A',
                            'invoice_no': delivery.invoice_no or delivery.delivery_no or '',
                            'item': product_name,
                            'empty': display_empty_returned,
                            'full': delivery.quantity,
                            'rate': float(delivery.unit_price) if delivery.unit_price else 0,
                            'total': delivery_amount,
                            'total_before_delivery_charges': total_before_delivery_charges,
                            'total_after_delivery_charges': delivery_amount,
                            'delivery_charges': delivery_charges,
                            'damage_charges': damage_charges,
                            'damage_description': delivery.damage_description or '',
                            'full_returned': delivery.full_returned or 0,
                            'payment_recv': payment_amount,
                            'is_payment': False,
                            'is_bf': False,
                            'is_quantity_only': is_quantity_only,
                            'description': delivery.description or '',
                            'customer_name': delivery.customer.name,
                            'calculation_details': delivery.calculation_details,
                            'return_details': delivery.return_details,
                        })

                    for payment in payments.order_by('payment_date', 'created_at'):
                        if payment.id in matched_payment_ids:
                            continue
                        
                        raw_non_bf_transactions.append({
                            'id': str(payment.id),
                            'type': 'payment',
                            'customer_id': str(payment.customer_id),
                            'payment_obj': payment,
                            'sort_date': payment.payment_date,
                            'created_at': payment.created_at or timezone.now(),
                            'date': payment.payment_date.strftime('%d/%m/%Y') if payment.payment_date else 'N/A',
                            'invoice_no': payment.invoice_no or '',
                            'item': 'Payment Received',
                            'empty': 0,
                            'full': 0,
                            'rate': 0,
                            'total': 0,
                            'delivery_charges': 0,
                            'damage_charges': 0,
                            'payment_recv': float(payment.amount),
                            'is_payment': True,
                            'is_bf': False,
                            'description': payment.notes or '',
                            'customer_name': payment.customer.name,
                        })

                    # Sort chronologically by (sort_date, created_at)
                    raw_non_bf_transactions.sort(key=lambda x: (x['sort_date'], x['created_at']))

                    # Combine BF with sorted non-BF transactions
                    transactions = [bf_transaction] + raw_non_bf_transactions

                    # Compute running balance and cylinder breakdowns in chronological order
                    running_balance = bf_balance
                    running_cylinders = bf_cylinders.copy()

                    for t in transactions:
                        if t.get('is_bf'):
                            continue

                        old_cylinders_breakdown = running_cylinders.copy()
                        old_cylinders_total = sum(old_cylinders_breakdown.values())
                        old_cylinders_parts = [f"{prod}: {bal}" for prod, bal in old_cylinders_breakdown.items() if bal != 0]
                        old_cylinders_display = ' | '.join(old_cylinders_parts) if old_cylinders_parts else '0'

                        if t['type'] == 'delivery':
                            delivery = t['delivery_obj']
                            is_quantity_only = t.get('is_quantity_only', False)
                            product_name = delivery.product.name if delivery.product else 'Unknown'

                            if not is_quantity_only:
                                ownership_quantity = delivery.cylinderledger_set.filter(
                                    ownership_movement__in=('customer_received', 'customer_returned')
                                ).values_list('ownership_quantity', flat=True).first() or 0

                                if delivery.cylinder_movement_type == 'customer_returned':
                                    net_change = ownership_quantity
                                elif delivery.cylinder_movement_type == 'customer_received':
                                    net_change = -ownership_quantity
                                else:
                                    net_change = delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0)

                                running_cylinders[product_name] = running_cylinders.get(product_name, 0) + net_change

                        new_cylinders_breakdown = running_cylinders.copy()
                        new_cylinders_total = sum(new_cylinders_breakdown.values())
                        new_cylinders_parts = [f"{prod}: {bal}" for prod, bal in new_cylinders_breakdown.items() if bal != 0]
                        new_cylinders_display = ' | '.join(new_cylinders_parts) if new_cylinders_parts else '0'

                        previous_balance = running_balance
                        new_balance = running_balance + t['total'] - t['payment_recv']
                        running_balance = new_balance

                        t['previous_balance'] = previous_balance
                        t['balance'] = new_balance
                        t['old_cylinders_display'] = old_cylinders_display
                        t['new_cylinders_display'] = new_cylinders_display
                        t['old_cylinders_breakdown'] = old_cylinders_breakdown
                        t['new_cylinders_breakdown'] = new_cylinders_breakdown
                        t['old_cylinders_total'] = old_cylinders_total
                        t['new_cylinders_total'] = new_cylinders_total

                    context['transactions'] = transactions
                    context['net_cylinders'] = sum(running_cylinders.values())
                    
                    # ============================================================
                    # CALCULATE TOTALS
                    # ============================================================
                    context['total_deliveries'] = len([t for t in transactions if t['type'] == 'delivery'])
                    context['total_payments'] = len([t for t in transactions if t['type'] == 'payment'])
                    context['total_quantity'] = sum(t['full'] for t in transactions if t['type'] == 'delivery' and not t.get('is_quantity_only'))
                    context['total_empty'] = sum(t['empty'] for t in transactions if t['type'] == 'delivery' and not t.get('is_quantity_only'))
                    context['total_sale_quantity'] = sum(t['full'] for t in transactions if t['type'] == 'delivery' and t.get('is_quantity_only'))
                    context['total_delivery_amount'] = sum(t['total'] for t in transactions if t['type'] == 'delivery')
                    context['total_delivery_charges'] = sum(t['delivery_charges'] for t in transactions if t['type'] == 'delivery')
                    context['total_damage_charges'] = sum(t.get('damage_charges', 0) for t in transactions if t['type'] == 'delivery')
                    context['total_before_delivery_charges'] = sum(t.get('total_before_delivery_charges', t['total']) for t in transactions if t['type'] == 'delivery')
                    context['total_after_delivery_charges'] = sum(t.get('total_after_delivery_charges', t['total']) for t in transactions if t['type'] == 'delivery')
                    context['total_payment_amount'] = sum(t['payment_recv'] for t in transactions if not t.get('is_bf', False))
                    context['net_amount'] = running_balance
                    context['outstanding_balance'] = running_balance
                    
                    # ============================================================
                    # PRODUCT SUMMARY
                    # ============================================================
                    product_summary = {}
                    for trans in transactions:
                        if trans['type'] == 'delivery' and trans['item'] != 'Payment Received':
                            product_name = trans['item']
                            if product_name not in product_summary:
                                product_summary[product_name] = {
                                    'name': product_name,
                                    'quantity': 0,
                                    'amount': 0,
                                    'returns': 0,
                                    'delivery_charges': 0,
                                    'is_quantity_only': trans.get('is_quantity_only', False)
                                }
                            product_summary[product_name]['quantity'] += trans['full']
                            product_summary[product_name]['amount'] += trans['total']
                            product_summary[product_name]['returns'] += trans['empty'] + trans.get('full_returned', 0)
                            product_summary[product_name]['delivery_charges'] += trans['delivery_charges']
                    
                    context['product_summary'] = product_summary.values()
                    
                    # ============================================================
                    # WALK-IN CUSTOMERS LIST BREAKDOWN
                    # ============================================================
                    walkin_customers_list = []
                    for wc in walkin_customers:
                        walkin_customers_list.append({
                            'pk': str(wc.pk),
                            'customer_code': wc.customer_code or 'WALKIN',
                            'name': wc.name or 'Walk-in Customer',
                            'mobile': wc.mobile or 'N/A',
                            'security_deposit': float(wc.security_deposit or 0),
                            'personal_cylinders': int(wc.personal_cylinders or 0),
                            'outstanding_balance': wc.get_outstanding_balance(),
                            'cylinder_balance': wc.get_cylinder_balance(),
                        })
                    context['walkin_customers_list'] = walkin_customers_list
                    
                else:
                    # No walk-in customers found
                    context['selected_customer'] = None
                    context['transactions'] = []
                    
            else:
                # ============================================================
                # REGULAR CUSTOMER LEDGER (Existing code)
                # ============================================================
                customer = get_object_or_404(Customer, pk=customer_id)
                context['selected_customer'] = customer
                context['customer_name'] = customer.name
                context['is_walkin_view'] = False
                
                context['security_deposit'] = customer.security_deposit or 0
                context['personal_cylinders'] = customer.personal_cylinders or 0
                
                # Calculate Net Cylinders
                deliveries_for_calc = Delivery.objects.filter(customer=customer)
                if date_from:
                    try:
                        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                        deliveries_for_calc = deliveries_for_calc.filter(delivery_date__gte=date_from_obj)
                    except ValueError:
                        pass
                if date_to:
                    try:
                        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                        deliveries_for_calc = deliveries_for_calc.filter(delivery_date__lte=date_to_obj)
                    except ValueError:
                        pass
                
                total_quantity = deliveries_for_calc.aggregate(total=Sum('quantity'))['total'] or 0
                total_empty = deliveries_for_calc.aggregate(total=Sum('empty_returned'))['total'] or 0
                total_full_returned = deliveries_for_calc.aggregate(total=Sum('full_returned'))['total'] or 0
                bf_cylinders = customer.bf_cylinders or {}
                bf_total = sum(int(quantity or 0) for quantity in bf_cylinders.values())
                net_cylinders = bf_total + total_quantity - total_empty - total_full_returned
                total_cylinders_at_shop = net_cylinders + (customer.personal_cylinders or 0)
                
                context['net_cylinders'] = net_cylinders
                context['total_cylinders_at_shop'] = total_cylinders_at_shop
                
                deliveries = Delivery.objects.filter(customer=customer)
                payments = Payment.objects.filter(customer=customer)
                
                if date_from:
                    try:
                        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                        bf_balance = customer.get_balance_before_date(date_from_obj)
                        bf_cylinders = customer.get_cylinders_before_date(date_from_obj)
                        deliveries = deliveries.filter(delivery_date__gte=date_from_obj)
                        payments = payments.filter(payment_date__gte=date_from_obj)
                    except ValueError:
                        bf_balance = float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
                        bf_cylinders = customer.bf_cylinders or {}
                else:
                    bf_balance = float(customer.bf_balance or 0) + float(customer.previous_balance or 0)
                    bf_cylinders = customer.bf_cylinders or {}
                
                if date_to:
                    try:
                        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                        deliveries = deliveries.filter(delivery_date__lte=date_to_obj)
                        payments = payments.filter(payment_date__lte=date_to_obj)
                    except ValueError:
                        pass
                
                bf_cylinders_display = ' | '.join([f"{k}: {v}" for k, v in bf_cylinders.items() if v != 0])
                if not bf_cylinders_display:
                    bf_cylinders_display = '0'
                
                bf_transaction = {
                    'type': 'bf',
                    'date': customer.bf_date.strftime('%d/%m/%Y') if customer.bf_date else 'B.F',
                    'invoice_no': '—',
                    'item': 'Opening Balance',
                    'empty': 0,
                    'full': 0,
                    'rate': 0,
                    'total': 0,
                    'delivery_charges': 0,
                    'damage_charges': 0,
                    'payment_recv': 0,
                    'previous_balance': 0,
                    'balance': bf_balance,
                    'is_payment': False,
                    'is_bf': True,
                    'old_cylinders_display': '0',
                    'new_cylinders_display': bf_cylinders_display,
                    'old_cylinders_breakdown': {},
                    'new_cylinders_breakdown': bf_cylinders.copy(),
                    'description': customer.bf_description or '',
                }
                
                delivery_payment_amounts, matched_payment_ids = _get_delivery_payment_map(
                    deliveries,
                    payments,
                )

                # Collect raw non-BF transactions
                raw_non_bf_transactions = []
                
                for delivery in deliveries.order_by('delivery_date', 'created_at'):
                    payment_amount = delivery_payment_amounts.get(delivery.id, 0)
                    delivery_charges = float(delivery.delivery_charges or 0)
                    damage_charges = float(delivery.damage_charges or 0)
                    delivery_amount = float(delivery.delivery_amount)
                    total_before_delivery_charges = delivery_amount - delivery_charges - damage_charges
                    
                    product_name = delivery.product.name if delivery.product else 'Unknown'
                    is_quantity_only = delivery.product.is_quantity_only if delivery.product else False
                    ownership_quantity = delivery.cylinderledger_set.filter(
                        ownership_movement__in=('customer_received', 'customer_returned')
                    ).values_list('ownership_quantity', flat=True).first() or 0
                    display_empty_returned = (
                        ownership_quantity
                        if delivery.cylinder_movement_type in ('customer_received', 'customer_returned')
                        else delivery.empty_returned or 0
                    )
                    
                    raw_non_bf_transactions.append({
                        'id': str(delivery.id),
                        'type': 'delivery',
                        'customer_id': str(delivery.customer_id),
                        'delivery_obj': delivery,
                        'sort_date': delivery.delivery_date,
                        'created_at': delivery.created_at or timezone.now(),
                        'date': delivery.delivery_date.strftime('%d/%m/%Y') if delivery.delivery_date else 'N/A',
                        'invoice_no': delivery.invoice_no or delivery.delivery_no or '',
                        'item': product_name,
                        'empty': display_empty_returned,
                        'full': delivery.quantity,
                        'rate': float(delivery.unit_price) if delivery.unit_price else 0,
                        'total': delivery_amount,
                        'total_before_delivery_charges': total_before_delivery_charges,
                        'total_after_delivery_charges': delivery_amount,
                        'delivery_charges': delivery_charges,
                        'damage_charges': damage_charges,
                        'damage_description': delivery.damage_description or '',
                        'full_returned': delivery.full_returned or 0,
                        'payment_recv': payment_amount,
                        'is_payment': False,
                        'is_bf': False,
                        'is_quantity_only': is_quantity_only,
                        'description': delivery.description or '',
                        'calculation_details': delivery.calculation_details,
                        'return_details': delivery.return_details,
                    })

                for payment in payments.order_by('payment_date', 'created_at'):
                    if payment.id in matched_payment_ids:
                        continue
                    
                    raw_non_bf_transactions.append({
                        'id': str(payment.id),
                        'type': 'payment',
                        'customer_id': str(payment.customer_id),
                        'payment_obj': payment,
                        'sort_date': payment.payment_date,
                        'created_at': payment.created_at or timezone.now(),
                        'date': payment.payment_date.strftime('%d/%m/%Y') if payment.payment_date else 'N/A',
                        'invoice_no': payment.invoice_no or '',
                        'item': 'Payment Received',
                        'empty': 0,
                        'full': 0,
                        'rate': 0,
                        'total': 0,
                        'delivery_charges': 0,
                        'damage_charges': 0,
                        'payment_recv': float(payment.amount),
                        'is_payment': True,
                        'is_bf': False,
                        'description': payment.notes or '',
                    })

                # Sort chronologically by (sort_date, created_at)
                raw_non_bf_transactions.sort(key=lambda x: (x['sort_date'], x['created_at']))

                # Combine BF with sorted non-BF transactions
                transactions = [bf_transaction] + raw_non_bf_transactions

                # Compute running balance and cylinder breakdowns in chronological order
                running_balance = bf_balance
                running_cylinders = bf_cylinders.copy()

                for t in transactions:
                    if t.get('is_bf'):
                        continue

                    old_cylinders_breakdown = running_cylinders.copy()
                    old_cylinders_total = sum(old_cylinders_breakdown.values())
                    old_cylinders_parts = [f"{prod}: {bal}" for prod, bal in old_cylinders_breakdown.items() if bal != 0]
                    old_cylinders_display = ' | '.join(old_cylinders_parts) if old_cylinders_parts else '0'

                    if t['type'] == 'delivery':
                        delivery = t['delivery_obj']
                        is_quantity_only = t.get('is_quantity_only', False)
                        product_name = delivery.product.name if delivery.product else 'Unknown'

                        if not is_quantity_only:
                            ownership_quantity = delivery.cylinderledger_set.filter(
                                ownership_movement__in=('customer_received', 'customer_returned')
                            ).values_list('ownership_quantity', flat=True).first() or 0

                            if delivery.cylinder_movement_type == 'customer_returned':
                                net_change = ownership_quantity
                            elif delivery.cylinder_movement_type == 'customer_received':
                                net_change = -ownership_quantity
                            else:
                                net_change = delivery.quantity - (delivery.empty_returned or 0) - (delivery.full_returned or 0)

                            running_cylinders[product_name] = running_cylinders.get(product_name, 0) + net_change

                    new_cylinders_breakdown = running_cylinders.copy()
                    new_cylinders_total = sum(new_cylinders_breakdown.values())
                    new_cylinders_parts = [f"{prod}: {bal}" for prod, bal in new_cylinders_breakdown.items() if bal != 0]
                    new_cylinders_display = ' | '.join(new_cylinders_parts) if new_cylinders_parts else '0'

                    previous_balance = running_balance
                    new_balance = running_balance + t['total'] - t['payment_recv']
                    running_balance = new_balance

                    t['previous_balance'] = previous_balance
                    t['balance'] = new_balance
                    t['old_cylinders_display'] = old_cylinders_display
                    t['new_cylinders_display'] = new_cylinders_display
                    t['old_cylinders_breakdown'] = old_cylinders_breakdown
                    t['new_cylinders_breakdown'] = new_cylinders_breakdown
                    t['old_cylinders_total'] = old_cylinders_total
                    t['new_cylinders_total'] = new_cylinders_total
                
                context['transactions'] = transactions
                
                context['total_deliveries'] = len([t for t in transactions if t['type'] == 'delivery'])
                context['total_payments'] = len([t for t in transactions if t['type'] == 'payment'])
                context['total_quantity'] = sum(t['full'] for t in transactions if t['type'] == 'delivery' and not t.get('is_quantity_only'))
                context['total_empty'] = sum(t['empty'] for t in transactions if t['type'] == 'delivery' and not t.get('is_quantity_only'))
                context['total_sale_quantity'] = sum(t['full'] for t in transactions if t['type'] == 'delivery' and t.get('is_quantity_only'))
                context['total_delivery_amount'] = sum(t['total'] for t in transactions if t['type'] == 'delivery')
                context['total_delivery_charges'] = sum(t['delivery_charges'] for t in transactions if t['type'] == 'delivery')
                context['total_damage_charges'] = sum(t.get('damage_charges', 0) for t in transactions if t['type'] == 'delivery')
                context['total_before_delivery_charges'] = sum(t.get('total_before_delivery_charges', t['total']) for t in transactions if t['type'] == 'delivery')
                context['total_after_delivery_charges'] = sum(t.get('total_after_delivery_charges', t['total']) for t in transactions if t['type'] == 'delivery')
                context['total_payment_amount'] = sum(t['payment_recv'] for t in transactions if not t.get('is_bf', False))
                context['net_amount'] = running_balance
                
                product_summary = {}
                for trans in transactions:
                    if trans['type'] == 'delivery' and trans['item'] != 'Payment Received':
                        product_name = trans['item']
                        if product_name not in product_summary:
                            product_summary[product_name] = {
                                'name': product_name,
                                'quantity': 0,
                                'amount': 0,
                                'returns': 0,
                                'delivery_charges': 0,
                                'is_quantity_only': trans.get('is_quantity_only', False)
                            }
                        product_summary[product_name]['quantity'] += trans['full']
                        product_summary[product_name]['amount'] += trans['total']
                        product_summary[product_name]['returns'] += trans['empty'] + trans.get('full_returned', 0)
                        product_summary[product_name]['delivery_charges'] += trans['delivery_charges']
                
                context['product_summary'] = product_summary.values()
                context['net_cylinders'] = sum(running_cylinders.values())
                context['outstanding_balance'] = running_balance
        
        # Get all customers for dropdown
        context['customers'] = Customer.objects.all().order_by('name')
        
        # If search is provided, filter customers
        if search:
            context['search_results'] = Customer.objects.filter(
                Q(name__icontains=search) |
                Q(mobile__icontains=search) |
                Q(customer_code__icontains=search) |
                Q(area__icontains=search)
            ).order_by('name')
        
        return context


@login_required
@require_POST
def delete_customer(request, pk):
    """Permanently remove a customer and all records belonging to them."""
    with transaction.atomic():
        customer = get_object_or_404(
            Customer.objects.select_for_update(),
            pk=pk,
        )
        deliveries = Delivery.objects.filter(customer=customer)

        # These relations use SET_NULL, so remove their customer-owned records explicitly.
        FBRInvoiceItem.objects.filter(delivery__in=deliveries).delete()
        Notification.objects.filter(customer=customer).delete()
        customer.delete()

    messages.success(request, 'Customer and all related records were permanently deleted.')
    return redirect('customers:list')