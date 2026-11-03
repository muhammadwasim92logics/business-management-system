from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from apps.deliveries.models import Delivery
import re

class Command(BaseCommand):
    help = 'Assign invoice numbers to deliveries without one'

    def handle(self, *args, **options):
        # Get all deliveries without invoice numbers, ordered by date (oldest first)
        deliveries = Delivery.objects.filter(
            Q(fbr_invoice_no__isnull=True) | Q(fbr_invoice_no='')
        ).order_by('delivery_date', 'created_at')
        
        # Check if there are any existing invoice numbers
        last_delivery = Delivery.objects.exclude(
            Q(fbr_invoice_no__isnull=True) | Q(fbr_invoice_no='')
        ).order_by('-fbr_invoice_no').first()
        
        if last_delivery and last_delivery.fbr_invoice_no:
            match = re.search(r'(\d+)$', last_delivery.fbr_invoice_no)
            if match:
                next_number = int(match.group(1)) + 1
            else:
                next_number = 1001
        else:
            next_number = 1001
        
        assigned_count = 0
        with transaction.atomic():
            for delivery in deliveries:
                delivery.fbr_invoice_no = str(next_number)
                delivery.save()
                next_number += 1
                assigned_count += 1
        
        self.stdout.write(f'✅ Assigned {assigned_count} invoice numbers')