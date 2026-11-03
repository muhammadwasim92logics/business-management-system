from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='list'),
    path('add/', views.ProductCreateView.as_view(), name='add'),
    path('stock-details/', views.StockDetailsView.as_view(), name='stock_details'),
    path('stock-overview/', views.StockOverviewView.as_view(), name='stock_overview'),
    path('stock-details/opening-balance/save/', views.save_stock_opening_balance, name='save_stock_opening_balance'),
    path('factory-fill/', views.FactoryFillView.as_view(), name='factory_fill'),
    path('factory-fill/stock/', views.factory_product_stock_api, name='factory_product_stock'),
    path('factory-fill/<uuid:pk>/edit/', views.FactoryFillUpdateView.as_view(), name='factory_fill_edit'),
    path('factory-fill/<uuid:pk>/delete/', views.FactoryFillDeleteView.as_view(), name='factory_fill_delete'),
    path('factory-fill/<uuid:pk>/', views.FactoryDetailView.as_view(), name='factory_detail'),
    path('<uuid:pk>/edit/', views.ProductUpdateView.as_view(), name='edit'),
    path('<uuid:pk>/delete/', views.ProductDeleteView.as_view(), name='delete'),
    path('<uuid:pk>/stock/', views.product_stock_api, name='stock_api'),
]