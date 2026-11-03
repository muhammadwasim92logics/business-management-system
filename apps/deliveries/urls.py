from django.urls import path
from . import views

app_name = 'deliveries'

urlpatterns = [
    path('', views.DeliveryListView.as_view(), name='list'),
    path('add/', views.DeliveryCreateView.as_view(), name='add'),
    path('daily/', views.DailyEntryView.as_view(), name='daily_entry'),
    path('daily/payment/', views.PaymentOnlyView.as_view(), name='payment_only'),
    path('daily/get-customer-balance/', views.get_customer_balance, name='get_customer_balance'),
    path('validate-stock/', views.validate_stock, name='validate_stock'),
    
    # CRUD API endpoints for AJAX operations
    path('api/save-entry/', views.save_entry_api, name='save_entry_api'),
    path('api/update-entry/', views.update_entry_api, name='update_entry_api'),
    path('api/delete-entry/', views.delete_entry_api, name='delete_entry_api'),
    path('api/daily-entries/', views.get_daily_entries_api, name='get_daily_entries_api'),
    path('api/clear-entries/', views.clear_entries_api, name='clear_entries_api'),
    path('api/save-payment/', views.save_payment_api, name='save_payment_api'),
]