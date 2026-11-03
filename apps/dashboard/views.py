from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.db.models import Sum
from django.db import models
from datetime import datetime, timedelta
from django.utils import timezone
from apps.customers.models import Customer
from apps.products.models import Product
from apps.deliveries.models import Delivery
from apps.payments.models import Payment
from apps.notifications.models import NotificationSettings

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/index.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        notification_settings = NotificationSettings.get_solo()
        inactive_days = max(1, (notification_settings.inactive_customer_after_hours + 23) // 24)
        not_coming_days = max(1, (notification_settings.not_coming_customer_after_hours + 23) // 24)
        week_ago = today - timedelta(days=inactive_days)
        month_ago = today - timedelta(days=30)
        
        # Get all customers
        all_customers = Customer.objects.all()
        
        # Calculate statuses based on last_activity_date
        active_customers = []
        inactive_customers = []
        not_coming_customers = []
        
        for customer in all_customers:
            last_activity = customer.last_activity_date or customer.registration_date or today
            days_inactive = (today - last_activity).days
            
            if days_inactive * 24 >= notification_settings.not_coming_customer_after_hours:
                not_coming_customers.append(customer)
            elif days_inactive * 24 >= notification_settings.inactive_customer_after_hours:
                inactive_customers.append(customer)
            else:
                active_customers.append(customer)
        
        context['total_customers'] = all_customers.count()
        context['active_customers'] = len(active_customers)
        context['inactive_customers'] = len(inactive_customers)
        context['not_coming_customers'] = len(not_coming_customers)
        
        # Today's deliveries
        today_deliveries = Delivery.objects.filter(delivery_date=today)
        context['today_deliveries_count'] = today_deliveries.count()
        context['today_deliveries_amount'] = today_deliveries.aggregate(total=Sum('delivery_amount'))['total'] or 0
        
        # Weekly and monthly sales
        context['weekly_sales'] = Delivery.objects.filter(delivery_date__gte=week_ago).aggregate(total=Sum('delivery_amount'))['total'] or 0
        context['monthly_sales'] = Delivery.objects.filter(delivery_date__gte=month_ago).aggregate(total=Sum('delivery_amount'))['total'] or 0
        
        # Pending amount
        total_billed = Delivery.objects.aggregate(total=Sum('delivery_amount'))['total'] or 0
        total_paid = Payment.objects.aggregate(total=Sum('amount'))['total'] or 0
        opening_balances = Customer.objects.aggregate(
            total_bf=Sum('bf_balance'),
            total_previous=Sum('previous_balance'),
        )
        context['pending_amount'] = (
            total_billed
            - total_paid
            + (opening_balances['total_bf'] or 0)
            + (opening_balances['total_previous'] or 0)
        )
        context['total_orders'] = Delivery.objects.count()
        
        # Low stock products
        context['low_stock_products'] = Product.objects.filter(
            stock_quantity__lte=models.F('minimum_stock')
        ).order_by('stock_quantity')[:10]
        
        # Recent deliveries
        context['recent_deliveries'] = Delivery.objects.all().order_by('-created_at')[:10]
        context['recent_payments'] = Payment.objects.all().order_by('-created_at')[:10]
        
        # 14-day sales chart data
        chart_start = today - timedelta(days=13)
        cylinder_sales = Delivery.objects.filter(
            delivery_date__range=(chart_start, today),
            product__is_quantity_only=False,
            product__is_filling_only=False,
        ).values('product__name').annotate(
            delivered=Sum('quantity'),
            total_full_returned=Sum('full_returned'),
            net_sold=Sum('quantity') - Sum('full_returned'),
        ).order_by('-net_sold', 'product__name')
        context['cylinder_sales'] = cylinder_sales

        sales_data = []
        for i in range(13, -1, -1):
            date = today - timedelta(days=i)
            daily_total = Delivery.objects.filter(delivery_date=date).aggregate(
                total=Sum('delivery_amount')
            )['total'] or 0
            sales_data.append({
                'date': date.strftime('%d %b'),
                'total': float(daily_total)
            })
        context['sales_chart_data'] = sales_data
        
        return context