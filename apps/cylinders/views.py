from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, ListView
from django.db.models import Q, Sum
from apps.products.models import Product
from apps.customers.models import Customer
from apps.deliveries.models import Delivery
from apps.cylinders.models import CylinderLedger
from django.utils import timezone

# ============================================================
# DASHBOARD VIEW (With Category Filter)
# ============================================================
# ============================================================
# DASHBOARD VIEW (With Category Filter)
# ============================================================
class CylinderDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'cylinders/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Get selected category from URL
        selected_category = self.request.GET.get('category', '')
        selected_product_id = self.request.GET.get('product', '')
        
        # 2. Get distinct categories for the dropdown
        categories = Product.objects.exclude(category__isnull=True).exclude(category='').values_list('category', flat=True).distinct()
        
        # 3. Filter products by category
        if selected_product_id:
            products = Product.objects.filter(pk=selected_product_id, is_quantity_only=False)
        elif selected_category:
            products = Product.objects.filter(category=selected_category, is_quantity_only=False)
        else:
            products = Product.objects.filter(is_quantity_only=False)

        # 4. Calculate stats based on these filtered products
        # In-shop cylinders
        filled_cylinders = products.aggregate(total=Sum('stock_quantity'))['total'] or 0
        empty_cylinders = products.aggregate(total=Sum('empty_stock_quantity'))['total'] or 0
        in_shop_total = filled_cylinders + empty_cylinders
        products = list(products)
        product_ids = [product.pk for product in products]
        
        # Aggregate ledger movements once instead of querying every customer/product pair.
        customers = list(Customer.objects.only('id', 'name', 'customer_code', 'bf_cylinders'))
        ledger_totals = {}
        ownership_totals = {}
        if product_ids:
            ledger_totals = {
                (entry['customer_id'], entry['product_id']): entry
                for entry in CylinderLedger.objects.filter(product_id__in=product_ids)
                .exclude(notes__startswith='B.F (Bring Forward)')
                .values('customer_id', 'product_id')
                .annotate(total_taken=Sum('full_out'), total_returned=Sum('empty_in'))
            }
            ownership_totals = {
                (entry['customer_id'], entry['product_id']): entry
                for entry in CylinderLedger.objects.filter(
                    product_id__in=product_ids,
                    ownership_movement__in=('customer_received', 'customer_returned'),
                ).values('customer_id', 'product_id').annotate(
                    received=Sum(
                        'ownership_quantity',
                        filter=Q(ownership_movement='customer_received'),
                    ),
                    returned=Sum(
                        'ownership_quantity',
                        filter=Q(ownership_movement='customer_returned'),
                    ),
                )
            }

        def bring_forward_quantity(customer, product):
            return sum(
                int(quantity or 0)
                for name, quantity in (customer.bf_cylinders or {}).items()
                if str(name).strip().upper() == product.name.strip().upper()
            )

        # 5. Customer Cylinder Data (Filtered by Category or Product)
        customer_cylinder_data = []
        customer_net_by_product = {product.pk: 0 for product in products}
        customer_owned_data = []
        owned_by_product = {product.pk: 0 for product in products}
        for customer in customers:
            for product in products:
                pair = (customer.pk, product.pk)
                totals = ledger_totals.get(pair, {})
                total_taken = totals.get('total_taken') or 0
                total_returned = totals.get('total_returned') or 0
                bf_quantity = bring_forward_quantity(customer, product)
                net_cylinders = total_taken - total_returned + bf_quantity
                customer_net_by_product[product.pk] += net_cylinders

                if net_cylinders > 0:
                    customer_cylinder_data.append({
                        'customer': customer,
                        'product': product,
                        'net_cylinders': net_cylinders,
                        'total_taken': total_taken,
                        'total_returned': total_returned,
                        'bring_forward': bf_quantity,
                    })

                ownership = ownership_totals.get(pair, {})
                received = ownership.get('received') or 0
                returned = ownership.get('returned') or 0
                holding = received - returned
                if holding > 0:
                    owned_by_product[product.pk] += holding
                    customer_owned_data.append({
                        'customer': customer,
                        'product': product,
                        'quantity': holding,
                    })
        
        # Total cylinders with customers
        cylinders_with_customers = sum(item['net_cylinders'] for item in customer_cylinder_data)

        customer_owned_in_shop = sum(item['quantity'] for item in customer_owned_data)
        
        # 6. Calculate TOTAL cylinders (in shop + with customers)
        total_cylinders = in_shop_total + cylinders_with_customers
        
        # 7. Product-wise Breakdown
        product_breakdown = []
        for product in products:
            product_totals = [
                totals for (customer_id, product_id), totals in ledger_totals.items()
                if product_id == product.pk
            ]
            full_out = sum(totals.get('total_taken') or 0 for totals in product_totals)
            empty_in = sum(totals.get('total_returned') or 0 for totals in product_totals)
            customer_net = customer_net_by_product[product.pk]
            expected_total = product.opening_full_quantity + product.opening_empty_quantity
            accounted_total = product.stock_quantity + product.empty_stock_quantity + customer_net
            product_breakdown.append({
                'product': product,
                'stock': product.stock_quantity,
                'empty_stock': product.empty_stock_quantity,
                'delivered': full_out,
                'returned': empty_in,
                'net_with_customers': full_out - empty_in,
                'with_customers': customer_net,
                'expected_total': expected_total,
                'accounted_total': accounted_total,
                'shortage': max(expected_total - accounted_total, 0),
                'customer_owned_in_shop': owned_by_product[product.pk],
            })
        
        # 8. Today's activity (Filtered)
        today = timezone.now().date()
        today_entries = CylinderLedger.objects.filter(transaction_date=today, product_id__in=product_ids)
        today_filled = today_entries.aggregate(total=Sum('full_out'))['total'] or 0
        today_empty = today_entries.aggregate(total=Sum('empty_in'))['total'] or 0
        
        # Calculate shortage
        shortage_cylinders = sum(item['shortage'] for item in product_breakdown)
        accounted_cylinders = in_shop_total + cylinders_with_customers
        
        context.update({
            'categories': categories,
            'selected_category': selected_category,
            'selected_product_id': selected_product_id,
            'product_options': Product.objects.filter(is_quantity_only=False),
            'total_cylinders': total_cylinders,  # ALL cylinders (in shop + with customers)
            'physical_total': total_cylinders + customer_owned_in_shop,
            'in_shop_total': in_shop_total,      # NEW: cylinders in shop
            'filled_cylinders': filled_cylinders,
            'empty_cylinders': empty_cylinders,
            'cylinders_with_customers': cylinders_with_customers,
            'customer_owned_data': customer_owned_data,
            'customer_owned_in_shop': customer_owned_in_shop,
            'accounted_cylinders': accounted_cylinders,
            'shortage_cylinders': shortage_cylinders,
            'customer_cylinder_data': customer_cylinder_data,
            'product_breakdown': product_breakdown,
            'today_filled': today_filled,
            'today_empty': today_empty,
            'total_products': len(products),
            'total_customers': len(customers),
        })
        
        return context


# ============================================================
# LEDGER VIEW
# ============================================================
class CylinderLedgerView(LoginRequiredMixin, ListView):
    model = CylinderLedger
    template_name = 'cylinders/ledger.html'
    context_object_name = 'entries'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        customer_id = self.request.GET.get('customer')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Cylinder Ledger'
        return context