from django import forms

from .models import TaskItem


class TaskItemForm(forms.ModelForm):
    class Meta:
        model = TaskItem
        fields = ['description', 'estimated_minutes']
        labels = {
            'description': 'Task description',
            'estimated_minutes': 'Estimated minutes',
        }
        widgets = {
            'estimated_minutes': forms.NumberInput(attrs={'min': 1}),
        }

    def clean_description(self):
        description = self.cleaned_data['description'].strip()
        if not description:
            raise forms.ValidationError('Task description cannot be blank.')
        return description

    def clean_estimated_minutes(self):
        minutes = self.cleaned_data['estimated_minutes']
        if minutes < 1:
            raise forms.ValidationError('Estimate must be at least 1 minute.')
        return minutes
