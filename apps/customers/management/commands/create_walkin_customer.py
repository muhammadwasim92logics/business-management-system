from django.core.management.base import BaseCommand
from apps.customers.models import Customer

class Command(BaseCommand):
    help = 'Create a default walk-in customer'

    def handle(self, *args, **options):
        walkin, created = Customer.objects.get_or_create(
            is_walkin=True,
            defaults={
                'name': 'Walk-in Customer',
                'mobile': '',
                'address': '',
                'notes': 'Default walk-in customer for quick sales'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✅ Walk-in customer created: {walkin.customer_code}'))
        else:
            self.stdout.write(self.style.WARNING(f'⚠️ Walk-in customer already exists: {walkin.customer_code}'))