import logging
from datetime import timedelta

import requests

from django.contrib import messages
from django.db import DatabaseError
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ai_assistant.forms import TaskItemForm

from .forms import CanvasConnectionForm
from .models import Assignment, CanvasConnection
from .services import CanvasAPIClient, CanvasSyncError


STALE_AFTER = timedelta(hours=24)
DEFAULT_ASSIGNMENT_SYNC_FAILURE_MESSAGE = (
    "Canvas synchronization failed for this assignment."
)
logger = logging.getLogger(__name__)


def _sync_failure_message(error):
    if isinstance(error, requests.HTTPError):
        response = error.response
        if response is not None and response.status_code in (401, 403):
            return "Canvas rejected the saved access token. Check your Canvas connection."
        return "Canvas returned an API error. Try syncing again later."
    if isinstance(error, requests.RequestException):
        return "Canvas could not be reached. Check your connection and try again."
    if isinstance(error, CanvasSyncError):
        return "Canvas returned data that could not be synchronized."
    return "Canvas data could not be saved. Try syncing again later."


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
        form = CanvasConnectionForm(
            instance=connection,
            initial={"canvas_base_url": ""},
        )

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

    except (requests.RequestException, CanvasSyncError, DatabaseError) as error:
        logger.exception(
            "Canvas synchronization failed for user ID %s.",
            request.user.pk,
        )
        messages.error(request, _sync_failure_message(error))

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
            "assignment_sync_status": get_assignment_sync_status(assignment),
            "task_items": assignment.task_items.filter(user=request.user),
            "task_form": TaskItemForm(),
        },
    )


def get_assignment_sync_status(assignment):
    if assignment.sync_status == Assignment.SyncStatus.FAILED:
        return {
            "level": "error",
            "label": "Sync failed",
            "message": (
                assignment.sync_error_message
                or DEFAULT_ASSIGNMENT_SYNC_FAILURE_MESSAGE
            ),
        }

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