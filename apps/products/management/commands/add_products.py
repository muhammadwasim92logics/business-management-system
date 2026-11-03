from django.core.management.base import BaseCommand
from apps.products.models import Product

class Command(BaseCommand):
    help = 'Add bulk products to the system'

    def handle(self, *args, **kwargs):
        products = [
            # Gas Cylinders
            {'name': 'O2 SMALL'},
            {'name': 'O2 BIG'},
            {'name': 'N2 SMALL'},
            {'name': 'N2 BIG'},
            {'name': 'CO2 25KG'},
            {'name': 'CO2 40KG'},
            {'name': 'CO2 20KG'},
            {'name': 'CO2 15KG'},
            {'name': 'CO2 18KG'},
            {'name': 'CO2 5KG'},
            {'name': 'CO2 10KG'},
            {'name': 'ARGON'},
            {'name': 'SPARGON'},
            {'name': 'LPG 45KG'},
            {'name': 'LPG 12KG'},
            
            # Coils
            {'name': 'COIL 0.1MM'},
            {'name': 'COIL 1.2MM'},
            {'name': 'COIL 0.8MM'},
            
            # Keys and Accessories
            {'name': 'CYLINDER KEY'},
            
            # Gags (Regulators)
            {'name': 'OXYGEN GAG'},
            {'name': 'LPG GAG 22'},
            {'name': 'LPG GAG 21'},
            {'name': 'LPG GAG 20'},
            {'name': 'ARGON GAG'},
            {'name': 'CO2 GAG'},
            
            # Cutting Equipment
            {'name': 'CUTTER VICTOR'},
            {'name': 'CUTTER BOC'},
            
            # Welding Torches
            {'name': 'WELDING TORCH LAZER'},
            {'name': 'WELDING TORCH ST'},
            {'name': 'WELDING TORCH CLOUT'},
            
            # Tips
            {'name': 'VICTOR TIPS'},
            {'name': 'BOC TIPS'},
            {'name': 'WELDING TORCH TIPS'},
            {'name': 'CO2 TIPS'},
            
            # Valves
            {'name': 'LPG VALVE'},
            {'name': 'OXYGEN VALVE'},
            {'name': 'NITROGEN VALVE'},
            {'name': 'ARGON VALVE'},
            {'name': 'CO2 VALVE'},
        ]

        added_count = 0
        skipped_count = 0
        
        for product_data in products:
            name = product_data['name']
            try:
                # Check if product already exists
                if Product.objects.filter(name=name).exists():
                    self.stdout.write(self.style.WARNING(f'Skipping: {name} (already exists)'))
                    skipped_count += 1
                    continue
                
                # Create the product with Price=0 and Stock=10
                Product.objects.create(
                    name=name,
                    unit_price=0,           # Price set to 0
                    stock_quantity=10,      # Stock set to 10
                    minimum_stock=1
                )
                self.stdout.write(self.style.SUCCESS(f'Added: {name} (Price: 0, Stock: 10)'))
                added_count += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error adding {name}: {str(e)}'))
                skipped_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Added {added_count} products with Price=0 and Stock=10'))
        self.stdout.write(self.style.WARNING(f'⚠️ Skipped {skipped_count} products (already exist or error)'))
