import requests

from .services import CanvasAPIClient
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import CanvasConnectionForm
from .models import CanvasConnection


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