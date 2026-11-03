from django.urls import path
from . import views

app_name = 'earnings'

urlpatterns = [
    path('', views.earning_dashboard, name='dashboard'),
    path('api/details/', views.get_earning_details, name='get_details'),
    path('api/expense/add/', views.add_expense, name='add_expense'),
    path('api/expense/add-bulk/', views.add_expenses_bulk, name='add_expenses_bulk'),
    path('api/expense/delete/<int:expense_id>/', views.delete_expense, name='delete_expense'),
    path('api/opening-balance/save/', views.save_opening_balance, name='save_opening_balance'),
    path('api/opening-balance/delete/', views.delete_opening_balance, name='delete_opening_balance'),
    path('api/partner-account/add/', views.add_partner_account, name='add_partner_account'),
    path('api/partner-account/update/<int:account_id>/', views.update_partner_account, name='update_partner_account'),
    path('api/partner-account/delete/<int:account_id>/', views.delete_partner_account, name='delete_partner_account'),
]