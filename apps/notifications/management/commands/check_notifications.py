from django.core.management.base import BaseCommand
from apps.notifications.services import NotificationService

class Command(BaseCommand):
    help = 'Run daily notification checks'
    
    def handle(self, *args, **options):
        self.stdout.write('Running daily notification checks...')
        notifications = NotificationService.run_daily_checks()
        self.stdout.write(
            self.style.SUCCESS(f'Created {len(notifications)} notifications')
        )