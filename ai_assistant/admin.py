from django.contrib import admin

from .models import AIRequest, TaskItem


@admin.register(TaskItem)
class TaskItemAdmin(admin.ModelAdmin):
    list_display = (
        'description',
        'assignment',
        'user',
        'estimated_minutes',
        'order',
        'is_completed',
        'ai_generated',
    )
    list_filter = ('is_completed', 'ai_generated')
    search_fields = ('description', 'assignment__title')


@admin.register(AIRequest)
class AIRequestAdmin(admin.ModelAdmin):
    list_display = ('request_type', 'user', 'requested_at', 'success', 'model_name')
    list_filter = ('request_type', 'success', 'model_name')
    search_fields = ('user__username',)
    readonly_fields = ('requested_at',)
