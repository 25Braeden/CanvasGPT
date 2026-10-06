from django.urls import path

from . import views

app_name = 'canvas_sync'

urlpatterns = [
    path('assignments/<int:pk>/', views.assignment_detail, name='assignment_detail'),
]
