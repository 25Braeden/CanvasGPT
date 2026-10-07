from django.urls import path

from . import views

app_name = "canvas_sync"

urlpatterns = [
    path("connection/", views.canvas_connection, name="connection"),
    path("sync/", views.sync_canvas, name="sync"),
    path(
        "assignments/<int:pk>/",
        views.assignment_detail,
        name="assignment_detail",
    ),
]