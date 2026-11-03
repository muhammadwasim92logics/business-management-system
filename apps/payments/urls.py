from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.PaymentListView.as_view(), name='list'),
    path('receive/', views.PaymentCreateView.as_view(), name='receive'),
]