from django.urls import path

from . import views

app_name = 'ai_assistant'

urlpatterns = [
    path(
        'assignments/<int:assignment_pk>/suggestions/generate/',
        views.suggestions_generate,
        name='suggestions_generate',
    ),
    path('suggestions/drafts/<int:pk>/review/', views.suggestions_review, name='suggestions_review'),
    path('suggestions/drafts/<int:pk>/discard/', views.suggestions_discard, name='suggestions_discard'),
    path('suggestions/drafts/<int:pk>/accept/', views.suggestions_accept, name='suggestions_accept'),
    path('assignments/<int:assignment_pk>/tasks/add/', views.task_add, name='task_add'),
    path('tasks/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:pk>/delete/', views.task_delete, name='task_delete'),
    path('tasks/<int:pk>/toggle/', views.task_toggle, name='task_toggle'),
    path('tasks/<int:pk>/move/<str:direction>/', views.task_move, name='task_move'),
]
