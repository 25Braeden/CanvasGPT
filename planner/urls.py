from django.urls import path

from . import views

app_name = 'planner'

urlpatterns = [
    path('availability/', views.availability_list, name='availability_list'),
    path('availability/add/', views.availability_add, name='availability_add'),
    path('availability/<int:pk>/edit/', views.availability_edit, name='availability_edit'),
    path('availability/<int:pk>/delete/', views.availability_delete, name='availability_delete'),
    path('plan/', views.plan_detail, name='plan_detail'),
    path('plan/generate/', views.plan_generate, name='plan_generate'),
    path('sessions/<int:pk>/toggle/', views.session_toggle, name='session_toggle'),
]
