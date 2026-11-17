from django import forms

from .models import TaskItem

from .services import MAX_DESCRIPTION_LENGTH, MAX_ESTIMATED_MINUTES, MAX_TASKS


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


class DraftRevisionForm(forms.Form):

    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class SuggestionReviewForm(forms.Form):

    selected = forms.BooleanField(required=False, label='Select for acceptance')

    description = forms.CharField(

        max_length=MAX_DESCRIPTION_LENGTH,

        widget=forms.Textarea(attrs={'rows': 3}),

        label='Task description',

    )

    estimated_minutes = forms.IntegerField(

        min_value=1,

        max_value=MAX_ESTIMATED_MINUTES,

        label='Estimated minutes',

    )


class BaseSuggestionReviewFormSet(forms.BaseFormSet):

    def __init__(self, *args, expected_count, **kwargs):

        self.expected_count = expected_count

        super().__init__(*args, **kwargs)

        # Existing draft rows must remain represented in the submitted formset.
        # New rows may be added by the student during review.

        for form in self.forms:

            form.empty_permitted = False

    def clean(self):

        super().clean()

        if self.total_form_count() < self.expected_count:

            raise forms.ValidationError(

                'The suggestion list changed. Reload the draft before saving.'

            )

        remaining_count = sum(

            1

            for form in self.forms

            if form.cleaned_data and not form.cleaned_data.get('DELETE', False)

        )

        if remaining_count < 1:

            raise forms.ValidationError(

                'Keep at least one task in the draft.'

            )

        if remaining_count > MAX_TASKS:

            raise forms.ValidationError(

                f'A checklist can contain at most {MAX_TASKS} draft tasks.'

            )


SuggestionReviewFormSet = forms.formset_factory(

    SuggestionReviewForm,

    formset=BaseSuggestionReviewFormSet,

    extra=0,

    min_num=1,

    max_num=MAX_TASKS,

    absolute_max=MAX_TASKS,

    validate_min=True,

    validate_max=True,

    can_delete=True,

)