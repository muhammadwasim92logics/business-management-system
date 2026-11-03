from django import forms
from .models import Customer
from apps.products.models import Product

class CustomerEntryForm(forms.ModelForm):
    # Customer fields
    name = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter customer name'}))
    mobile = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '03XX-XXXXXXX'}))
    alternate_mobile = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Complete address'}))
    area = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City/Area'}))
    stn = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'STN number'}))
    ntn = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'NTN number'}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Additional notes'}))
    
    # Payment fields
    payment_made = forms.BooleanField(required=False, label='Payment Made')
    payment_amount = forms.DecimalField(required=False, min_value=0, decimal_places=2, 
                                        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}))
    payment_type = forms.ChoiceField(required=False, choices=[('cash', 'Cash'), ('transfer', 'Bank Transfer'), ('upi', 'UPI')],
                                     widget=forms.Select(attrs={'class': 'form-select'}))
    
    class Meta:
        model = Customer
        fields = ['name', 'mobile', 'alternate_mobile', 'address', 'area', 'stn', 'ntn', 'notes']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get all products for the entry form
        self.products = Product.objects.all().order_by('name')