from django.contrib import admin

from .models import AvailabilityBlock, PlanSession, StudyPlan


@admin.register(AvailabilityBlock)
class AvailabilityBlockAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'weekday', 'start_time', 'end_time', 'recurrence')
    list_filter = ('weekday', 'recurrence')
    search_fields = ('user__username',)


class PlanSessionInline(admin.TabularInline):
    model = PlanSession
    extra = 0


@admin.register(StudyPlan)
class StudyPlanAdmin(admin.ModelAdmin):
    list_display = ('user', 'start_date', 'end_date', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('user__username',)
    inlines = [PlanSessionInline]


@admin.register(PlanSession)
class PlanSessionAdmin(admin.ModelAdmin):
    list_display = ('task_item', 'study_plan', 'scheduled_start', 'scheduled_end', 'is_completed')
    list_filter = ('is_completed',)
    search_fields = ('task_item__description',)
