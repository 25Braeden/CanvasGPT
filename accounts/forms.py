from zoneinfo import available_timezones

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .middleware import TIMEZONE_ALIASES
from .models import StudentProfile, User


class SignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class UserDetailsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')


class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = (
            'timezone',
            'preferred_session_minutes',
            'break_minutes',
            'daily_study_goal_minutes',
            'notifications_enabled',
            'dark_mode_enabled',
            'due_soon_days',
        )

    def clean_timezone(self):
        timezone_name = self.cleaned_data['timezone'].strip()
        lookup_name = TIMEZONE_ALIASES.get(timezone_name.upper(), timezone_name)
        # available_timezones() is case-sensitive, unlike ZoneInfo on macOS.
        if lookup_name not in available_timezones():
            raise forms.ValidationError(
                'Enter a valid timezone, such as "America/New_York" or "UTC".'
            )
        return timezone_name
