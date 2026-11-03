from django.apps import AppConfig

class FbrConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.fbr'
    verbose_name = 'FBR Ledger'

    def ready(self):
        import apps.fbr.signals  # Register signals