from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(pattern_name='dashboard:index', permanent=False)),
    path('auth/', include('apps.accounts.urls', namespace='accounts')),
    path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),
    path('customers/', include('apps.customers.urls', namespace='customers')),
    path('products/', include('apps.products.urls', namespace='products')),
    path('deliveries/', include('apps.deliveries.urls', namespace='deliveries')),
    path('payments/', include('apps.payments.urls', namespace='payments')),
    path('cylinders/', include('apps.cylinders.urls', namespace='cylinders')),
    path('notifications/', include('apps.notifications.urls', namespace='notifications')),
    path('fbr/', include('apps.fbr.urls', namespace='fbr')),
    path('suppliers/', include('apps.suppliers.urls', namespace='suppliers')),
    path('earnings/', include('apps.earnings.urls')),  # ✅ CORRECT
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)