"""Build iCalendar (RFC 5545) text from study plan sessions.

Times are written in UTC so no VTIMEZONE blocks are needed; calendar
applications convert them to the viewer's local time.
"""

import datetime

from django.urls import reverse
from django.utils import timezone

PRODID = '-//Canvas Copilots//CanvasGPT//EN'
UID_DOMAIN = 'canvasgpt'
MAX_LINE_OCTETS = 75


def escape_text(value):
    """Escape a TEXT property value per RFC 5545 section 3.3.11."""
    value = str(value)
    value = value.replace('\\', '\\\\')
    value = value.replace(';', '\\;').replace(',', '\\,')
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    return value.replace('\n', '\\n')


def fold_line(line):
    """Fold a content line so no physical line exceeds 75 octets.

    Continuation lines start with a single space, which counts toward the
    limit. Multi-byte UTF-8 characters are never split.
    """
    if len(line.encode('utf-8')) <= MAX_LINE_OCTETS:
        return line
    parts = []
    current = ''
    current_octets = 0
    limit = MAX_LINE_OCTETS
    for char in line:
        size = len(char.encode('utf-8'))
        if current_octets + size > limit:
            parts.append(current)
            current = ''
            current_octets = 0
            limit = MAX_LINE_OCTETS - 1  # leave room for the leading space
        current += char
        current_octets += size
    parts.append(current)
    return '\r\n '.join(parts)


def format_utc(value):
    """Format an aware datetime as an iCalendar UTC DATE-TIME."""
    return value.astimezone(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _session_description(session, tz):
    assignment = session.task_item.assignment
    course = assignment.course
    lines = [f'Assignment: {assignment.title}']
    course_label = course.course_code or course.name
    if course_label:
        lines.append(f'Course: {course_label}')
    if assignment.due_at:
        due = timezone.localtime(assignment.due_at, tz)
        lines.append(f'Due: {due:%b %d, %Y %I:%M %p %Z}')
    lines.append(f'Estimated: {session.task_item.estimated_minutes} min')
    return '\n'.join(lines)


def build_session_event(session, request, tz, now):
    """Return the content lines for one VEVENT."""
    assignment_url = request.build_absolute_uri(
        reverse('canvas_sync:assignment_detail', args=[session.task_item.assignment.pk])
    )
    summary = session.task_item.description
    if session.is_completed:
        summary = f'[Done] {summary}'
    return [
        'BEGIN:VEVENT',
        f'UID:session-{session.pk}@{UID_DOMAIN}',
        f'DTSTAMP:{format_utc(now)}',
        f'DTSTART:{format_utc(session.scheduled_start)}',
        f'DTEND:{format_utc(session.scheduled_end)}',
        f'SUMMARY:{escape_text(summary)}',
        f'DESCRIPTION:{escape_text(_session_description(session, tz))}',
        f'URL:{assignment_url}',
        'STATUS:CONFIRMED',
        'TRANSP:OPAQUE',
        'END:VEVENT',
    ]


def build_calendar(sessions, request, tz, now=None):
    """Return a complete VCALENDAR document for the given sessions."""
    now = now or timezone.now()
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        f'PRODID:{PRODID}',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:CanvasGPT Study Plan',
    ]
    for session in sessions:
        lines.extend(build_session_event(session, request, tz, now))
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold_line(line) for line in lines) + '\r\n'
