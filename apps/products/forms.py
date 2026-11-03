from django import forms
from .models import Product
from .models import FactoryFillTransaction


class FactoryFillTransactionForm(forms.ModelForm):
    class Meta:
        model = FactoryFillTransaction
        fields = ['factory', 'product', 'transaction_date', 'empty_sent', 'full_received', 'invoice_number', 'notes']
        widgets = {
            'transaction_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'empty_sent': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'full_received': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'invoice_number': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 50}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'unit_price', 'purchase_price', 'stock_quantity', 'empty_stock_quantity', 'unit_weight_kg', 
                  'stock_weight_kg', 'minimum_stock', 'is_quantity_only', 'is_filling_only', 'is_sellable', 'is_purchasable']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'e.g., LPG 25KG, CU-2, LOCK CYLINDER, REGULATOR',
                'style': 'text-transform: uppercase;'
            }),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'purchase_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stock_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'empty_stock_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'opening_full_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'opening_empty_quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_weight_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'stock_weight_kg': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.001'}),
            'minimum_stock': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_quantity_only': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_filling_only': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_sellable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_purchasable': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Product Name',
            'unit_price': 'Selling Price (PKR)',
            'purchase_price': 'Purchase Price (PKR)',
            'stock_quantity': 'Stock Quantity',
            'empty_stock_quantity': 'Empty Cylinder Stock',
            'opening_full_quantity': 'Opening Full Cylinders',
            'opening_empty_quantity': 'Opening Empty Cylinders',
            'unit_weight_kg': 'Unit Weight (kg)',
            'stock_weight_kg': 'Current Stock Weight (kg)',
            'minimum_stock': 'Minimum Stock Alert',
            'is_quantity_only': 'Sale Only / Direct Product (No Empty Cylinder Exchange)',
            'is_filling_only': 'Cylinder Filling Only / LPG Filling Product',
            'is_sellable': 'Show in Sales Module',
            'is_purchasable': 'Show in Purchases Module',
        }

    def clean_name(self):
        """Convert name to uppercase and check for duplicates"""
        name = self.cleaned_data.get('name')
        if name:
            name = name.upper().strip()
            existing = Product.objects.filter(name=name)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError(f'❌ Product "{name}" already exists! Please use a different name.')
        return name

    def clean_unit_price(self):
        price = self.cleaned_data.get('unit_price')
        if price is not None and price < 0:
            raise forms.ValidationError('Unit price cannot be negative.')
        return price

    def clean_purchase_price(self):
        price = self.cleaned_data.get('purchase_price')
        if price is not None and price < 0:
            raise forms.ValidationError('Purchase price cannot be negative.')
        return price

    def clean_stock_quantity(self):
        qty = self.cleaned_data.get('stock_quantity')
        unchanged_existing_deficit = (
            self.instance.pk
            and not self.instance._state.adding
            and qty == self.instance.stock_quantity
        )
        if qty is not None and qty < 0 and not unchanged_existing_deficit:
            raise forms.ValidationError('Stock quantity cannot be negative.')
        return qty

    def clean_empty_stock_quantity(self):
        qty = self.cleaned_data.get('empty_stock_quantity')
        if qty is not None and qty < 0:
            raise forms.ValidationError('Empty cylinder stock cannot be negative.')
        return qty

    def clean_minimum_stock(self):
        min_stock = self.cleaned_data.get('minimum_stock')
        if min_stock is not None and min_stock < 0:
            raise forms.ValidationError('Minimum stock cannot be negative.')
        return min_stock
    
    def clean(self):
        cleaned_data = super().clean()
        is_sellable = cleaned_data.get('is_sellable')
        is_purchasable = cleaned_data.get('is_purchasable')
        
        # At least one should be true
        if not is_sellable and not is_purchasable:
            raise forms.ValidationError('❌ Product must be visible in at least one module (Sales or Purchases).')
        
        return cleaned_data