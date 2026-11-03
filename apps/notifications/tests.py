from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
import io
import zipfile

from apps.notifications.models import Notification
from apps.notifications.services import BackupService


class BackupServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='backup-user', password='secret123')

    def test_daily_backup_email_sends_once_per_day(self):
        first = BackupService.send_daily_backup(self.user)
        self.assertTrue(first['sent'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(BackupService.is_backup_sent_today(self.user))

        second = BackupService.send_daily_backup(self.user)
        self.assertFalse(second['sent'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('already been sent for today', second['message'].lower())

        backup_note = Notification.objects.filter(type='backup_sent', created_at__date__gte=__import__('datetime').datetime.now().date())
        self.assertTrue(backup_note.exists())

    @patch('apps.notifications.backup_service.EmailMessage')
    @patch('apps.notifications.backup_service.BackupService._create_backup_payload')
    def test_daily_backup_email_failure_does_not_save_a_local_copy(self, create_payload, fake_email):
        create_payload.return_value = ('gbms_backup_test.zip', b'backup bytes')
        message = fake_email.return_value
        message.send.side_effect = OSError('SMTP delivery failed')

        response = BackupService.send_daily_backup(self.user)

        self.assertFalse(response['sent'])
        self.assertIn('could not be emailed', response['message'])
        self.assertIn('internet connection', response['message'].lower())
        self.assertIn('no backup was saved on this computer', response['message'].lower())
        self.assertEqual(response['detail'], 'SMTP delivery failed')
        self.assertNotIn('path', response)
        self.assertFalse(Notification.objects.filter(type='backup_sent').exists())

    @patch('apps.notifications.backup_service.BackupService._create_backup_payload')
    def test_backup_creation_failure_returns_actionable_reason(self, create_payload):
        create_payload.side_effect = OSError('Permission denied')

        response = BackupService.send_daily_backup(self.user)

        self.assertFalse(response['sent'])
        self.assertIn('backup file could not be prepared', response['message'])
        self.assertEqual(response['detail'], 'Permission denied')
        self.assertNotIn('path', response)

    @patch('apps.notifications.backup_service.EmailMessage')
    @patch('apps.notifications.backup_service.BackupService._create_backup_payload')
    def test_backup_email_backend_sending_no_messages_does_not_save_locally(self, create_payload, fake_email):
        create_payload.return_value = ('gbms_backup_test.zip', b'backup bytes')
        fake_email.return_value.send.return_value = 0

        response = BackupService.send_daily_backup(self.user)

        self.assertFalse(response['sent'])
        self.assertIn('did not confirm', response['message'])
        self.assertIn('no backup was saved on this computer', response['message'].lower())
        self.assertIn('sent 0 messages', response['detail'])
        self.assertNotIn('path', response)
        self.assertFalse(Notification.objects.filter(type='backup_sent').exists())

    @patch('apps.notifications.views.BackupService.send_daily_backup')
    def test_backup_result_is_shown_as_a_popup_message(self, send_backup):
        send_backup.return_value = {
            'sent': False,
            'message': 'Backup email could not be sent: Network is unreachable.',
        }
        self.client.force_login(self.user)

        response = self.client.post(reverse('notifications:backup_now'), follow=True)

        self.assertContains(response, 'data-backup-feedback="Backup email could not be sent: Network is unreachable."')
        self.assertContains(response, 'data-backup-status="error"')
        self.assertContains(response, 'id="backupFeedbackModal"')
        self.assertContains(response, 'Backup could not be sent online')
        self.assertContains(response, 'id="backupFeedbackMessage"')
        self.assertContains(response, 'backup-feedback-fallback')
        self.assertContains(response, 'Save to this computer')
        self.assertContains(response, 'Send backup online')
        self.assertNotContains(response, 'window.alert(feedback.dataset.backupFeedback)')

    @patch('apps.notifications.views.BackupService.send_daily_backup')
    def test_successful_backup_result_is_shown_as_a_popup_message(self, send_backup):
        send_backup.return_value = {
            'sent': True,
            'message': 'Backup completed successfully and the backup email was sent.',
        }
        self.client.force_login(self.user)

        response = self.client.post(reverse('notifications:backup_now'), follow=True)

        self.assertContains(response, 'Backup completed successfully and the backup email was sent.')
        self.assertContains(response, 'data-backup-status="success"')
        self.assertContains(response, 'id="backupFeedbackModal"')
        self.assertNotContains(response, 'window.alert(feedback.dataset.backupFeedback)')

    def test_local_backup_download_returns_a_zip_attachment(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('notifications:backup_download'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertIn('attachment; filename="gbms_backup_', response['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(response.content)) as backup:
            self.assertIn('backup_metadata.json', backup.namelist())
            self.assertIn('db.sqlite3', backup.namelist())
