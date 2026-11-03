from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone
from .models import Payment
from .forms import PaymentForm
from apps.customers.models import Customer

class PaymentListView(LoginRequiredMixin, ListView):
    model = Payment
    template_name = 'payments/list.html'
    context_object_name = 'payments'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        customer_id = self.request.GET.get('customer')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset

class PaymentCreateView(LoginRequiredMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = 'payments/receive.html'
    
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
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Receive Payment'
        
        customer_id = self.request.GET.get('customer')
        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
                context['selected_customer'] = customer
                context['customer_name'] = customer.name
                context['customer_code'] = customer.customer_code
                context['customer_balance'] = customer.get_outstanding_balance()
            except Customer.DoesNotExist:
                pass
        
        return context
    
    def form_valid(self, form):
        with transaction.atomic():
            form.instance.created_by = self.request.user
            response = super().form_valid(form)
            
            customer = form.cleaned_data['customer']
            customer.last_activity_date = timezone.now().date()
            customer.save(update_fields=['last_activity_date', 'updated_at'])
            
            messages.success(self.request, f'Payment {self.object.payment_no} recorded successfully!')
            
            # Check if we should redirect back to customer profile
            if self.request.GET.get('customer'):
                return redirect('customers:detail', pk=customer.pk)
            
            return response
    
    def get_success_url(self):
        if self.request.GET.get('customer'):
            return reverse_lazy('customers:detail', kwargs={'pk': self.request.GET.get('customer')})
        return reverse_lazy('payments:list')