from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.NotificationListView.as_view(), name='list'),
    path('mark-read/<uuid:pk>/', views.MarkNotificationReadView.as_view(), name='mark_read'),
    path('mark-all-read/', views.MarkAllNotificationsReadView.as_view(), name='mark_all_read'),
    path('delete/<uuid:pk>/', views.DeleteNotificationView.as_view(), name='delete'),
    path('delete-all/', views.DeleteAllNotificationsView.as_view(), name='delete_all'),
    path('delete-read/', views.DeleteReadNotificationsView.as_view(), name='delete_read'),
    path('run-checks/', views.RunDailyChecksView.as_view(), name='run_checks'),
    path('backup/', views.BackupNowView.as_view(), name='backup_now'),
    path('backup/download/', views.BackupDownloadView.as_view(), name='backup_download'),
    path('count/', views.GetNotificationCountView.as_view(), name='count'),
    path('settings/', views.NotificationSettingsView.as_view(), name='settings'),
]