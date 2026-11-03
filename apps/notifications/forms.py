from django import forms

from .models import NotificationSettings


class NotificationSettingsForm(forms.ModelForm):
    pending_payment_delay_days = forms.IntegerField(min_value=0, required=False)
    pending_payment_delay_hours = forms.IntegerField(min_value=0, max_value=23, required=False)
    cylinder_due_delay_days = forms.IntegerField(min_value=0, required=False)
    cylinder_due_delay_hours = forms.IntegerField(min_value=0, max_value=23, required=False)
    inactive_customer_delay_days = forms.IntegerField(min_value=0, required=False)
    inactive_customer_delay_hours = forms.IntegerField(min_value=0, max_value=23, required=False)
    not_coming_customer_delay_days = forms.IntegerField(min_value=0, required=False)
    not_coming_customer_delay_hours = forms.IntegerField(min_value=0, max_value=23, required=False)
    backup_reminder_delay_days = forms.IntegerField(min_value=0, required=False)
    backup_reminder_delay_hours = forms.IntegerField(min_value=0, max_value=23, required=False)

    class Meta:
        model = NotificationSettings
        fields = (
            'pending_payment_delay_days', 'pending_payment_delay_hours', 'pending_payment_minimum',
            'cylinder_due_delay_days', 'cylinder_due_delay_hours', 'cylinder_due_minimum',
            'inactive_customer_delay_days', 'inactive_customer_delay_hours',
            'not_coming_customer_delay_days', 'not_coming_customer_delay_hours',
            'backup_reminder_delay_days', 'backup_reminder_delay_hours',
            'weekly_reminder_enabled',
        )
        widgets = {
            'pending_payment_minimum': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'cylinder_due_minimum': forms.NumberInput(attrs={'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'weekly_reminder_enabled':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'
        timing_fields = {
            'pending_payment': self.instance.pending_payment_after_hours,
            'cylinder_due': self.instance.cylinder_due_after_hours,
            'inactive_customer': self.instance.inactive_customer_after_hours,
            'not_coming_customer': self.instance.not_coming_customer_after_hours,
            'backup_reminder': self.instance.backup_reminder_after_hours,
        }
        for prefix, total_hours in timing_fields.items():
            self.initial[f'{prefix}_delay_days'], remainder = divmod(total_hours or 0, 24)
            self.initial[f'{prefix}_delay_hours'] = remainder

    @staticmethod
    def _duration(cleaned_data, prefix):
        days = cleaned_data.get(f'{prefix}_delay_days') or 0
        hours = cleaned_data.get(f'{prefix}_delay_hours') or 0
        return days * 24 + hours

    def clean(self):
        cleaned_data = super().clean()
        durations = {
            'pending_payment_after_hours': self._duration(cleaned_data, 'pending_payment'),
            'cylinder_due_after_hours': self._duration(cleaned_data, 'cylinder_due'),
            'inactive_customer_after_hours': self._duration(cleaned_data, 'inactive_customer'),
            'not_coming_customer_after_hours': self._duration(cleaned_data, 'not_coming_customer'),
            'backup_reminder_after_hours': self._duration(cleaned_data, 'backup_reminder'),
        }
        if durations['pending_payment_after_hours'] < 1:
            self.add_error('pending_payment_delay_hours', 'Set a delay of at least 1 hour.')
        if durations['inactive_customer_after_hours'] < 1:
            self.add_error('inactive_customer_delay_hours', 'Set a delay of at least 1 hour.')
        if durations['backup_reminder_after_hours'] < 1:
            self.add_error('backup_reminder_delay_hours', 'Set a reminder interval of at least 1 hour.')
        if durations['not_coming_customer_after_hours'] < durations['inactive_customer_after_hours']:
            self.add_error('not_coming_customer_delay_days', 'This must be greater than or equal to the inactive threshold.')
        cleaned_data.update(durations)
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        for field in (
            'pending_payment_after_hours', 'cylinder_due_after_hours',
            'inactive_customer_after_hours', 'not_coming_customer_after_hours',
            'backup_reminder_after_hours',
        ):
            setattr(instance, field, self.cleaned_data[field])
        if commit:
            instance.save()
        return instance