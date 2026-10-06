from django.urls import path

from . import views

app_name = 'ai_assistant'

urlpatterns = [
    path('assignments/<int:assignment_pk>/tasks/add/', views.task_add, name='task_add'),
    path('tasks/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:pk>/delete/', views.task_delete, name='task_delete'),
    path('tasks/<int:pk>/toggle/', views.task_toggle, name='task_toggle'),
    path('tasks/<int:pk>/move/<str:direction>/', views.task_move, name='task_move'),
]
