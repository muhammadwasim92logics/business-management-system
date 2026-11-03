from django.urls import path
from . import views

app_name = 'cylinders'

urlpatterns = [
    path('', views.CylinderDashboardView.as_view(), name='dashboard'),
    path('ledger/', views.CylinderLedgerView.as_view(), name='ledger'),
]