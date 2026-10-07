from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from .models import StudentProfile


TIMEZONE_ALIASES = {
    "EDT": "America/New_York",
    "EST": "America/New_York",
}


class UserTimezoneMiddleware:
    """Activate each authenticated student's preferred timezone."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        timezone.deactivate()

        if request.user.is_authenticated:
            try:
                timezone_name = request.user.student_profile.timezone
                timezone_name = TIMEZONE_ALIASES.get(
                    timezone_name.upper(),
                    timezone_name,
                )
                timezone.activate(ZoneInfo(timezone_name))
            except (StudentProfile.DoesNotExist, ZoneInfoNotFoundError):
                pass

        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
