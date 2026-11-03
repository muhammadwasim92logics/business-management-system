from django.urls import path
from . import views

app_name = 'fbr'

urlpatterns = [
    path('', views.FBRLedgerView.as_view(), name='ledger'),
    path('ledger/delivery/<uuid:pk>/delete/', views.DeleteFBRDeliveryView.as_view(), name='delete_ledger_delivery'),
    path('invoices/', views.FBRInvoicesView.as_view(), name='invoices'),
    path('invoices/manage-numbers/', views.ManageFBRInvoiceNumbersView.as_view(), name='manage_invoice_numbers'),
    path('api/save-selected-customers/', views.SaveFBRSelectedCustomersView.as_view(), name='save_selected_customers'),
    path('api/save-customer-setting/', views.SaveFBRCustomerSettingView.as_view(), name='save_customer_setting'),
]