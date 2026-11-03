from django import forms
from .models import Delivery
from apps.customers.models import Customer

class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ['customer', 'product', 'quantity', 'unit_price', 
                  'empty_returned', 'full_delivered', 'is_guarantee', 'guarantee_amount', 'remarks']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'product': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'empty_returned': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'full_delivered': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'is_guarantee': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'guarantee_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Order customers by name
        self.fields['customer'].queryset = Customer.objects.all().order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        quantity = cleaned_data.get('quantity')
        
        if product and quantity and quantity > product.stock_quantity:
            raise forms.ValidationError(
                f'⚠️ Insufficient Stock! Available: {product.stock_quantity} units.'
            )
        return cleaned_data