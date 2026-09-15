from django.contrib import admin

from .models import Assignment, Course, RubricCriterion


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'course_code', 'term', 'is_active', 'user')
    list_filter = ('is_active', 'term')
    search_fields = ('name', 'course_code')


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'due_at', 'points_possible', 'last_synchronized_at')
    list_filter = ('due_at',)
    search_fields = ('title', 'course__name')


@admin.register(RubricCriterion)
class RubricCriterionAdmin(admin.ModelAdmin):
    list_display = ('title', 'assignment', 'points')
    search_fields = ('title', 'assignment__title')
