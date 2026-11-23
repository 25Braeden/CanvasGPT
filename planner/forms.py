from django import forms
from django.db import transaction

from .models import AvailabilityBlock


class AvailabilityBlockForm(forms.ModelForm):
    # Weekly availability can cover several days at once. Each checked day
    # is stored as its own AvailabilityBlock so scheduling stays per-weekday.
    weekdays = forms.TypedMultipleChoiceField(
        label='Weekdays',
        choices=AvailabilityBlock.Weekday.choices,
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AvailabilityBlock
        fields = ['recurrence', 'date', 'start_time', 'end_time']
        labels = {
            'recurrence': 'Repeats',
            'date': 'Date',
            'start_time': 'Start time',
            'end_time': 'End time',
        }
        help_texts = {
            'date': '',
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.weekday is not None:
            self.initial.setdefault('weekdays', [self.instance.weekday])

    def clean(self):
        cleaned_data = super().clean()

        recurrence = cleaned_data.get('recurrence')
        weekdays = cleaned_data.get('weekdays') or []

        if recurrence == AvailabilityBlock.Recurrence.WEEKLY:
            cleaned_data['date'] = None
            if not weekdays:
                self.add_error('weekdays', 'Choose at least one weekday.')
            # Keep the edited block on its current day when it is still
            # checked; any other checked days become new blocks on save.
            elif self.instance.weekday not in weekdays:
                self.instance.weekday = min(weekdays)

        elif recurrence == AvailabilityBlock.Recurrence.NONE:
            cleaned_data['weekdays'] = []
            self.instance.weekday = None

        return cleaned_data

    def save(self, commit=True):
        """Save this block plus a copy for each additional checked weekday."""
        block = super().save(commit=False)
        extra_days = [
            day for day in sorted(set(self.cleaned_data.get('weekdays') or []))
            if day != block.weekday
        ]
        self.extra_blocks = [
            AvailabilityBlock(
                user=block.user,
                recurrence=block.recurrence,
                weekday=day,
                start_time=block.start_time,
                end_time=block.end_time,
            )
            for day in extra_days
        ]
        if commit:
            with transaction.atomic():
                block.save()
                AvailabilityBlock.objects.bulk_create(self.extra_blocks)
        return block
