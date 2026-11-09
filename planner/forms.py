from django import forms

from .models import AvailabilityBlock


class AvailabilityBlockForm(forms.ModelForm):
    class Meta:
        model = AvailabilityBlock
        fields = ['recurrence', 'date', 'weekday', 'start_time', 'end_time']
        labels = {
            'recurrence': 'Repeats',
            'date': 'Date',
            'weekday': 'Weekday',
            'start_time': 'Start time',
            'end_time': 'End time',
        }
        help_texts = {
            'date': '',
            'weekday': '',
        }
        widgets = {
            'date': forms.DateInput(
                attrs={'type': 'date'},
                format='%Y-%m-%d',
            ),
            'start_time': forms.TimeInput(
                attrs={'type': 'time'},
                format='%H:%M',
            ),
            'end_time': forms.TimeInput(
                attrs={'type': 'time'},
                format='%H:%M',
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        recurrence = cleaned_data.get('recurrence')

        if recurrence == AvailabilityBlock.Recurrence.WEEKLY:
            cleaned_data['date'] = None

        elif recurrence == AvailabilityBlock.Recurrence.NONE:
            cleaned_data['weekday'] = None

        return cleaned_data