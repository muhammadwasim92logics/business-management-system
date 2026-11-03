import json
import io
import smtplib
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from apps.notifications.models import Notification, NotificationSettings


class BackupService:
    @staticmethod
    def get_backup_dir():
        project_root = Path(settings.BASE_DIR)
        backup_dir = project_root / 'backups'
        backup_dir.mkdir(exist_ok=True)
        return backup_dir

    @staticmethod
    def _create_backup_payload():
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        db_path = Path(settings.BASE_DIR) / 'db.sqlite3'
        media_dir = Path(settings.BASE_DIR) / 'media'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            if db_path.exists():
                archive.write(db_path, arcname='db.sqlite3')

            if media_dir.exists():
                for file_path in media_dir.rglob('*'):
                    if file_path.is_file():
                        archive.write(file_path, arcname=str(file_path.relative_to(settings.BASE_DIR)))

            metadata = {
                'backup_created_at': timezone.now().isoformat(),
                'database_name': 'db.sqlite3',
                'app_name': 'GBMS',
                'project_root': str(settings.BASE_DIR),
            }
            archive.writestr('backup_metadata.json', json.dumps(metadata, indent=2, default=str))

        return f'gbms_backup_{timestamp}.zip', buffer.getvalue()

    @staticmethod
    def is_backup_sent_today(user):
        today = timezone.now().date()
        return Notification.objects.filter(
            type=Notification.Type.BACKUP_SENT,
            created_at__date=today
        ).exists()

    @staticmethod
    def send_daily_backup(user):
        if BackupService.is_backup_sent_today(user):
            return {
                'sent': False,
                'message': 'Backup file has already been sent for today. Please try again tomorrow.'
            }

        try:
            backup_name, backup_content = BackupService._create_backup_payload()
        except (OSError, RuntimeError, TypeError, ValueError, zipfile.LargeZipFile) as exc:
            return {
                'sent': False,
                'message': (
                    'The backup file could not be prepared. Please check that the app has access '
                    'to its data files, then try again.'
                ),
                'detail': str(exc),
            }

        subject = f'GBMS Daily Backup - {timezone.now().strftime("%Y-%m-%d")}'
        body = (
            'This is the daily backup for the GBMS application.\n\n'
            'The attached zip file contains the current SQLite database plus media files.\n'
            'Restore by replacing the database file in the project and re-running the app if needed.\n'
            'This backup is generated automatically for data recovery.'
        )

        try:
            message = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.EMAIL_BACKUP_TO],
                reply_to=[settings.DEFAULT_FROM_EMAIL],
            )
            message.attach(backup_name, backup_content, 'application/zip')
            sent_count = message.send(fail_silently=False)
            if sent_count != 1:
                return {
                    'sent': False,
                    'message': (
                        'The email service did not confirm that the backup was sent. '
                        'Please check your internet connection and email settings, then try again. '
                        'No backup was saved on this computer.'
                    ),
                    'detail': f'The email service reported that it sent {sent_count} messages.',
                }
        except (OSError, RuntimeError, ValueError, smtplib.SMTPException) as exc:
            return {
                'sent': False,
                'message': (
                    'The backup could not be emailed because the app could not connect to the '
                    'email service. Check your internet connection and email settings, then try '
                    'again. No backup was saved on this computer.'
                ),
                'detail': str(exc),
            }

        Notification.objects.create(
            type=Notification.Type.BACKUP_SENT,
            title='✅ Daily Backup Sent',
            message=f'The latest application backup was emailed successfully on {timezone.now().strftime("%Y-%m-%d %H:%M")}.',
            status=Notification.Status.UNREAD,
            link='/notifications/'
        )

        return {
            'sent': True,
            'message': 'Backup completed successfully and the backup email was sent.',
            'filename': backup_name,
        }

    @staticmethod
    def create_local_backup():
        try:
            filename, content = BackupService._create_backup_payload()
        except (OSError, RuntimeError, TypeError, ValueError, zipfile.LargeZipFile) as exc:
            return {
                'success': False,
                'message': (
                    'The backup file could not be prepared. Please check that the app can read '
                    'its data files, then try again.'
                ),
                'detail': str(exc),
            }
        return {'success': True, 'filename': filename, 'content': content}

    @staticmethod
    def create_backup_reminder_if_missing():
        now = timezone.now()
        settings = NotificationSettings.get_solo()
        interval_start = now - timedelta(hours=settings.backup_reminder_after_hours)
        already_exists = Notification.objects.filter(
            type=Notification.Type.BACKUP_REMINDER,
            status=Notification.Status.UNREAD
        ).exists()

        if already_exists:
            return False

        latest_backup = Notification.objects.filter(
            type=Notification.Type.BACKUP_SENT,
            created_at__gte=interval_start,
        ).exists()
        if latest_backup:
            return False

        Notification.objects.create(
            type=Notification.Type.BACKUP_REMINDER,
            title='⚠️ Daily Backup Required',
            message='You have not created today\'s backup yet. Please click the Backup button to email the latest data safely.',
            status=Notification.Status.UNREAD,
            link='/notifications/'
        )
        return True
