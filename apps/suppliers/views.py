from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.db.models import Sum, Q
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import pytz
import json
import uuid

from .models import Supplier, Purchase
from apps.products.models import Product

PKT = pytz.timezone('Asia/Karachi')


# ============================================================
# HELPER FUNCTIONS FOR PRODUCT TYPE DETECTION
# ============================================================
def is_argon_product(product_name):
    """Check if product is Argon, Special Argon, Gas Mix, DA, or Dry Air"""
    name_lower = product_name.lower()
    return ('argon' in name_lower or 
            'special argon' in name_lower or 
            'mixture' in name_lower or
            'da' in name_lower or
            'dry air' in name_lower or
            'da gas' in name_lower)

def is_lpg_product(product_name):
    """Check if product is LPG"""
    return 'lpg' in product_name.lower()

def is_oxygen_product(product_name):
    """Check if product is Oxygen"""
    return 'oxygen' in product_name.lower()

def is_nitrogen_product(product_name):
    """Check if product is Nitrogen"""
    name_lower = product_name.lower()
    return 'nitrogen' in name_lower or 'n2' in name_lower


class SupplierListView(LoginRequiredMixin, ListView):
    model = Supplier
    template_name = 'suppliers/list.html'
    context_object_name = 'suppliers'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(mobile__icontains=search) |
                Q(supplier_code__icontains=search)
            )
        return queryset


class SupplierCreateView(LoginRequiredMixin, CreateView):
    model = Supplier
    template_name = 'suppliers/form.html'
    fields = ['name', 'mobile', 'address', 'bf_balance', 'ntn', 'stn', 'notes']
    success_url = reverse_lazy('suppliers:list')
    
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        next_number = Supplier.objects.count() + 1
        supplier_code = f'SUP-{next_number:04d}'
        while Supplier.objects.filter(supplier_code=supplier_code).exists():
            next_number += 1
            supplier_code = f'SUP-{next_number:04d}'
        form.instance.supplier_code = supplier_code
        messages.success(self.request, f'Supplier "{form.instance.name}" created successfully!')
        return super().form_valid(form)


class SupplierUpdateView(LoginRequiredMixin, UpdateView):
    model = Supplier
    template_name = 'suppliers/form.html'
    fields = ['name', 'mobile', 'address', 'bf_balance', 'ntn', 'stn', 'notes']
    success_url = reverse_lazy('suppliers:list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Supplier "{form.instance.name}" updated successfully!')
        return super().form_valid(form)


class SupplierDeleteView(LoginRequiredMixin, DeleteView):
    model = Supplier
    template_name = 'suppliers/confirm_delete.html'
    success_url = reverse_lazy('suppliers:list')
    
    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Supplier deleted successfully!')
        return super().delete(request, *args, **kwargs)


class PurchaseEntryView(LoginRequiredMixin, TemplateView):
    """Purchase Entry - Add/view purchase entries"""
    template_name = 'suppliers/purchase_entry.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        date_str = self.request.GET.get('date', '')
        selected_date = timezone.now().astimezone(PKT).date()
        
        if date_str:
            try:
                selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                selected_date = timezone.now().astimezone(PKT).date()
        
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)
        today = timezone.now().astimezone(PKT).date()
        
        context['selected_date'] = selected_date
        context['prev_date'] = prev_date
        context['next_date'] = next_date
        context['today'] = today
        context['has_next'] = next_date <= today
        
        context['suppliers'] = Supplier.objects.all().order_by('name')
        context['products'] = Product.objects.filter(is_purchasable=True).order_by('name')
        
        # Get purchases for selected date
        purchases = Purchase.objects.filter(purchase_date=selected_date).order_by('created_at', 'pk')
        
        # Build activities for display
        activities = []
        supplier_balances = {
            str(supplier.pk): Decimal(supplier.bf_balance)
            for supplier in context['suppliers']
        }
        previous_purchases = Purchase.objects.filter(
            purchase_date__lt=selected_date,
        ).select_related('supplier').order_by('purchase_date', 'created_at', 'pk')
        for previous_purchase in previous_purchases:
            supplier_key = str(previous_purchase.supplier_id)
            supplier_balances[supplier_key] += (
                previous_purchase.total_amount - previous_purchase.paid_amount
            )
        daily_net_balance = Decimal('0')

        for purchase in purchases:
            created_at_pkt = purchase.created_at.astimezone(PKT) if purchase.created_at else None
            
            supplier_key = str(purchase.supplier_id)
            old_balance = supplier_balances[supplier_key]
            new_balance = old_balance + purchase.total_amount - purchase.paid_amount
            supplier_balances[supplier_key] = new_balance
            daily_net_balance += purchase.total_amount - purchase.paid_amount

            if not purchase.product_id:
                activities.append({
                    'id': str(purchase.id),
                    'purchase_no': purchase.purchase_no,
                    'invoice_no': purchase.invoice_no or '',
                    'supplier': purchase.supplier,
                    'supplier_name': purchase.supplier.name,
                    'product_name': 'Payment Only',
                    'quantity': 0,
                    'cubic_meters': 0,
                    'unit_price': 0,
                    'rate_without_tax': 0,
                    'tax_per_m3': 0,
                    'rate_with_tax_per_m3': 0,
                    'total_amount': 0,
                    'delivery_charges': 0,
                    'extra_charges': 0,
                    'paid_amount': purchase.paid_amount,
                    'payment_type': purchase.payment_type,
                    'description': purchase.description or 'Payment Only',
                    'tax_info': '',
                    'purchase_date': purchase.purchase_date,
                    'day': purchase.purchase_date.strftime('%A'),
                    'created_time': created_at_pkt.strftime('%I:%M %p') if created_at_pkt else 'N/A',
                    'old_balance': old_balance,
                    'new_balance': new_balance,
                    'is_payment': True,
                    'tax_type': purchase.get_tax_type_display(),
                    'sales_tax_rate': 0,
                    'subtotal_amount': 0,
                    'sales_tax_amount': 0,
                    'total_cubic_meters': 0,
                    'display_m3': 0,
                    'is_argon': False,
                    'is_oxygen': False,
                    'is_nitrogen': False,
                    'is_lpg': False,
                    'is_co2': False,
                    'rate_per_cylinder': 0,
                    'cylinder_qty': 0,
                    'cylinder_weight': 0,
                    'm3_per_cylinder': 0,
                    'rate_with_tax': 0,
                    'tax_per_unit': 0,
                    'br_rate': 11.80,
                    'rate_per_kg': 0,
                })
                continue
            
            # Check product types using helper functions
            product_name = purchase.product.name.lower()
            is_argon = is_argon_product(product_name)
            is_oxygen = is_oxygen_product(product_name)
            is_nitrogen = is_nitrogen_product(product_name)
            is_lpg = is_lpg_product(product_name)
            is_co2 = 'co2' in product_name and not is_lpg
            
            # Get the actual cubic meters value
            cubic_meters_value = getattr(purchase, 'cubic_meters', 0)
            total_cubic_meters = getattr(purchase, 'total_cubic_meters', 0)
            
            # For Oxygen/Nitrogen, quantity is in KG
            if is_oxygen or is_nitrogen:
                quantity_kg = float(purchase.quantity)
                display_m3 = float(cubic_meters_value) if cubic_meters_value else 0
            else:
                quantity_kg = float(purchase.quantity)
                display_m3 = float(cubic_meters_value) if cubic_meters_value else 0
            
            # For Argon, show the actual M³ values
            if is_argon:
                if total_cubic_meters > 0:
                    display_m3 = float(total_cubic_meters)
                else:
                    display_m3 = float(purchase.quantity)
            
            # Tax amount is already calculated in the model
            tax_amount = float(purchase.sales_tax_amount) if purchase.sales_tax_amount else 0
            subtotal_amount = float(purchase.subtotal_amount) if purchase.subtotal_amount else 0
            
            # Build description with tax info
            description = purchase.description or ''
            tax_info = ''
            if is_argon:
                if purchase.tax_type == 'with_tax':
                    tax_info = f"🔹 {float(purchase.quantity)} M³ with tax"
                else:
                    tax_info = f"🔸 {float(purchase.quantity)} M³ without tax"
            
            # ============================================================
            # ✅ ADD: Rate without Tax & Tax per M³ for Oxygen/Nitrogen
            # ============================================================
            rate_without_tax = 0
            tax_per_m3 = 0
            rate_with_tax_per_m3 = 0

            if is_oxygen or is_nitrogen:
                tax_rate = float(purchase.sales_tax_rate) if purchase.sales_tax_rate else 0
                rate_without_tax = (
                    float(purchase.unit_price) / 1.18
                    if purchase.tax_type == 'with_tax' else float(purchase.unit_price)
                )
                
                if tax_rate > 0:
                    tax_per_m3 = rate_without_tax * (tax_rate / 100)
                
                rate_with_tax_per_m3 = rate_without_tax + tax_per_m3
            
            # ============================================================
            # ✅ ADD: Ledger-style fields for Argon/LPG
            # ============================================================
            rate_per_cylinder = 0
            m3_per_cylinder = 0
            rate_with_tax = 0
            tax_per_unit = 0
            rate_per_kg = 0
            br_rate = 11.80
            
            if is_lpg and purchase.cylinder_qty > 0 and purchase.cylinder_weight > 0:
                rate_per_kg = float(purchase.unit_price) / br_rate
                rate_per_cylinder = rate_per_kg * float(purchase.cylinder_weight)
                if purchase.tax_type == 'with_tax':
                    rate_per_cylinder *= 1 + (float(purchase.sales_tax_rate) / 100)
            if is_argon:
                # Convert all values to float to avoid Decimal * float errors
                total_cubic_meters_float = float(total_cubic_meters) if total_cubic_meters else 0
                cylinder_qty_float = float(purchase.cylinder_qty) if purchase.cylinder_qty else 0
                unit_price_float = float(purchase.unit_price) if purchase.unit_price else 0
                
                if total_cubic_meters_float > 0 and cylinder_qty_float > 0:
                    m3_per_cylinder = total_cubic_meters_float / cylinder_qty_float
                else:
                    m3_per_cylinder = 0

                rate_without_tax = unit_price_float
                tax_rate = float(purchase.sales_tax_rate) if purchase.tax_type == 'with_tax' else 0
                tax_per_m3 = rate_without_tax * (tax_rate / 100)
                rate_with_tax_per_m3 = rate_without_tax + tax_per_m3
                rate_with_tax = rate_with_tax_per_m3
                tax_per_unit = tax_per_m3
                
                # 🔥 FIX: Convert m3_per_cylinder to float if it's Decimal
                m3_per_cylinder_float = float(m3_per_cylinder) if m3_per_cylinder else 0
                rate_per_cylinder = m3_per_cylinder_float * (
                    rate_with_tax if purchase.tax_type == 'with_tax' else rate_without_tax
                )
            
            activity = {
                'id': str(purchase.id),
                'purchase_no': purchase.purchase_no,
                'invoice_no': purchase.invoice_no or '',
                'supplier': purchase.supplier,
                'supplier_name': purchase.supplier.name,
                'product_name': purchase.product.name,
                'quantity': quantity_kg,
                'cubic_meters': cubic_meters_value,
                'unit_price': purchase.unit_price,
                'rate_without_tax': rate_without_tax,
                'tax_per_m3': tax_per_m3,
                'rate_with_tax_per_m3': rate_with_tax_per_m3,
                'total_amount': purchase.total_amount,
                'delivery_charges': purchase.delivery_charges,
                'extra_charges': purchase.extra_charges,
                'paid_amount': purchase.paid_amount,
                'payment_type': purchase.payment_type,
                'description': description,
                'tax_info': tax_info,
                'purchase_date': purchase.purchase_date,
                'day': purchase.purchase_date.strftime('%A'),
                'created_time': created_at_pkt.strftime('%I:%M %p') if created_at_pkt else 'N/A',
                'old_balance': old_balance,
                'new_balance': new_balance,
                'is_payment': False,
                'tax_type': purchase.get_tax_type_display(),
                'sales_tax_rate': purchase.sales_tax_rate,
                'subtotal_amount': subtotal_amount,
                'sales_tax_amount': tax_amount,
                'total_cubic_meters': total_cubic_meters,
                'display_m3': display_m3,
                'is_argon': is_argon,
                'is_oxygen': is_oxygen,
                'is_nitrogen': is_nitrogen,
                'is_lpg': is_lpg,
                'is_co2': is_co2,
                'rate_per_cylinder': rate_per_cylinder,
                'cylinder_qty': purchase.cylinder_qty,
                'cylinder_weight': purchase.cylinder_weight,
                'm3_per_cylinder': m3_per_cylinder,
                'rate_with_tax': rate_with_tax,
                'tax_per_unit': tax_per_unit,
                'br_rate': br_rate,
                'rate_per_kg': rate_per_kg,
            }
            activities.append(activity)
        
        context['activities'] = activities
        context['total_purchases'] = len(activities)
        context['total_quantity'] = sum(a['quantity'] for a in activities)
        context['total_amount'] = sum(a['total_amount'] for a in activities)
        context['total_paid'] = sum(a['paid_amount'] for a in activities)
        context['net_balance'] = daily_net_balance
        context['total_delivery_charges'] = sum(a['delivery_charges'] for a in activities)
        context['total_extra_charges'] = sum(a['extra_charges'] for a in activities)
        context['total_subtotal'] = sum(a['subtotal_amount'] for a in activities)
        context['total_sales_tax'] = sum(a['sales_tax_amount'] for a in activities)
        
        return context
    
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            selected_date_str = request.POST.get('selected_date', '')
            if selected_date_str:
                try:
                    selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
                except ValueError:
                    selected_date = timezone.now().astimezone(PKT).date()
            else:
                selected_date = timezone.now().astimezone(PKT).date()
            
            # Find all entry blocks (up to 20)
            entries_saved = 0
            for entry_num in range(1, 21):
                supplier_key = f'supplier_id_{entry_num}'
                if supplier_key not in request.POST:
                    continue
                
                supplier_id = request.POST.get(supplier_key)
                if not supplier_id:
                    continue
                
                supplier = get_object_or_404(Supplier, pk=supplier_id)
                product_id = request.POST.get(f'product_id_{entry_num}')
                invoice_no = request.POST.get(f'invoice_no_{entry_num}', '')
                paid_amount = request.POST.get(f'paid_amount_{entry_num}', 0)
                payment_type = request.POST.get(f'payment_type_{entry_num}', 'cash')
                if not product_id:
                    try:
                        paid_amount_value = float(paid_amount) if paid_amount else 0
                    except (ValueError, TypeError):
                        paid_amount_value = 0
                    if paid_amount_value > 0:
                        Purchase.objects.create(
                            supplier=supplier,
                            product=None,
                            quantity=0,
                            unit_price=0,
                            paid_amount=paid_amount_value,
                            payment_type=payment_type,
                            invoice_no=(invoice_no or '').strip(),
                            description='Payment Only',
                            purchase_date=selected_date,
                            created_by=request.user,
                        )
                        entries_saved += 1
                    continue
                
                product = get_object_or_404(Product, pk=product_id)
                entry_group_id = uuid.uuid4()
                
                # Get the quantity from the appropriate field
                quantity = request.POST.get(f'quantity_{entry_num}', 0)
                
                # Get Argon specific fields
                total_cubic_meters = request.POST.get(f'total_cubic_meters_{entry_num}', 0)
                cylinder_weight = request.POST.get(f'cylinder_weight_{entry_num}', 0)
                extra_charges = request.POST.get(f'extra_charges_{entry_num}', 0)
                
                # Get other fields
                unit_price = request.POST.get(f'unit_price_{entry_num}', 0)
                delivery_charges = request.POST.get(f'delivery_charges_{entry_num}', 0)
                paid_amount = request.POST.get(f'paid_amount_{entry_num}', 0)
                payment_type = request.POST.get(f'payment_type_{entry_num}', 'cash')
                invoice_no = request.POST.get(f'invoice_no_{entry_num}', '')
                description = request.POST.get(f'description_{entry_num}', '')
                
                # Tax fields
                tax_type = request.POST.get(f'tax_type_{entry_num}', 'none')
                sales_tax_rate = request.POST.get(f'sales_tax_rate_{entry_num}', 0)
                taxable_qty = request.POST.get(f'taxable_qty_{entry_num}', 0)
                
                try:
                    quantity = float(quantity) if quantity else 0
                    total_cubic_meters = float(total_cubic_meters) if total_cubic_meters else 0
                    cylinder_qty = float(cylinder_qty) if cylinder_qty else 0
                    cylinder_weight = float(cylinder_weight) if cylinder_weight else 0
                    extra_charges = float(extra_charges) if extra_charges else 0
                    unit_price = float(unit_price) if unit_price else 0
                    delivery_charges = float(delivery_charges) if delivery_charges else 0
                    paid_amount = float(paid_amount) if paid_amount else 0
                    sales_tax_rate = float(sales_tax_rate) if sales_tax_rate else 0
                    taxable_qty = float(taxable_qty) if taxable_qty else 0
                except (ValueError, TypeError):
                    continue
                
                # Check if this is an Argon product using helper
                is_argon = is_argon_product(product.name)
                is_lpg = is_lpg_product(product.name)
                
                # For Argon, use total_cubic_meters as the quantity
                if is_argon:
                    quantity = total_cubic_meters if total_cubic_meters > 0 else quantity
                elif is_lpg:
                    quantity = cylinder_qty * cylinder_weight
                
                if quantity <= 0:
                    continue
                
                # Validate taxable_qty
                if taxable_qty < 0:
                    taxable_qty = 0
                if taxable_qty > quantity:
                    taxable_qty = quantity
                
                non_taxable_qty = quantity - taxable_qty

                # Calculate split ratio
                split_ratio = taxable_qty / quantity if quantity > 0 else 0
                
                # Calculate deliveries and paid amounts
                taxable_delivery = delivery_charges * split_ratio
                non_taxable_delivery = delivery_charges - taxable_delivery
                taxable_paid = paid_amount * split_ratio
                non_taxable_paid = paid_amount - taxable_paid
                
                # Calculate Argon-specific split
                taxable_total_m3 = total_cubic_meters * split_ratio if is_argon else 0
                non_taxable_total_m3 = total_cubic_meters - taxable_total_m3 if is_argon else 0
                taxable_cylinder_qty = int(cylinder_qty * split_ratio) if is_argon else 0
                non_taxable_cylinder_qty = cylinder_qty - taxable_cylinder_qty if is_argon else 0
                taxable_lpg_cylinder_qty = round(taxable_qty / cylinder_weight) if is_lpg and cylinder_weight > 0 else 0
                taxable_lpg_cylinder_qty = min(cylinder_qty, max(0, taxable_lpg_cylinder_qty))
                non_taxable_lpg_cylinder_qty = cylinder_qty - taxable_lpg_cylinder_qty if is_lpg else 0

                # 1. Create TAXABLE portion
                if taxable_qty > 0:
                    Purchase.objects.create(
                        supplier=supplier,
                        product=product,
                        entry_group_id=entry_group_id,
                        quantity=taxable_qty,
                        unit_price=unit_price,
                        delivery_charges=taxable_delivery,
                        paid_amount=taxable_paid,
                        payment_type=payment_type,
                        invoice_no=invoice_no,
                        description=description + " (Taxable)",
                        purchase_date=selected_date,
                        created_by=request.user,
                        tax_type='with_tax',
                        sales_tax_rate=sales_tax_rate,
                        total_cubic_meters=taxable_total_m3 if is_argon else 0,
                        cylinder_qty=(taxable_cylinder_qty if is_argon else taxable_lpg_cylinder_qty) if (is_argon or is_lpg) else 0,
                        cylinder_weight=cylinder_weight if (is_argon or is_lpg) else 0,
                        extra_charges=extra_charges * split_ratio if extra_charges else 0,
                    )
                    entries_saved += 1

                # 2. Create NON-TAXABLE portion
                if non_taxable_qty > 0:
                    Purchase.objects.create(
                        supplier=supplier,
                        product=product,
                        entry_group_id=entry_group_id,
                        quantity=non_taxable_qty,
                        unit_price=unit_price,
                        delivery_charges=non_taxable_delivery,
                        paid_amount=non_taxable_paid,
                        payment_type=payment_type,
                        invoice_no=invoice_no,
                        description=description + " (Non-Taxable)",
                        purchase_date=selected_date,
                        created_by=request.user,
                        tax_type='none',
                        sales_tax_rate=0,
                        total_cubic_meters=non_taxable_total_m3 if is_argon else 0,
                        cylinder_qty=(non_taxable_cylinder_qty if is_argon else non_taxable_lpg_cylinder_qty) if (is_argon or is_lpg) else 0,
                        cylinder_weight=cylinder_weight if (is_argon or is_lpg) else 0,
                        extra_charges=extra_charges - (extra_charges * split_ratio) if extra_charges else 0,
                    )
                    entries_saved += 1
                
                # Update stock ONLY ONCE (total quantity)
                product.stock_quantity += quantity
                product.save()
            
            if entries_saved > 0:
                messages.success(request, f'✅ {entries_saved} purchase(s) saved for {selected_date}!')
            else:
                messages.warning(request, 'No entries were saved. Please fill in the form.')
            
            return redirect(f'{request.path}?date={selected_date.strftime("%Y-%m-%d")}')


class SupplierProductLedgerView(LoginRequiredMixin, TemplateView):
    """Supplier Product Ledger - View purchases filtered by product & supplier"""
    template_name = 'suppliers/ledger.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        product_id = self.request.GET.get('product')
        supplier_id = self.request.GET.get('supplier')
        selected_product_ids = self.request.GET.getlist('products')
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        
        if supplier_id:
            product_ids = Purchase.objects.filter(supplier_id=supplier_id).order_by().values_list(
                'product_id', flat=True
            ).distinct()
            context['products'] = Product.objects.filter(id__in=product_ids, is_purchasable=True).order_by('name')
        else:
            context['products'] = Product.objects.filter(is_purchasable=True).order_by('name')

        context['suppliers'] = Supplier.objects.all().order_by('name')
        context['selected_product'] = product_id
        context['selected_product_ids'] = selected_product_ids or ([product_id] if product_id else [])
        context['selected_supplier'] = supplier_id
        context['start_date'] = start_date
        context['end_date'] = end_date
        
        supplier = None
        if supplier_id:
            try:
                supplier = Supplier.objects.get(id=supplier_id)
            except Supplier.DoesNotExist:
                supplier = None
        
        context['supplier'] = supplier

        unallocated_payments = Purchase.objects.none()
        if supplier:
            unallocated_payments = Purchase.objects.filter(
                supplier=supplier,
                product__isnull=True,
                paid_amount__gt=0,
            ).order_by('purchase_date', 'created_at', 'pk')
            if start_date:
                try:
                    unallocated_payments = unallocated_payments.filter(
                        purchase_date__gte=datetime.strptime(start_date, '%Y-%m-%d').date()
                    )
                except ValueError:
                    pass
            if end_date:
                try:
                    unallocated_payments = unallocated_payments.filter(
                        purchase_date__lte=datetime.strptime(end_date, '%Y-%m-%d').date()
                    )
                except ValueError:
                    pass

            payment_balances = {}
            supplier_balance = Decimal(supplier.bf_balance)
            supplier_purchases = Purchase.objects.filter(
                supplier=supplier,
            ).order_by('purchase_date', 'created_at', 'pk')
            for purchase in supplier_purchases:
                balance_before = supplier_balance
                supplier_balance += purchase.total_amount - purchase.paid_amount
                if purchase.product_id is None and purchase.paid_amount > 0:
                    payment_balances[purchase.pk] = (balance_before, supplier_balance)

            unallocated_payments = list(unallocated_payments)
            for payment in unallocated_payments:
                payment.previous_balance, payment.remaining_balance = payment_balances[payment.pk]
        context['unallocated_payments'] = unallocated_payments
        context['unallocated_payments_total'] = sum(
            (payment.paid_amount for payment in unallocated_payments),
            Decimal('0'),
        )

        if not getattr(self, '_building_product_ledgers', False):
            requested_product_ids = selected_product_ids or ([product_id] if product_id else [])
            if supplier_id and not requested_product_ids:
                requested_product_ids = list(
                    Purchase.objects.filter(supplier_id=supplier_id, product__isnull=False)
                    .order_by()
                    .values_list('product_id', flat=True)
                    .distinct()
                )

            product_by_id = {str(product.pk): product for product in context['products']}
            available_product_ids = set(product_by_id)
            if product_id and not selected_product_ids:
                legacy_product = Product.objects.filter(pk=product_id, is_purchasable=True).first()
                if legacy_product:
                    available_product_ids.add(str(legacy_product.pk))
                    product_by_id[str(legacy_product.pk)] = legacy_product
            requested_product_ids = [
                str(selected_id) for selected_id in requested_product_ids
                if str(selected_id) in available_product_ids
            ]
            requested_product_ids = list(dict.fromkeys(requested_product_ids))
            context['selected_product_ids'] = requested_product_ids
            context['ledger_sets'] = []

            for selected_id in requested_product_ids:
                original_query = self.request.GET
                self.request.GET = original_query.copy()
                self.request.GET['product'] = selected_id
                self.request.GET.pop('products', None)
                self._building_product_ledgers = True
                try:
                    ledger_context = self.get_context_data(**kwargs)
                finally:
                    self._building_product_ledgers = False
                    self.request.GET = original_query

                selected_product = product_by_id[selected_id]
                context['ledger_sets'].append({
                    'ledger_entries': ledger_context['ledger_entries'],
                    'product_name': ledger_context['product_name'] or selected_product.name,
                    'supplier_name': ledger_context['supplier_name'] or supplier.name,
                    'is_argon': ledger_context['is_argon'],
                    'is_lpg': ledger_context['is_lpg'],
                    'total_quantity': ledger_context.get('total_quantity', 0),
                    'total_subtotal': ledger_context.get('total_subtotal', 0),
                    'total_tax': ledger_context.get('total_tax', 0),
                    'total_amount': ledger_context.get('total_amount', 0),
                    'total_paid': ledger_context.get('total_paid', 0),
                    'final_balance': ledger_context.get('final_balance', supplier.bf_balance),
                    'total_delivery_charges': ledger_context.get('total_delivery_charges', 0),
                    'total_extra_charges': ledger_context.get('total_extra_charges', 0),
                    'total_m3': ledger_context.get('total_m3', 0),
                    'total_cylinders': ledger_context.get('total_cylinders', 0),
                    'avg_m3_per_cylinder': ledger_context.get('avg_m3_per_cylinder', 0),
                })
            if context['ledger_sets']:
                product_ledgers = context['ledger_sets']
                ledger_entries = [
                    entry
                    for ledger in product_ledgers
                    for entry in ledger['ledger_entries']
                    if not entry['is_bf_row']
                ]
                ledger_entries.sort(
                    key=lambda entry: (
                        entry['date'],
                        entry['created_at'],
                        entry['purchase_no'],
                    )
                )

                running_balance = float(supplier.bf_balance)
                opening_entry = next(
                    (
                        entry
                        for ledger in product_ledgers
                        for entry in ledger['ledger_entries']
                        if entry['is_bf_row']
                    ),
                    None,
                )
                if opening_entry:
                    opening_entry = opening_entry.copy()
                    opening_entry.update({
                        'is_argon': False,
                        'is_lpg': False,
                        'product_name': '',
                    })
                    ledger_entries.insert(0, opening_entry)

                for entry in ledger_entries:
                    if entry['is_bf_row']:
                        entry['balance'] = running_balance
                        continue
                    running_balance += float(entry['total_amount']) - float(entry['paid_amount'])
                    entry['balance'] = running_balance

                total_entries = [entry for entry in ledger_entries if not entry['is_bf_row']]
                combined_ledger = {
                    'ledger_entries': ledger_entries,
                    'product_name': (
                        product_ledgers[0]['product_name']
                        if len(product_ledgers) == 1 else 'All Products'
                    ),
                    'supplier_name': supplier.name,
                    'is_argon': product_ledgers[0]['is_argon'] if len(product_ledgers) == 1 else False,
                    'is_lpg': product_ledgers[0]['is_lpg'] if len(product_ledgers) == 1 else False,
                    'is_unified': len(product_ledgers) > 1,
                    'total_quantity': sum(entry['quantity'] for entry in total_entries),
                    'total_subtotal': sum(entry['subtotal_amount'] for entry in total_entries),
                    'total_tax': sum(entry['sales_tax_amount'] for entry in total_entries),
                    'total_amount': sum(entry['total_amount'] for entry in total_entries),
                    'total_paid': sum(entry['paid_amount'] for entry in total_entries),
                    'final_balance': running_balance,
                    'total_delivery_charges': sum(entry['delivery_charges'] for entry in total_entries),
                    'total_extra_charges': sum(entry['extra_charges'] for entry in total_entries),
                    'total_m3': sum(entry['total_cubic_meters'] for entry in total_entries),
                    'total_cylinders': sum(entry['cylinder_qty'] for entry in total_entries),
                }
                combined_ledger['avg_m3_per_cylinder'] = (
                    combined_ledger['total_m3'] / combined_ledger['total_cylinders']
                    if combined_ledger['total_cylinders'] else 0
                )
                context['ledger_sets'] = [combined_ledger]
                context.update(combined_ledger)
            return context
        
        if product_id and supplier_id and supplier:
            product_queryset = Purchase.objects.filter(
                product_id=product_id,
                supplier_id=supplier_id
            ).order_by('purchase_date', 'created_at')

            if start_date:
                try:
                    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                    product_queryset = product_queryset.filter(purchase_date__gte=start_date_obj)
                except ValueError:
                    pass

            if end_date:
                try:
                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                    product_queryset = product_queryset.filter(purchase_date__lte=end_date_obj)
                except ValueError:
                    pass

            queryset = list(product_queryset)
            queryset.sort(key=lambda purchase: (purchase.purchase_date, purchase.created_at))

            # Check if this is an Argon product using helper
            product = Product.objects.get(id=product_id)
            is_argon = is_argon_product(product.name)
            is_lpg = is_lpg_product(product.name)

            ledger_entries = []

            # START RUNNING BALANCE WITH BF BALANCE
            running_balance = float(supplier.bf_balance)

            # Create BF row
            if supplier.bf_balance != 0:
                ledger_entries.append({
                    'id': None,
                    'date': None,
                    'created_at': None,
                    'day': None,
                    'purchase_no': None,
                    'invoice_no': None,
                    'product_name': '',
                    'quantity': 0,
                    'unit_price': 0,
                    'delivery_charges': 0,
                    'extra_charges': 0,
                    'tax_type': 'Opening Balance',
                    'sales_tax_rate': 0,
                    'subtotal_amount': 0,
                    'sales_tax_amount': 0,
                    'rate_without_tax': 0,
                    'tax_per_m3': 0,
                    'rate_with_tax_per_m3': 0,
                    'total_amount': 0,
                    'paid_amount': 0,
                    'balance': running_balance,
                    'description': 'Opening Balance (BF)',
                    'cubic_meters': 0,
                    'is_bf_row': True,
                    'total_cubic_meters': 0,
                    'cylinder_qty': 0,
                    'm3_per_cylinder': 0,
                    'rate_with_tax': 0,
                    'tax_per_unit': 0,
                    'br_rate': 0,
                    'rate_per_kg': 0,
                    'rate_per_cylinder': 0,
                    'cylinder_weight': 0,
                    'is_argon': is_argon,
                    'is_lpg': is_lpg,
                    'is_oxygen': False,
                    'is_nitrogen': False,
                })

            for purchase in queryset:
                if purchase.product_id is None:
                    # Payment-only row: amount paid is already reflected in the ledger paid column,
                    # but it must also affect the balance through the same running-balance math.
                    running_balance -= float(purchase.paid_amount)
                    entry = {
                        'id': str(purchase.id),
                        'date': purchase.purchase_date,
                        'created_at': purchase.created_at,
                        'day': purchase.purchase_date.strftime('%A'),
                        'purchase_no': purchase.purchase_no,
                        'invoice_no': purchase.invoice_no or '',
                        'product_name': purchase.product.name if purchase.product_id else '',
                        'quantity': 0,
                        'unit_price': 0,
                        'delivery_charges': 0,
                        'extra_charges': 0,
                        'tax_type': 'Payment Only',
                        'sales_tax_rate': 0,
                        'subtotal_amount': 0,
                        'sales_tax_amount': 0,
                        'rate_without_tax': 0,
                        'tax_per_m3': 0,
                        'rate_with_tax_per_m3': 0,
                        'total_amount': 0,
                        'paid_amount': purchase.paid_amount,
                        'payment_type': purchase.payment_type,
                        'balance': running_balance,
                        'description': purchase.description or 'Payment Only',
                        'cubic_meters': 0,
                        'is_bf_row': False,
                        'total_cubic_meters': 0,
                        'cylinder_qty': 0,
                        'm3_per_cylinder': 0,
                        'rate_with_tax': 0,
                        'tax_per_unit': 0,
                        'br_rate': 0,
                        'rate_per_kg': 0,
                        'rate_per_cylinder': 0,
                        'cylinder_weight': 0,
                        'is_argon': False,
                        'is_lpg': False,
                        'is_oxygen': False,
                        'is_nitrogen': False,
                    }
                    ledger_entries.append(entry)
                    continue

                # Calculate amount EXCLUDING delivery charges for balance
                balance_amount = float(purchase.subtotal_amount) + float(purchase.sales_tax_amount)
                running_balance += balance_amount - float(purchase.paid_amount)

                # Calculate total WITHOUT delivery for display in "Total" column
                total_without_delivery = float(purchase.subtotal_amount) + float(purchase.sales_tax_amount)

                # Check product types using helper
                product_name = purchase.product.name.lower()
                is_oxygen = is_oxygen_product(product_name)
                is_nitrogen = is_nitrogen_product(product_name)

                # Calculate Argon-specific fields
                total_cubic_meters = float(purchase.total_cubic_meters) if purchase.total_cubic_meters else 0
                cylinder_qty = purchase.cylinder_qty if purchase.cylinder_qty else 0
                m3_per_cylinder = total_cubic_meters / cylinder_qty if cylinder_qty > 0 else 0

                rate_without_tax = 0
                tax_per_m3 = 0
                rate_with_tax_per_m3 = 0
                rate_per_cylinder = 0
                rate_with_tax = 0
                tax_per_unit = 0

                if is_argon:
                    rate_without_tax = float(purchase.unit_price)
                    tax_rate = float(purchase.sales_tax_rate) if purchase.tax_type == 'with_tax' else 0
                    tax_per_m3 = rate_without_tax * (tax_rate / 100)
                    rate_with_tax_per_m3 = rate_without_tax + tax_per_m3
                    rate_with_tax = rate_with_tax_per_m3
                    tax_per_unit = tax_per_m3
                    rate_per_cylinder = m3_per_cylinder * (
                        rate_with_tax if purchase.tax_type == 'with_tax' else rate_without_tax
                    )

                # ============================================================
                # ✅ ADD: Rate without Tax & Tax per M³ for Oxygen/Nitrogen
                # ============================================================
                if is_oxygen or is_nitrogen:
                    tax_rate = float(purchase.sales_tax_rate) if purchase.sales_tax_rate else 0
                    rate_without_tax = (
                        float(purchase.unit_price) / 1.18
                        if purchase.tax_type == 'with_tax' else float(purchase.unit_price)
                    )
                    tax_per_m3 = rate_without_tax * (tax_rate / 100)
                    rate_with_tax_per_m3 = rate_without_tax + tax_per_m3

                # LPG-specific calculations
                rate_per_kg = 0
                br_rate = 11.80

                if is_lpg and purchase.cylinder_qty > 0 and purchase.cylinder_weight > 0:
                    rate_per_kg = float(purchase.unit_price) / br_rate
                    rate_per_cylinder = rate_per_kg * float(purchase.cylinder_weight)
                    if purchase.tax_type == 'with_tax':
                        rate_per_cylinder *= 1 + (float(purchase.sales_tax_rate) / 100)

                entry = {
                    'id': str(purchase.id),
                    'date': purchase.purchase_date,
                    'created_at': purchase.created_at,
                    'day': purchase.purchase_date.strftime('%A'),
                    'purchase_no': purchase.purchase_no,
                    'invoice_no': purchase.invoice_no or '',
                    'product_name': purchase.product.name,
                    'quantity': purchase.quantity,
                    'unit_price': purchase.unit_price,
                    'delivery_charges': purchase.delivery_charges,
                    'extra_charges': purchase.extra_charges,
                    'tax_type': purchase.get_tax_type_display(),
                    'sales_tax_rate': purchase.sales_tax_rate,
                    'subtotal_amount': purchase.subtotal_amount,
                    'sales_tax_amount': purchase.sales_tax_amount,
                    'rate_without_tax': rate_without_tax,
                    'tax_per_m3': tax_per_m3,
                    'rate_with_tax_per_m3': rate_with_tax_per_m3,
                    'total_amount': total_without_delivery,
                    'paid_amount': purchase.paid_amount,
                    'payment_type': purchase.payment_type,
                    'balance': running_balance,
                    'description': purchase.description or '',
                    'cubic_meters': getattr(purchase, 'cubic_meters', 0),
                    'is_bf_row': False,
                    'total_cubic_meters': total_cubic_meters,
                    'cylinder_qty': cylinder_qty,
                    'm3_per_cylinder': m3_per_cylinder,
                    'rate_with_tax': rate_with_tax,
                    'tax_per_unit': tax_per_unit,
                    'br_rate': br_rate,
                    'rate_per_kg': rate_per_kg,
                    'rate_per_cylinder': rate_per_cylinder,
                    'cylinder_weight': purchase.cylinder_weight,
                    'is_argon': is_argon,
                    'is_lpg': is_lpg,
                    'is_oxygen': is_oxygen,
                    'is_nitrogen': is_nitrogen,
                }
                ledger_entries.append(entry)

            context['ledger_entries'] = ledger_entries
            context['product_name'] = Product.objects.get(id=product_id).name
            context['supplier_name'] = supplier.name
            context['is_argon'] = is_argon
            context['is_lpg'] = is_lpg

            context['total_quantity'] = sum(e['quantity'] for e in ledger_entries if not e['is_bf_row'])
            context['total_subtotal'] = sum(e['subtotal_amount'] for e in ledger_entries if not e['is_bf_row'])
            context['total_tax'] = sum(e['sales_tax_amount'] for e in ledger_entries if not e['is_bf_row'])
            context['total_amount'] = sum(e['total_amount'] for e in ledger_entries if not e['is_bf_row'])
            context['total_paid'] = sum(e['paid_amount'] for e in ledger_entries if not e['is_bf_row'])
            context['final_balance'] = running_balance
            context['total_delivery_charges'] = sum(e['delivery_charges'] for e in ledger_entries if not e['is_bf_row'])
            context['total_extra_charges'] = sum(e['extra_charges'] for e in ledger_entries if not e['is_bf_row'])
            context['total_m3'] = sum(e['total_cubic_meters'] for e in ledger_entries if not e['is_bf_row'])
            context['total_cylinders'] = sum(e['cylinder_qty'] for e in ledger_entries if not e['is_bf_row'])
            
        else:
            context['ledger_entries'] = []
            context['product_name'] = ''
            context['supplier_name'] = ''
            context['is_argon'] = False
            context['is_lpg'] = False
        
        return context

# ============================================================
# API ENDPOINTS FOR PURCHASES
# ============================================================
@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def save_purchase_api(request):
    """API endpoint to save a single purchase entry via AJAX"""
    try:
        data = json.loads(request.body)
        date_str = data.get('date')
        entry_data = data.get('data')
        
        if not entry_data:
            return JsonResponse({'success': False, 'error': 'No data provided'})
        
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().astimezone(PKT).date()
        
        supplier_id = entry_data.get('supplier_id')
        product_id = entry_data.get('product_id')
        quantity = entry_data.get('quantity', 0)  # This is KG
        unit_price = entry_data.get('unit_price', 0)
        delivery_charges = entry_data.get('delivery_charges', 0)
        paid_amount = entry_data.get('paid_amount', 0)
        payment_type = entry_data.get('payment_type', 'cash')
        invoice_no = entry_data.get('invoice_no', '')
        description = entry_data.get('description', '')
        
        # Tax fields
        tax_type = entry_data.get('tax_type', 'none')
        sales_tax_rate = entry_data.get('sales_tax_rate', 0)
        taxable_qty = entry_data.get('taxable_qty', 0)  # User enters this in M³ for Oxygen/Nitrogen
        
        # New fields
        total_m3 = entry_data.get('total_m3', 0)
        cylinder_qty = entry_data.get('cylinder_qty', 0)
        lpg_qty = entry_data.get('lpg_qty', 0)
        cylinder_weight = entry_data.get('cylinder_weight', 0)
        extra_charges = entry_data.get('extra_charges', 0)
        
        if not supplier_id:
            return JsonResponse({'success': False, 'error': 'Supplier is required'})
        if not product_id:
            if float(paid_amount or 0) > 0:
                purchase = Purchase.objects.create(
                    supplier=get_object_or_404(Supplier, pk=supplier_id),
                    product=None,
                    quantity=0,
                    unit_price=0,
                    paid_amount=paid_amount,
                    payment_type=payment_type,
                    invoice_no=(invoice_no or '').strip(),
                    description='Payment Only',
                    purchase_date=selected_date,
                    created_by=request.user,
                )
                return JsonResponse({
                    'success': True,
                    'entry_id': str(purchase.id),
                    'message': 'Supplier payment saved successfully',
                })
            return JsonResponse({'success': False, 'error': 'Payment amount must be greater than 0'})
        if quantity <= 0:
            return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0'})
        
        supplier = get_object_or_404(Supplier, pk=supplier_id)
        product = get_object_or_404(Product, pk=product_id)
        
        # Check product types using helper
        is_argon = is_argon_product(product.name)
        is_lpg = is_lpg_product(product.name)
        is_oxygen = is_oxygen_product(product.name)
        is_nitrogen = is_nitrogen_product(product.name)
        
        # ============================================================
        # 🔥 FIX: Convert Taxable Qty from M³ to KG for Oxygen/Nitrogen
        # ============================================================
        if is_oxygen or is_nitrogen:
            # User entered taxable_qty in M³, convert to KG for split calculation
            conversion_factor = 0.7384 if is_oxygen else 0.844
            taxable_qty_kg = taxable_qty / conversion_factor if conversion_factor > 0 else 0
            print(f"🔵 {product.name}: {taxable_qty} M³ → {taxable_qty_kg} KG")
        else:
            taxable_qty_kg = taxable_qty
        
        # Validate taxable_qty_kg
        if taxable_qty_kg < 0:
            taxable_qty_kg = 0
        if taxable_qty_kg > quantity:
            taxable_qty_kg = quantity
        
        non_taxable_qty = quantity - taxable_qty_kg
        
        print("=" * 60)
        print("🔵 SAVE PURCHASE API")
        print(f"Total Quantity: {quantity} KG")
        print(f"Is Oxygen: {is_oxygen}")
        print(f"Is Nitrogen: {is_nitrogen}")
        print(f"Taxable Qty (user input): {taxable_qty} M³")
        print(f"Taxable Qty (converted to KG): {taxable_qty_kg} KG")
        print(f"Non-Taxable Qty: {non_taxable_qty} KG")
        print("=" * 60)
        
        # ============================================================
        # ✅ FIX: For LPG, use lpg_qty as cylinder_qty
        # ============================================================
        if is_lpg:
            # Use lpg_qty (number of cylinders) as cylinder_qty
            if lpg_qty > 0:
                cylinder_qty = lpg_qty
                print(f"🔵 LPG DETECTED: Cylinder Qty={cylinder_qty}, Weight={cylinder_weight}, Rate per KG={unit_price}")
        
        # For Argon, use total_m3 as the quantity
        if is_argon:
            quantity = total_m3 if total_m3 > 0 else quantity
            if cylinder_qty == 0 and is_argon_product(product.name):
                cylinder_qty = entry_data.get('cylinder_qty', 0) or 0
        
        # ============================================================
        # Use converted taxable_qty_kg for split
        # ============================================================
        # Calculate split ratio using KG values
        split_ratio = taxable_qty_kg / quantity if quantity > 0 else 0
        
        taxable_delivery = delivery_charges * split_ratio
        non_taxable_delivery = delivery_charges - taxable_delivery
        taxable_paid = paid_amount * split_ratio
        non_taxable_paid = paid_amount - taxable_paid
        
        # Calculate Argon-specific split
        taxable_total_m3 = total_m3 * split_ratio if is_argon else 0
        non_taxable_total_m3 = total_m3 - taxable_total_m3 if is_argon else 0
        taxable_cylinder_qty = int(cylinder_qty * split_ratio) if is_argon else 0
        non_taxable_cylinder_qty = cylinder_qty - taxable_cylinder_qty if is_argon else 0
        taxable_lpg_cylinder_qty = round(taxable_qty_kg / cylinder_weight) if is_lpg and cylinder_weight > 0 else 0
        taxable_lpg_cylinder_qty = min(cylinder_qty, max(0, taxable_lpg_cylinder_qty))
        non_taxable_lpg_cylinder_qty = cylinder_qty - taxable_lpg_cylinder_qty if is_lpg else 0

        first_entry_id = None
        entry_group_id = uuid.uuid4()

        # 1. Create TAXABLE portion (using taxable_qty_kg in KG)
        if taxable_qty_kg > 0:
            taxable_purchase = Purchase.objects.create(
                supplier=supplier,
                product=product,
                entry_group_id=entry_group_id,
                quantity=taxable_qty_kg,  # ✅ This is now in KG
                unit_price=unit_price,
                delivery_charges=taxable_delivery,
                paid_amount=taxable_paid,
                payment_type=payment_type,
                invoice_no=invoice_no,
                description=description + " (Taxable)",
                purchase_date=selected_date,
                created_by=request.user,
                tax_type='with_tax',
                sales_tax_rate=sales_tax_rate,
                total_cubic_meters=taxable_total_m3 if is_argon else 0,
                cylinder_qty=(taxable_lpg_cylinder_qty if is_lpg else taxable_cylinder_qty) if (is_lpg or is_argon) else 0,
                cylinder_weight=cylinder_weight if (is_lpg or is_argon) else 0,
                extra_charges=extra_charges * split_ratio if extra_charges else 0,
            )
            first_entry_id = str(taxable_purchase.id)
            print(f"Created TAXABLE: {taxable_qty_kg} KG with tax")

        # 2. Create NON-TAXABLE portion (using non_taxable_qty in KG)
        if non_taxable_qty > 0:
            non_taxable_purchase = Purchase.objects.create(
                supplier=supplier,
                product=product,
                entry_group_id=entry_group_id,
                quantity=non_taxable_qty,  # ✅ This is in KG
                unit_price=unit_price,
                delivery_charges=non_taxable_delivery,
                paid_amount=non_taxable_paid,
                payment_type=payment_type,
                invoice_no=invoice_no,
                description=description + " (Non-Taxable)",
                purchase_date=selected_date,
                created_by=request.user,
                tax_type='none',
                sales_tax_rate=0,
                total_cubic_meters=non_taxable_total_m3 if is_argon else 0,
                cylinder_qty=(non_taxable_lpg_cylinder_qty if is_lpg else non_taxable_cylinder_qty) if (is_lpg or is_argon) else 0,
                cylinder_weight=cylinder_weight if (is_lpg or is_argon) else 0,
                extra_charges=extra_charges - (extra_charges * split_ratio) if extra_charges else 0,
            )
            if not first_entry_id:
                first_entry_id = str(non_taxable_purchase.id)
            print(f"Created NON-TAXABLE: {non_taxable_qty} KG without tax")

        # Update stock with total quantity (KG)
        product.stock_quantity += quantity
        product.save()

        return JsonResponse({
            'success': True,
            'entry_id': first_entry_id,
            'message': 'Purchase saved successfully',
            'taxable_qty_kg': taxable_qty_kg,
            'non_taxable_qty': non_taxable_qty,
            'total_qty': quantity,
            'taxable_qty_m3': taxable_qty,  # Original user input in M³
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})
    
    
@login_required
def get_daily_purchases_api(request):
    """API endpoint to get purchases for a specific date"""
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'purchases': []})
    
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'purchases': []})
    
    purchases = Purchase.objects.filter(purchase_date=date_obj).order_by('created_at')
    
    entries = []
    for purchase in purchases:
        entry_data = {
            'id': str(purchase.id),
            'supplier_id': str(purchase.supplier_id),
            'supplier_name': purchase.supplier.name,
            'product_id': str(purchase.product_id) if purchase.product_id else '',
            'product_name': purchase.product.name if purchase.product_id else 'Payment Only',
            'quantity': float(purchase.quantity),
            'unit_price': float(purchase.unit_price),
            'delivery_charges': float(purchase.delivery_charges),
            'paid_amount': float(purchase.paid_amount),
            'payment_type': purchase.payment_type,
            'invoice_no': purchase.invoice_no or '',
            'description': purchase.description or '',
            'tax_type': purchase.tax_type,
            'sales_tax_rate': float(purchase.sales_tax_rate),
            'subtotal_amount': float(purchase.subtotal_amount),
            'sales_tax_amount': float(purchase.sales_tax_amount),
            'total_amount': float(purchase.total_amount),
            'cubic_meters': float(getattr(purchase, 'cubic_meters', 0)),
        }
        entries.append(entry_data)
    
    return JsonResponse({'purchases': entries})


@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def delete_purchase_api(request):
    """API endpoint to delete a purchase entry"""
    try:
        data = json.loads(request.body)
        entry_id = data.get('entry_id')
        
        if not entry_id:
            return JsonResponse({'success': False, 'error': 'Entry ID is required'})
        
        purchase = get_object_or_404(Purchase, pk=uuid.UUID(entry_id))

        related_purchases = Purchase.objects.filter(entry_group_id=purchase.entry_group_id) if purchase.entry_group_id else Purchase.objects.filter(pk=purchase.pk)
        related_purchases = list(related_purchases.select_related('product'))
        if not request.user.is_superuser and any(row.created_by_id != request.user.pk for row in related_purchases):
            return JsonResponse({'success': False, 'error': 'You do not have permission to delete this purchase'})

        stock_to_restore = {}
        for row in related_purchases:
            if row.product_id:
                stock_to_restore[row.product_id] = stock_to_restore.get(row.product_id, 0) + row.quantity
        for product_id, quantity in stock_to_restore.items():
            product = Product.objects.select_for_update().get(pk=product_id)
            product.stock_quantity -= quantity
            product.save(update_fields=['stock_quantity', 'updated_at'])

        Purchase.objects.filter(pk__in=[row.pk for row in related_purchases]).delete()
        
        return JsonResponse({'success': True, 'message': 'Purchase deleted successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
    
@login_required
@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def update_purchase_api(request):
    """API endpoint to update an existing purchase entry with flexible row handling"""
    try:
        data = json.loads(request.body)
        entry_id = data.get('entry_id')
        entry_data = data.get('data')
        
        if not entry_id or not entry_data:
            return JsonResponse({'success': False, 'error': 'Missing data'})
        
        original_purchase = get_object_or_404(Purchase, pk=uuid.UUID(entry_id))
        
        if original_purchase.created_by and original_purchase.created_by != request.user and not request.user.is_superuser:
            return JsonResponse({'success': False, 'error': 'Permission denied'})
        
        supplier_id = entry_data.get('supplier_id')
        product_id = entry_data.get('product_id')
        total_quantity = entry_data.get('quantity', 0)
        unit_price = entry_data.get('unit_price', 0)
        delivery_charges = entry_data.get('delivery_charges', 0)
        paid_amount = entry_data.get('paid_amount', 0)
        payment_type = entry_data.get('payment_type', 'cash')
        invoice_no = entry_data.get('invoice_no', '')
        description = entry_data.get('description', '')
        tax_type = entry_data.get('tax_type', 'none')
        sales_tax_rate = entry_data.get('sales_tax_rate', 0)
        taxable_qty = entry_data.get('taxable_qty', 0)
        extra_charges = entry_data.get('extra_charges', 0)
        
        # Get purchase date from payload and respect the user’s selected date during edit.
        selected_date = original_purchase.purchase_date
        purchase_date_str = entry_data.get('purchase_date')
        if purchase_date_str:
            try:
                selected_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                selected_date = original_purchase.purchase_date
        
        # Get LPG-specific fields
        total_m3 = entry_data.get('total_m3', 0)
        cylinder_qty = entry_data.get('cylinder_qty', 0) or 0
        cylinder_weight = entry_data.get('cylinder_weight', 0) or 0
        lpg_qty = entry_data.get('lpg_qty', 0) or 0
        
        if not product_id and float(paid_amount or 0) > 0:
            related_purchases = Purchase.objects.filter(entry_group_id=original_purchase.entry_group_id) if original_purchase.entry_group_id else Purchase.objects.filter(pk=original_purchase.pk)
            related_purchases = list(related_purchases.select_related('product'))
            stock_to_restore = {}
            for row in related_purchases:
                if row.product_id:
                    stock_to_restore[row.product_id] = stock_to_restore.get(row.product_id, 0) + row.quantity
            for old_product_id, quantity in stock_to_restore.items():
                old_product = Product.objects.select_for_update().get(pk=old_product_id)
                old_product.stock_quantity -= quantity
                old_product.save(update_fields=['stock_quantity', 'updated_at'])
            for row in related_purchases:
                if row.pk != original_purchase.pk:
                    row.delete()
            original_purchase.supplier = get_object_or_404(Supplier, pk=supplier_id)
            original_purchase.product = None
            original_purchase.quantity = 0
            original_purchase.unit_price = 0
            original_purchase.paid_amount = paid_amount
            original_purchase.payment_type = payment_type
            original_purchase.invoice_no = (invoice_no or '').strip()
            original_purchase.description = description or 'Payment Only'
            original_purchase.purchase_date = selected_date
            original_purchase.save()
            return JsonResponse({'success': True, 'message': 'Supplier payment updated successfully'})

        if total_quantity <= 0:
            return JsonResponse({'success': False, 'error': 'Quantity must be greater than 0'})
        
        supplier = get_object_or_404(Supplier, pk=supplier_id)
        product = get_object_or_404(Product, pk=product_id)
        
        # Check if this is Argon or LPG using helper
        is_argon = is_argon_product(product.name)
        is_lpg = is_lpg_product(product.name)
        
        # ============================================================
        # ✅ FIX: For LPG, use lpg_qty as cylinder_qty if available
        # ============================================================
        if is_lpg:
            if lpg_qty > 0:
                cylinder_qty = lpg_qty
            elif cylinder_qty == 0:
                # Try to get cylinder_qty from existing records
                existing = Purchase.objects.filter(
                    supplier=supplier,
                    product=product,
                    invoice_no=original_purchase.invoice_no,
                    purchase_date=original_purchase.purchase_date
                ).first()
                if existing:
                    cylinder_qty = existing.cylinder_qty or 0
                    cylinder_weight = float(existing.cylinder_weight) if existing.cylinder_weight else 0
        
        print("=" * 60)
        print("🔵 UPDATE PURCHASE API")
        print(f"Entry ID: {entry_id}")
        print(f"Is LPG: {is_lpg}")
        print(f"Cylinder Qty: {cylinder_qty}")
        print(f"Cylinder Weight: {cylinder_weight}")
        print(f"Total Quantity: {total_quantity}")
        print(f"Taxable Qty: {taxable_qty}")
        print("=" * 60)
        
        # ============================================================
        # STEP 1: Find ALL related records (same group)
        # ============================================================
        if not original_purchase.entry_group_id:
            original_purchase.entry_group_id = uuid.uuid4()
            original_purchase.save(update_fields=['entry_group_id'])
        related_purchases = Purchase.objects.filter(
            entry_group_id=original_purchase.entry_group_id,
        ).order_by('created_at')
        
        existing_records = list(related_purchases)
        existing_count = len(existing_records)
        original_created_at = original_purchase.created_at
        
        # ============================================================
        # STEP 2: Restore stock for ALL related records
        # ============================================================
        stock_to_restore = {}
        for p in existing_records:
            if p.product_id:
                stock_to_restore[p.product_id] = stock_to_restore.get(p.product_id, 0) + p.quantity
        for old_product_id, quantity in stock_to_restore.items():
            old_product = Product.objects.select_for_update().get(pk=old_product_id)
            old_product.stock_quantity -= quantity
            old_product.save(update_fields=['stock_quantity', 'updated_at'])
        print(f"Restored stock for {len(existing_records)} grouped purchase row(s)")
        
        # ============================================================
        # STEP 3: Calculate new split
        # ============================================================
        # Validate taxable_qty
        if taxable_qty < 0:
            taxable_qty = 0
        if taxable_qty > total_quantity:
            taxable_qty = total_quantity
        non_taxable_qty = total_quantity - taxable_qty
        
        split_ratio = taxable_qty / total_quantity if total_quantity > 0 else 0
        taxable_delivery = delivery_charges * split_ratio
        non_taxable_delivery = delivery_charges - taxable_delivery
        taxable_paid = paid_amount * split_ratio
        non_taxable_paid = paid_amount - taxable_paid
        taxable_total_m3 = total_m3 * split_ratio if is_argon else 0
        non_taxable_total_m3 = total_m3 - taxable_total_m3 if is_argon else 0
        
        # For LPG, calculate the split quantities for cylinders
        if is_lpg:
            taxable_cylinder_qty = round(taxable_qty / cylinder_weight) if cylinder_weight > 0 else 0
            taxable_cylinder_qty = min(cylinder_qty, max(0, taxable_cylinder_qty))
            non_taxable_cylinder_qty = cylinder_qty - taxable_cylinder_qty
            print(f"LPG Split - Cylinders: Taxable={taxable_cylinder_qty}, Non-Taxable={non_taxable_cylinder_qty}")
        else:
            taxable_cylinder_qty = 0
            non_taxable_cylinder_qty = 0
        
        # ============================================================
        # STEP 4: Delete ALL existing records
        # ============================================================
        for p in existing_records:
            p.delete()
            print(f"Deleted {existing_count} existing records")
        
        # ============================================================
        # STEP 5: Create new records based on split
        # ============================================================
        first_entry_id = None
        new_entries = []
        
        # Create TAXABLE portion
        if taxable_qty > 0:
            p = Purchase(
                supplier=supplier,
                product=product,
                entry_group_id=original_purchase.entry_group_id,
                quantity=taxable_qty,
                unit_price=unit_price,
                delivery_charges=taxable_delivery,
                paid_amount=taxable_paid,
                payment_type=payment_type,
                invoice_no=invoice_no,
                description=description + " (Taxable)",
                purchase_date=selected_date,
                created_by=request.user,
                tax_type='with_tax',
                sales_tax_rate=sales_tax_rate,
                total_cubic_meters=taxable_total_m3 if is_argon else 0,
                cylinder_qty=(taxable_cylinder_qty if is_argon else cylinder_qty) if (is_argon or is_lpg) else 0,
                cylinder_weight=cylinder_weight if (is_argon or is_lpg) else 0,
                extra_charges=extra_charges * split_ratio if extra_charges else 0,
            )
            new_entries.append(p)
            first_entry_id = str(p.id)
            print(f"Created TAXABLE: {taxable_qty} with tax, Cylinder Qty: {p.cylinder_qty}, Weight: {p.cylinder_weight}")
        
        # Create NON-TAXABLE portion
        if non_taxable_qty > 0:
            p = Purchase(
                supplier=supplier,
                product=product,
                entry_group_id=original_purchase.entry_group_id,
                quantity=non_taxable_qty,
                unit_price=unit_price,
                delivery_charges=non_taxable_delivery,
                paid_amount=non_taxable_paid,
                payment_type=payment_type,
                invoice_no=invoice_no,
                description=description + " (Non-Taxable)",
                purchase_date=selected_date,
                created_by=request.user,
                tax_type='none',
                sales_tax_rate=0,
                total_cubic_meters=non_taxable_total_m3 if is_argon else 0,
                cylinder_qty=(non_taxable_cylinder_qty if is_argon else cylinder_qty) if (is_argon or is_lpg) else 0,
                cylinder_weight=cylinder_weight if (is_argon or is_lpg) else 0,
                extra_charges=extra_charges - (extra_charges * split_ratio) if extra_charges else 0,
            )
            new_entries.append(p)
            if not first_entry_id:
                first_entry_id = str(p.id)
            print(f"Created NON-TAXABLE: {non_taxable_qty} without tax, Cylinder Qty: {p.cylinder_qty}, Weight: {p.cylinder_weight}")
        
        # Save all with same created_at to preserve order
        for entry in new_entries:
            entry.created_at = original_created_at
            entry.save()
            print(f"  Saved: {entry.purchase_no} - Quantity: {entry.quantity}, Tax: {entry.tax_type}, Rate: {entry.unit_price}")
        
        # ============================================================
        # STEP 6: Update stock with new total quantity
        # ============================================================
        product = Product.objects.select_for_update().get(pk=product.pk)
        product.stock_quantity += total_quantity
        product.save()
        print(f"Updated stock: +{total_quantity} units")
        print(f"Update complete! New records: {len(new_entries)}")
        print("=" * 60)
        
        return JsonResponse({
            'success': True,
            'entry_id': first_entry_id,
            'message': 'Purchase updated successfully!',
            'old_count': existing_count,
            'new_count': len(new_entries)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})
    
    
    
@login_required
def get_supplier_history_api(request):
    """Return recent purchase and payment-only records for the selected supplier."""
    supplier_id = request.GET.get('supplier_id')
    if not supplier_id:
        return JsonResponse({'supplier': {}, 'records': []})

    try:
        supplier = Supplier.objects.get(pk=supplier_id)
    except Supplier.DoesNotExist:
        return JsonResponse({'supplier': {}, 'records': []})

    purchases = Purchase.objects.filter(supplier_id=supplier_id).order_by('-purchase_date', '-created_at')[:25]
    records = []
    total_paid = 0
    total_amount = 0

    for purchase in purchases:
        product_name = purchase.product.name if purchase.product_id else 'Payment Only'
        amount = float(purchase.subtotal_amount) + float(purchase.sales_tax_amount) if purchase.product_id else 0
        paid = float(purchase.paid_amount or 0)
        total_paid += paid
        total_amount += amount

        records.append({
            'id': str(purchase.id),
            'date': purchase.purchase_date.isoformat(),
            'purchase_no': purchase.purchase_no,
            'invoice_no': purchase.invoice_no or '',
            'product_name': product_name,
            'paid_amount': float(paid),
            'amount': float(amount),
            'payment_type': purchase.payment_type,
            'description': purchase.description or ('Payment Only' if not purchase.product_id else ''),
            'is_payment_only': purchase.product_id is None,
        })

    return JsonResponse({
        'supplier': {
            'id': str(supplier.id),
            'name': supplier.name,
            'code': supplier.supplier_code,
            'mobile': supplier.mobile or '',
        },
        'summary': {
            'records_count': len(records),
            'total_paid': float(total_paid),
            'total_amount': float(total_amount),
        },
        'records': records,
    })


@login_required
def get_purchase_details_api(request):
    """API to fetch a single purchase entry for editing"""
    entry_id = request.GET.get('id')
    if not entry_id:
        return JsonResponse({'error': 'Missing ID'}, status=400)
    
    try:
        purchase = Purchase.objects.get(pk=uuid.UUID(entry_id))

        product_id = str(purchase.product_id) if purchase.product_id else ''
        related = Purchase.objects.filter(entry_group_id=purchase.entry_group_id).order_by('created_at')
        if not purchase.entry_group_id:
            related = Purchase.objects.filter(pk=purchase.pk)
        
        total_qty = sum(float(p.quantity) for p in related)
        total_taxable_qty = 0
        total_paid = sum(float(p.paid_amount) for p in related)
        total_delivery = sum(float(p.delivery_charges) for p in related)
        total_extra = sum(float(p.extra_charges) for p in related)
        
        for p in related:
            if p.tax_type == 'with_tax':
                total_taxable_qty += float(p.quantity)
        
        first_row = related.first()
        
        clean_description = purchase.description or ''
        clean_description = clean_description.replace(" (Taxable)", "").replace(" (Non-Taxable)", "").strip()

        is_argon = False
        is_lpg = False
        total_cubic_meters = float(purchase.total_cubic_meters) if purchase.total_cubic_meters else 0
        cylinder_qty = purchase.cylinder_qty if purchase.cylinder_qty else 0
        cylinder_weight = float(purchase.cylinder_weight) if purchase.cylinder_weight else 0
        unit_price = float(purchase.unit_price) if purchase.unit_price else 0

        product = purchase.product
        if product:
            is_argon = is_argon_product(product.name)
            is_lpg = is_lpg_product(product.name)

        # For LPG, use the cylinder_qty and cylinder_weight from the first record
        if is_lpg:
            for p in related:
                if p.cylinder_qty > 0:
                    cylinder_qty = p.cylinder_qty
                    cylinder_weight = float(p.cylinder_weight) if p.cylinder_weight else 0
                    break
            unit_price = float(purchase.unit_price) if purchase.unit_price else 0
        
        data = {
            'id': str(purchase.id),
            'supplier_id': str(purchase.supplier_id),
            'product_id': product_id,
            'purchase_date': purchase.purchase_date.isoformat(),
            'quantity': float(total_qty),
            'taxable_qty': float(total_taxable_qty),
            'unit_price': unit_price,
            'delivery_charges': float(total_delivery),
            'extra_charges': float(total_extra),
            'paid_amount': float(total_paid),
            'payment_type': purchase.payment_type,
            'invoice_no': purchase.invoice_no or '',
            'description': clean_description,
            'tax_type': first_row.tax_type if first_row else 'none',
            'sales_tax_rate': float(first_row.sales_tax_rate) if first_row else 0,
            'total_m3': total_cubic_meters if is_argon else 0,
            'cylinder_qty': cylinder_qty if (is_argon or is_lpg) else 0,
            'cylinder_weight': cylinder_weight if (is_argon or is_lpg) else 0,
            'is_argon': is_argon,
            'is_lpg': is_lpg,
        }
        return JsonResponse(data)
        
    except Purchase.DoesNotExist:
        return JsonResponse({'error': 'Purchase not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def get_ledger_suppliers_api(request):
    """API to get suppliers that supply a specific product"""
    product_id = request.GET.get('product')
    if not product_id:
        return JsonResponse({'suppliers': []})
    
    supplier_ids = Purchase.objects.filter(product_id=product_id).values_list('supplier_id', flat=True).distinct()
    suppliers = Supplier.objects.filter(id__in=supplier_ids).order_by('name')
    
    data = [{'id': str(s.id), 'name': s.name} for s in suppliers]
    return JsonResponse({'suppliers': data})


@login_required
def get_ledger_products_api(request):
    """API to get products that a specific supplier supplies"""
    supplier_id = request.GET.get('supplier')
    if not supplier_id:
        return JsonResponse({'products': []})
    
    product_ids = Purchase.objects.filter(supplier_id=supplier_id).values_list('product_id', flat=True).distinct()
    products = Product.objects.filter(id__in=product_ids).order_by('name')
    
    data = [{'id': str(p.id), 'name': p.name} for p in products]
    return JsonResponse({'products': data})