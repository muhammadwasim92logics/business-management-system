from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, View
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .models import Notification, NotificationSettings
from .forms import NotificationSettingsForm
from .services import BackupService, NotificationService

class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'notifications/list.html'
    context_object_name = 'notifications'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status', '')
        notification_type = self.request.GET.get('type', '')
        
        if status:
            queryset = queryset.filter(status=status)
        if notification_type:
            queryset = queryset.filter(type=notification_type)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        NotificationService.check_backup_reminder()
        context = super().get_context_data(**kwargs)
        context['unread_count'] = Notification.objects.filter(status=Notification.Status.UNREAD).count()
        context['total_count'] = Notification.objects.count()
        context['read_count'] = Notification.objects.filter(status=Notification.Status.READ).count()
        context['types'] = Notification.Type.choices
        context['current_type'] = self.request.GET.get('type', '')
        context['current_status'] = self.request.GET.get('status', '')
        return context

class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        notification.mark_as_read()
        
        # Also mark any other notifications for the same customer/type as read
        if notification.customer and notification.type:
            Notification.objects.filter(
                customer=notification.customer,
                type=notification.type,
                status=Notification.Status.UNREAD
            ).exclude(pk=notification.pk).update(
                status=Notification.Status.READ,
                updated_at=timezone.now()
            )
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        
        messages.success(request, 'Notification marked as read.')
        return redirect('notifications:list')

class MarkAllNotificationsReadView(LoginRequiredMixin, View):
    def post(self, request):
        count = Notification.objects.filter(status=Notification.Status.UNREAD).count()
        Notification.objects.filter(status=Notification.Status.UNREAD).update(
            status=Notification.Status.READ,
            updated_at=timezone.now()
        )
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'count': count})
        
        messages.success(request, f'{count} notifications marked as read.')
        return redirect('notifications:list')

class DeleteNotificationView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk)
        notification.delete()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        
        messages.success(request, 'Notification deleted successfully.')
        return redirect('notifications:list')

class DeleteAllNotificationsView(LoginRequiredMixin, View):
    def post(self, request):
        count = Notification.objects.count()
        
        # Delete all notifications
        Notification.objects.all().delete()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'count': count})
        
        messages.success(request, f'{count} notifications deleted successfully.')
        return redirect('notifications:list')

class DeleteReadNotificationsView(LoginRequiredMixin, View):
    def post(self, request):
        count = Notification.objects.filter(status=Notification.Status.READ).count()
        Notification.objects.filter(status=Notification.Status.READ).delete()
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'count': count})
        
        messages.success(request, f'{count} read notifications deleted successfully.')
        return redirect('notifications:list')

class RunDailyChecksView(LoginRequiredMixin, View):
    def post(self, request):
        # First, mark old notifications as read (they're no longer relevant)
        # Only keep notifications from today as unread
        today = timezone.now().date()
        old_unread = Notification.objects.filter(
            status=Notification.Status.UNREAD,
            created_at__date__lt=today
        )
        old_count = old_unread.count()
        old_unread.update(status=Notification.Status.READ, updated_at=timezone.now())

        # Run checks for new notifications
        notifications = NotificationService.run_daily_checks()

        message = f'Daily checks completed. {len(notifications)} new notifications created.'
        if old_count > 0:
            message += f' {old_count} old notifications marked as read.'
        messages.success(request, message)
        return redirect('notifications:list')

class BackupNowView(LoginRequiredMixin, View):
    def post(self, request):
        result = BackupService.send_daily_backup(request.user)
        if result['sent']:
            messages.success(request, result['message'], extra_tags='backup-result')
        else:
            messages.warning(request, result['message'], extra_tags='backup-result')
        return redirect('notifications:list')


class BackupDownloadView(LoginRequiredMixin, View):
    def post(self, request):
        result = BackupService.create_local_backup()
        if not result['success']:
            return JsonResponse({
                'success': False,
                'message': result['message'],
            }, status=500)

        response = HttpResponse(result['content'], content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{result["filename"]}"'
        response['Content-Length'] = len(result['content'])
        return response


class GetNotificationCountView(LoginRequiredMixin, View):
    def get(self, request):
        NotificationService.check_backup_reminder()
        count = Notification.objects.filter(status=Notification.Status.UNREAD).count()
        return JsonResponse({'count': count})


class NotificationSettingsView(LoginRequiredMixin, View):
    template_name = 'notifications/settings.html'

    def get(self, request):
        form = NotificationSettingsForm(instance=NotificationSettings.get_solo())
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        settings = NotificationSettings.get_solo()
        form = NotificationSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notification settings saved.')
            return redirect('notifications:settings')
        return render(request, self.template_name, {'form': form})