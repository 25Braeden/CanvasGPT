import requests
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ai_assistant.forms import TaskItemForm

from .forms import CanvasConnectionForm
from .models import Assignment, CanvasConnection
from .services import CanvasAPIClient


STALE_AFTER = timedelta(hours=24)


@login_required
def canvas_connection(request):
    connection = CanvasConnection.objects.filter(user=request.user).first()

    if request.method == "POST":
        form = CanvasConnectionForm(
            request.POST,
            instance=connection,
        )

        if form.is_valid():
            connection = form.save(commit=False)
            connection.user = request.user
            connection.save()

            messages.success(
                request,
                "Canvas connection saved successfully.",
            )

            return redirect("canvas_sync:connection")
    else:
        form = CanvasConnectionForm(instance=connection)

    return render(
        request,
        "canvas_sync/connection.html",
        {
            "form": form,
            "connection": connection,
        },
    )


@login_required
def sync_canvas(request):
    if request.method != "POST":
        return redirect("canvas_sync:connection")

    connection = CanvasConnection.objects.filter(user=request.user).first()

    if not connection:
        messages.error(
            request,
            "Save your Canvas connection before syncing.",
        )
        return redirect("canvas_sync:connection")

    try:
        client = CanvasAPIClient(
            connection.canvas_base_url,
            connection.access_token,
        )

        client.sync_user_data(request.user)

        messages.success(
            request,
            "Canvas data synced successfully.",
        )

    except requests.RequestException:
        messages.error(
            request,
            "Canvas sync failed. Check your Canvas URL and access token.",
        )

    return redirect("canvas_sync:connection")


@login_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.select_related("course").prefetch_related(
            "rubric_criteria"
        ),
        pk=pk,
        course__user=request.user,
    )

    return render(
        request,
        "canvas_sync/assignment_detail.html",
        {
            "assignment": assignment,
            "task_items": assignment.task_items.filter(user=request.user),
            "task_form": TaskItemForm(),
        },
    )


def get_assignment_sync_status(assignment):
    if not assignment.last_synchronized_at:
        return {
            "level": "warning",
            "label": "Not synced yet",
            "message": (
                "Canvas data has not been synchronized "
                "for this assignment yet."
            ),
        }

    age = timezone.now() - assignment.last_synchronized_at

    if age > STALE_AFTER:
        return {
            "level": "warning",
            "label": "Sync may be stale",
            "message": (
                "This assignment was last synced more than 24 hours ago. "
                "Details may have changed in Canvas."
            ),
        }

    return {
        "level": "success",
        "label": "Up to date",
        "message": (
            "This assignment was recently synchronized with Canvas."
        ),
    }