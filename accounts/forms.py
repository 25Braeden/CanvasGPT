from django import forms
from django.contrib.auth.forms import UserCreationForm

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
