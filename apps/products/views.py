from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import re
from .models import Factory, FactoryFillTransaction, Product, StockOpeningBalance
from django.db import transaction
from django.db.models import Q
from .forms import ProductForm, FactoryFillTransactionForm
from apps.deliveries.models import Delivery
from apps.suppliers.models import Purchase
from apps.customers.models import Customer


STOCK_DETAIL_CATEGORIES = (
    ('oxygen_liquid', 'OXYGEN LIQUID'),
    ('co2', 'CO2'),
    ('lpg', 'LPG'),
)


def get_stock_detail_category(product_name):
    """Return the stock-details category for an allowed gas product.
    
    Groups oxygen, nitrogen, argon, DA, and special argon all as 'oxygen_liquid'.
    """
    product_upper = product_name.upper() if product_name else ''

    if 'CO2' in product_upper or 'CARBON DIOXIDE' in product_upper:
        return 'co2'
    if 'LPG' in product_upper:
        return 'lpg'
    # Group all breathing gases (oxygen, nitrogen, argon, DA) as oxygen_liquid
    oxygen_terms = ['OXYGEN', 'O2', 'NITROGEN', 'N2', 'ARGON', 'DA', 'SPECIAL ARGON']
    for term in oxygen_terms:
        if term in product_upper:
            return 'oxygen_liquid'
    return None

class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = 'products/list.html'
    context_object_name = 'products'
    
    def get_queryset(self):
        queryset = super().get_queryset()
        search_query = self.request.GET.get('q', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(product_code__icontains=search_query)
            )
        return queryset.order_by('name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add counts for badges
        context['total_products'] = Product.objects.count()
        context['sellable_count'] = Product.objects.filter(is_sellable=True).count()
        context['purchasable_count'] = Product.objects.filter(is_purchasable=True).count()
        context['factories'] = Factory.objects.all()
        context['search_query'] = self.request.GET.get('q', '').strip()
        return context

class ProductCreateView(LoginRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'products/form.html'
    success_url = reverse_lazy('products:list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = False
        context['page_title'] = 'Add New Product'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Product "{form.instance.name}" created successfully!')
        return super().form_valid(form)

class ProductUpdateView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'products/form.html'
    success_url = reverse_lazy('products:list')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_edit'] = True
        context['page_title'] = f'Edit Product - {self.object.name}'
        return context
    
    def form_valid(self, form):
        messages.success(self.request, f'Product "{form.instance.name}" updated successfully!')
        return super().form_valid(form)

class ProductDeleteView(LoginRequiredMixin, DeleteView):
    model = Product
    template_name = 'products/confirm_delete.html'
    success_url = reverse_lazy('products:list')
    
    def delete(self, request, *args, **kwargs):
        product = self.get_object()
        product_name = product.name
        messages.success(self.request, f'Product "{product_name}" has been deleted successfully.')
        return super().delete(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Delete Product - {self.object.name}'
        return context


class FactoryFillView(LoginRequiredMixin, TemplateView):
    template_name = 'products/factory_fill.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['factories'] = Factory.objects.all()
        context['products'] = Product.objects.all().order_by('name')
        context['selected_factory'] = self.request.GET.get('factory', '')
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action == 'create_factory':
            name = request.POST.get('factory_name', '').strip().upper()
            if not name:
                messages.error(request, 'Factory name is required.')
            else:
                factory, created = Factory.objects.get_or_create(name=name)
                messages.success(request, f'Factory "{factory.name}" {"added" if created else "already exists"}.')
            return redirect('products:factory_fill')

        try:
            factory = get_object_or_404(Factory, pk=request.POST.get('factory'))
            product_id = request.POST.get('product')
            product = get_object_or_404(Product, pk=product_id)
            transaction_date = datetime.strptime(
                request.POST.get('transaction_date', ''), '%Y-%m-%d'
            ).date()
            empty_sent = int(request.POST.get('empty_sent') or 0)
            full_received = int(request.POST.get('full_received', '0'))
            if empty_sent < 0 or full_received < 0:
                raise ValueError
        except (TypeError, ValueError, ValidationError):
            messages.error(request, 'Enter a valid date and non-negative cylinder quantities.')
            return redirect('products:factory_fill')

        with transaction.atomic():
            locked_product = Product.objects.select_for_update().get(pk=product.pk)
            if locked_product.empty_stock_quantity < empty_sent:
                messages.error(
                    request,
                    f'Only {locked_product.empty_stock_quantity} empty {locked_product.name} '
                    'cylinders are available.',
                )
                return redirect('products:factory_fill')
            FactoryFillTransaction.objects.create(
                factory=factory,
                product=locked_product,
                transaction_date=transaction_date,
                empty_sent=empty_sent,
                full_received=full_received,
                invoice_number=request.POST.get('invoice_number', '').strip() or None,
                notes=request.POST.get('notes', '').strip(),
                created_by=request.user,
            )
            locked_product.empty_stock_quantity -= empty_sent
            locked_product.stock_quantity += full_received
            locked_product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])

        messages.success(request, f'{product.name} factory fill recorded successfully.')
        return redirect('products:factory_fill')


class FactoryDetailView(LoginRequiredMixin, TemplateView):
    template_name = 'products/factory_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        factory = get_object_or_404(Factory, pk=kwargs['pk'])
        context['factory'] = factory
        context['transactions'] = factory.fill_transactions.select_related('product', 'created_by')
        return context


class FactoryFillUpdateView(LoginRequiredMixin, UpdateView):
    model = FactoryFillTransaction
    form_class = FactoryFillTransactionForm
    template_name = 'products/factory_fill_edit.html'

    def form_valid(self, form):
        with transaction.atomic():
            fill = FactoryFillTransaction.objects.select_for_update().get(pk=self.object.pk)
            old_product = Product.objects.select_for_update().get(pk=fill.product_id)
            new_product_id = form.cleaned_data['product'].pk
            new_product = old_product if new_product_id == old_product.pk else Product.objects.select_for_update().get(pk=new_product_id)

            stock_fields_changed = (
                new_product.pk != old_product.pk
                or form.cleaned_data['full_received'] != fill.full_received
                or form.cleaned_data['empty_sent'] != fill.empty_sent
            )
            if stock_fields_changed and old_product.stock_quantity < fill.full_received:
                form.add_error(None, 'This fill cannot be edited because some received cylinders are already used.')
                return self.form_invalid(form)

            old_product.empty_stock_quantity += fill.empty_sent
            if stock_fields_changed:
                old_product.stock_quantity -= fill.full_received

            if new_product.pk != old_product.pk:
                old_product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])
            new_empty_stock = (
                new_product.empty_stock_quantity - form.cleaned_data['empty_sent']
                if stock_fields_changed else old_product.empty_stock_quantity
            )
            if new_empty_stock < 0:
                form.add_error('empty_sent', f'Only {new_product.empty_stock_quantity} empty {new_product.name} cylinders are available.')
                return self.form_invalid(form)

            if stock_fields_changed:
                new_product.empty_stock_quantity = new_empty_stock
                new_product.stock_quantity += form.cleaned_data['full_received']
            new_product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])
            fill.factory = form.cleaned_data['factory']
            fill.product = new_product
            fill.transaction_date = form.cleaned_data['transaction_date']
            fill.empty_sent = form.cleaned_data['empty_sent']
            fill.full_received = form.cleaned_data['full_received']
            fill.invoice_number = form.cleaned_data['invoice_number']
            fill.notes = form.cleaned_data['notes']
            fill.save(update_fields=[
                'factory', 'product', 'transaction_date', 'empty_sent',
                'full_received', 'invoice_number', 'notes',
            ])

        messages.success(self.request, 'Factory fill updated successfully.')
        return redirect('products:factory_detail', pk=fill.factory_id)


class FactoryFillDeleteView(LoginRequiredMixin, DeleteView):
    model = FactoryFillTransaction
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            fill = FactoryFillTransaction.objects.select_for_update().get(pk=kwargs['pk'])
            product = Product.objects.select_for_update().get(pk=fill.product_id)
            factory_id = fill.factory_id
            product.empty_stock_quantity += fill.empty_sent
            product.stock_quantity -= fill.full_received
            product.save(update_fields=['empty_stock_quantity', 'stock_quantity', 'updated_at'])
            fill.delete()

        messages.success(request, 'Factory fill deleted and stock movement reversed successfully.')
        return redirect('products:factory_detail', pk=factory_id)


@login_required
def factory_product_stock_api(request):
    product = get_object_or_404(Product, pk=request.GET.get('product'))
    return JsonResponse({
        'id': str(product.pk),
        'name': product.name,
        'empty_stock_quantity': product.empty_stock_quantity,
        'stock_quantity': product.stock_quantity,
    })

def product_stock_api(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return JsonResponse({
        'id': str(product.id),
        'name': product.name,
        'stock_quantity': product.stock_quantity,
        'is_purchasable': product.is_purchasable,
        'is_sellable': product.is_sellable
    })

class StockDetailsView(LoginRequiredMixin, TemplateView):
    template_name = 'products/stock_details.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_product = self.request.GET.get('product', '')
        start_date_text = self.request.GET.get('start_date', '')
        end_date_text = self.request.GET.get('end_date', '')

        context['products'] = STOCK_DETAIL_CATEGORIES
        context['selected_product'] = selected_product
        context['start_date'] = start_date_text
        context['end_date'] = end_date_text
        context['movements'] = []

        selected_customer_ids = self.request.session.get('fbr_selected_customer_ids', [])
        context['selected_customer_ids'] = selected_customer_ids
        context['selected_customers'] = Customer.objects.filter(
            pk__in=selected_customer_ids
        ).order_by('name')

        if not selected_product:
            return context

        category_key = selected_product
        try:
            product = Product.objects.get(pk=selected_product)
            category_key = get_stock_detail_category(product.name)
        except (Product.DoesNotExist, ValidationError, ValueError):
            pass

        category_names = dict(STOCK_DETAIL_CATEGORIES)
        if category_key not in category_names:
            return context
        context['product_name'] = category_names[category_key]
        context['product_category'] = category_key
        context['unit'] = 'M3' if category_key == 'oxygen_liquid' else 'KG'

        category_products = [
            product for product in Product.objects.all()
            if get_stock_detail_category(product.name) == category_key
        ]
        product_ids = [product.pk for product in category_products]
        if not product_ids:
            return context

        start_date = self._parse_date(start_date_text)
        end_date = self._parse_date(end_date_text)
        
        # Get FBR customer deliveries to determine purchase date range
        fbr_deliveries = Delivery.objects.filter(
            product_id__in=product_ids,
            customer_id__in=selected_customer_ids,
        )
        fbr_delivery_start = fbr_deliveries.order_by('delivery_date').values_list('delivery_date', flat=True).first()
        fbr_delivery_end = fbr_deliveries.order_by('-delivery_date').values_list('delivery_date', flat=True).first()
        
        if not start_date:
            start_date = Purchase.objects.filter(
                product_id__in=product_ids,
                tax_type='with_tax',
            ).order_by('purchase_date').values_list('purchase_date', flat=True).first()
            if fbr_delivery_start and (not start_date or fbr_delivery_start < start_date):
                start_date = fbr_delivery_start
        if not end_date:
            end_date = timezone.localdate()

        context['report_start_date'] = start_date
        context['report_end_date'] = end_date

        # Filter purchases: only show those with sales tax
        # Only taxable purchases should appear in stock details
        purchases = Purchase.objects.filter(
            product_id__in=product_ids,
            purchase_date__lte=end_date,
            tax_type='with_tax',
        )
        if fbr_delivery_end:
            # Only show purchases on or before the last FBR delivery date
            purchases = purchases.filter(purchase_date__lte=fbr_delivery_end)
        
        deliveries = Delivery.objects.filter(
            product_id__in=product_ids,
            customer_id__in=selected_customer_ids,
            delivery_date__lte=end_date,
        )

        saved_opening = StockOpeningBalance.objects.filter(category=category_key).first()
        if saved_opening:
            opening_balance = saved_opening.quantity
        else:
            # Fallback for categories that have not been configured yet.
            opening_balance = sum(
                (Decimal(str(product.stock_quantity or 0)) for product in category_products),
                Decimal('0'),
            )
            for purchase in purchases:
                if start_date and purchase.purchase_date >= start_date:
                    opening_balance -= Decimal(str(purchase.quantity or 0))
            for delivery in deliveries:
                if start_date and delivery.delivery_date >= start_date:
                    opening_balance += self._fbr_quantity(delivery)
                    opening_balance -= Decimal(str(delivery.full_returned or 0))

        movements = []
        if start_date:
            purchases = purchases.filter(purchase_date__gte=start_date)
            deliveries = deliveries.filter(delivery_date__gte=start_date)

        for purchase in purchases:
            movements.append({
                'date': purchase.purchase_date,
                'invoice': purchase.invoice_no or purchase.purchase_no,
                'party': purchase.supplier.name,
                'type': 'in',
                'in_qty': Decimal(str(purchase.quantity or 0)),
                'out_qty': None,
                'unit': context['unit'],
                'description': purchase.description or 'Purchase from supplier',
                'sort_time': purchase.created_at,
            })

        for delivery in deliveries:
            out_quantity = self._fbr_quantity(delivery)
            movements.append({
                'date': delivery.delivery_date,
                'invoice': delivery.invoice_no or delivery.delivery_no,
                'party': delivery.customer.name,
                'type': 'out',
                'in_qty': Decimal(str(delivery.full_returned or 0)) if delivery.full_returned else None,
                'out_qty': out_quantity if out_quantity else None,
                'unit': context['unit'],
                'description': self._delivery_description(delivery),
                'sort_time': delivery.created_at,
            })

        movements.sort(key=lambda item: (item['date'], item['sort_time']))
        running_balance = opening_balance
        for index, movement in enumerate(movements, start=1):
            running_balance += movement['in_qty'] or Decimal('0')
            running_balance -= movement['out_qty'] or Decimal('0')
            movement['serial'] = index
            movement['balance'] = running_balance

        context['opening_balance'] = opening_balance
        context['opening_balance_saved'] = bool(saved_opening)
        context['movements'] = movements
        context['closing_balance'] = running_balance
        context['total_in'] = sum((m['in_qty'] or Decimal('0') for m in movements), Decimal('0'))
        context['total_out'] = sum((m['out_qty'] or Decimal('0') for m in movements), Decimal('0'))
        return context

    @staticmethod
    def _parse_date(value):
        try:
            return datetime.strptime(value, '%Y-%m-%d').date() if value else None
        except ValueError:
            return None

    @staticmethod
    def _delivery_description(delivery):
        details = []
        if delivery.full_returned:
            details.append(f"Full return: {delivery.full_returned} in")
        if delivery.low_pressure_details:
            details.append(f"Low pressure: {len(delivery.low_pressure_details)} adjusted")
        return '; '.join(details) or 'Sale / delivery to customer'

    @staticmethod
    def _fbr_quantity(delivery):
        """Return the quantity used by the FBR invoice for this delivery."""
        product_name = delivery.product.name if delivery.product else ''
        category = get_stock_detail_category(product_name)
        quantity = Decimal(str(delivery.quantity or 0))

        if category == 'oxygen_liquid':
            base_amount = quantity * Decimal(str(delivery.unit_price or 0))
            ex_value = (base_amount / Decimal('1.18')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            return (ex_value / Decimal('115')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        match = re.search(r'(\d+)\s*KG', product_name.upper())
        kg_per_cylinder = Decimal(match.group(1)) if match else Decimal('1')
        return quantity * kg_per_cylinder


class StockOverviewView(LoginRequiredMixin, TemplateView):
    """Show oxygen and nitrogen stock in cubic metres by cylinder size."""
    template_name = 'products/stock_overview.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grouped = {}

        for product in Product.objects.all().order_by('name'):
            gas, size, capacity = self._gas_size(product.name)
            if not gas:
                continue

            purchases = Purchase.objects.filter(product=product)
            deliveries = Delivery.objects.filter(product=product)
            purchase_multiplier = Decimal('1') if gas in ('LPG', 'CO2') else capacity
            purchased = sum(
                (
                    Decimal(str(purchase.cubic_meters or 0))
                    if size == 'Bulk' and gas in ('OXYGEN', 'NITROGEN')
                    else Decimal(str(purchase.quantity or 0)) * purchase_multiplier
                    for purchase in purchases
                ),
                Decimal('0'),
            )
            dispatched = sum(
                (
                    (Decimal(str(delivery.quantity or 0)) - self._return_quantity(delivery)) * capacity
                    for delivery in deliveries
                ),
                Decimal('0'),
            )

            current_stock = Decimal(str(product.stock_quantity or 0)) * purchase_multiplier
            if not purchased and not dispatched and not current_stock:
                continue

            row = grouped.setdefault(gas, {
                'product_name': gas,
                'unit': 'KG' if gas in ('LPG', 'CO2') else 'M3',
                'purchased': Decimal('0'),
                'dispatched': Decimal('0'),
                'current_stock': Decimal('0'),
                'minimum_stock': Decimal('0'),
                'has_movements': False,
                'size_details': {},
            })
            row['purchased'] += purchased
            row['dispatched'] += dispatched
            row['current_stock'] += current_stock
            row['minimum_stock'] += Decimal(str(product.minimum_stock or 0)) * capacity
            row['has_movements'] = row['has_movements'] or bool(purchases.exists() or deliveries.exists())
            size_detail = row['size_details'].setdefault(size, {
                'capacity': capacity,
                'purchased': Decimal('0'),
                'dispatched': Decimal('0'),
                'current_stock': Decimal('0'),
            })
            size_detail['purchased'] += purchased
            size_detail['dispatched'] += dispatched
            size_detail['current_stock'] += current_stock

        rows = []
        for row in grouped.values():
            if row['has_movements']:
                row['current_stock'] = row['purchased'] - row['dispatched']
            row['size_details'] = [
                {'size': size, **details}
                for size, details in sorted(row['size_details'].items())
            ]
            row['is_low'] = row['current_stock'] <= row['minimum_stock']
            rows.append(row)
        rows.sort(key=lambda row: row['product_name'])

        context['stock_rows'] = rows
        context['total_purchased'] = sum((row['purchased'] for row in rows), Decimal('0'))
        context['total_dispatched'] = sum((row['dispatched'] for row in rows), Decimal('0'))
        context['low_stock_rows'] = [row for row in rows if row['is_low']]
        return context

    @staticmethod
    def _kg_per_cylinder(product_name):
        match = re.search(r'(\d+)\s*KG', (product_name or '').upper())
        return Decimal(match.group(1)) if match else Decimal('1')

    @staticmethod
    def _gas_size(product_name):
        name = (product_name or '').upper()
        if 'LPG' in name:
            match = re.search(r'(\d+(?:\.\d+)?)\s*KG', name)
            if not match:
                return 'LPG', 'Bulk', Decimal('1')
            capacity = Decimal(match.group(1))
            return 'LPG', f'{capacity:g} KG', capacity
        if 'CO2' in name or 'CARBON DIOXIDE' in name:
            match = re.search(r'(\d+(?:\.\d+)?)\s*KG', name)
            if not match:
                return 'CO2', 'Bulk', Decimal('1')
            capacity = Decimal(match.group(1))
            return 'CO2', f'{capacity:g} KG', capacity
        if 'OXYGEN' in name or re.search(r'\bO2\b', name):
            gas = 'OXYGEN'
        elif 'NITROGEN' in name or re.search(r'\bN2\b', name):
            gas = 'NITROGEN'
        else:
            return None, None, Decimal('0')

        if 'SMALL' in name or '6.8' in name:
            return gas, 'Small', Decimal('6.8')
        if 'BIG' in name or '9.9' in name:
            return gas, 'Big', Decimal('9.9')
        return gas, 'Bulk', Decimal('1')

    @staticmethod
    def _return_quantity(delivery):
        return Decimal(str(delivery.full_returned or 0))

    @classmethod
    def _delivery_quantity(cls, delivery):
        category = get_stock_detail_category(delivery.product.name)
        if category in ('lpg', 'co2'):
            return Decimal(str(delivery.quantity or 0)) * cls._kg_per_cylinder(delivery.product.name)
        if category == 'oxygen_liquid':
            return StockDetailsView._fbr_quantity(delivery)
        return Decimal(str(delivery.quantity or 0))

    @classmethod
    def _stock_values(cls, product):
        category = get_stock_detail_category(product.name)
        if category in ('lpg', 'co2'):
            multiplier = cls._kg_per_cylinder(product.name)
            return 'KG', Decimal(str(product.stock_quantity or 0)) * multiplier, Decimal(str(product.minimum_stock or 0)) * multiplier
        if category == 'oxygen_liquid':
            return 'M3', Decimal(str(product.stock_quantity or 0)), Decimal(str(product.minimum_stock or 0))
        return 'Units', Decimal(str(product.stock_quantity or 0)), Decimal(str(product.minimum_stock or 0))


@login_required
def save_stock_opening_balance(request):
    if request.method != 'POST':
        return redirect('products:stock_details')

    category = request.POST.get('category', '')
    amount_text = request.POST.get('quantity', '').strip()
    if category not in dict(STOCK_DETAIL_CATEGORIES):
        messages.error(request, 'Invalid stock category.')
        return redirect('products:stock_details')

    try:
        quantity = Decimal(amount_text)
        if quantity < 0:
            raise ValueError
    except (ArithmeticError, TypeError, ValueError):
        messages.error(request, 'Opening stock must be a valid non-negative number.')
        return redirect(f"/products/stock-details/?product={category}")

    StockOpeningBalance.objects.update_or_create(
        category=category,
        defaults={'quantity': quantity},
    )
    messages.success(request, 'Opening stock balance updated.')
    return redirect(f"/products/stock-details/?product={category}")