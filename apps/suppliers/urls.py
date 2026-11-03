from django.urls import path
from . import views

app_name = 'suppliers'

urlpatterns = [
    # Main views
    path('', views.SupplierListView.as_view(), name='list'),
    path('add/', views.SupplierCreateView.as_view(), name='add'),
    path('edit/<uuid:pk>/', views.SupplierUpdateView.as_view(), name='edit'),
    path('delete/<uuid:pk>/', views.SupplierDeleteView.as_view(), name='delete'),
    path('purchase-entry/', views.PurchaseEntryView.as_view(), name='purchase_entry'),
    path('ledger/', views.SupplierProductLedgerView.as_view(), name='ledger'),

    # ============================================================
    # API ENDPOINTS FOR PURCHASES (AJAX)
    # ============================================================

    # Get supplier activity/history when choosing a supplier on the purchase form
    path('api/supplier-history/', views.get_supplier_history_api, name='supplier_history_api'),

    # Save a single purchase entry via AJAX
    path('api/save-purchase/', views.save_purchase_api, name='save_purchase_api'),
    
    # Get daily purchases for a specific date
    path('api/daily-purchases/', views.get_daily_purchases_api, name='get_daily_purchases_api'),
    
    # Delete a purchase entry
    path('api/delete-purchase/', views.delete_purchase_api, name='delete_purchase_api'),
    
    # Update a purchase entry (supports 1→2, 2→1, 1→1, 2→2)
    path('api/update-purchase/', views.update_purchase_api, name='update_purchase_api'),
    
    # Get purchase details for editing
    path('api/get-purchase-details/', views.get_purchase_details_api, name='get_purchase_details_api'),
    
    # Get products that a specific supplier supplies
    path('api/ledger-products/', views.get_ledger_products_api, name='get_ledger_products_api'),
    
    # Get suppliers that supply a specific product
    path('api/ledger-suppliers/', views.get_ledger_suppliers_api, name='get_ledger_suppliers_api'),
]