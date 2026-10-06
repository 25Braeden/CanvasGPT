from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import StudentProfile, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    pass


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'timezone',
        'preferred_session_minutes',
        'break_minutes',
        'daily_study_goal_minutes',
        'notifications_enabled',
    )
    search_fields = ('user__username', 'user__email')
    list_filter = ('notifications_enabled', 'timezone')
