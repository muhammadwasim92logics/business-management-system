from django.urls import path
from . import views

app_name = 'customers'

urlpatterns = [
    path('', views.CustomerListView.as_view(), name='list'),
    path('print/', views.CustomerPrintView.as_view(), name='print'),
    path('create/', views.CustomerCreateView.as_view(), name='create'),
    path('add/', views.CustomerCreateView.as_view(), name='add'),
    path('<uuid:pk>/delete/', views.delete_customer, name='delete'),
    path('<uuid:pk>/', views.CustomerDetailView.as_view(), name='detail'),
    path('<uuid:pk>/edit/', views.CustomerUpdateView.as_view(), name='edit'),
    path('<uuid:pk>/update-bf/', views.update_bf, name='update_bf'),
    path('ledger/', views.CustomerLedgerView.as_view(), name='ledger'),
    path('bf-setup/', views.bf_setup, name='bf_setup'),
    path('api/save-bf-customer/', views.save_bf_customer_api, name='save_bf_customer_api'),
]