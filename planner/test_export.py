import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import StudentProfile

from .ical import escape_text, fold_line, format_utc
from .models import StudyPlan
from .test_views import PlannerViewTestCase


def unfold(body):
    """Undo RFC 5545 line folding and split into logical lines."""
    return body.replace('\r\n ', '').split('\r\n')


class IcalHelperTests(SimpleTestCase):
    def test_escape_text_handles_special_characters(self):
        self.assertEqual(
            escape_text('a,b;c\\d\ne\r\nf'),
            'a\\,b\\;c\\\\d\\ne\\nf',
        )

    def test_short_line_is_not_folded(self):
        self.assertEqual(fold_line('SUMMARY:short'), 'SUMMARY:short')

    def test_long_line_folds_to_75_octets(self):
        line = 'DESCRIPTION:' + 'x' * 200
        folded = fold_line(line)
        physical = folded.split('\r\n')
        self.assertGreater(len(physical), 1)
        for part in physical:
            self.assertLessEqual(len(part.encode('utf-8')), 75)
        for part in physical[1:]:
            self.assertTrue(part.startswith(' '))
        self.assertEqual(folded.replace('\r\n ', ''), line)

    def test_fold_never_splits_multibyte_characters(self):
        line = 'SUMMARY:' + 'é' * 100
        folded = fold_line(line)
        for part in folded.split('\r\n'):
            self.assertLessEqual(len(part.encode('utf-8')), 75)
            part.encode('utf-8').decode('utf-8')
        self.assertEqual(folded.replace('\r\n ', ''), line)

    def test_format_utc_converts_from_local_time(self):
        local = datetime.datetime(2026, 11, 2, 9, 30, tzinfo=ZoneInfo('America/Chicago'))
        self.assertEqual(format_utc(local), '20261102T153000Z')


class PlanExportViewTests(PlannerViewTestCase):
    url = reverse('planner:plan_export')

    def active_plan(self, user=None):
        return StudyPlan.objects.create(
            user=user or self.user,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 31),
            is_active=True,
        )

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response['Location'])

    def test_rejects_post(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)

    def test_response_headers(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/calendar; charset=utf-8')
        self.assertEqual(
            response['Content-Disposition'],
            'attachment; filename="canvasgpt-study-plan.ics"',
        )

    def test_no_plan_returns_empty_calendar(self):
        body = self.client.get(self.url).content.decode()
        lines = unfold(body)
        self.assertEqual(lines[0], 'BEGIN:VCALENDAR')
        self.assertIn('VERSION:2.0', lines)
        self.assertIn('END:VCALENDAR', lines)
        self.assertNotIn('BEGIN:VEVENT', body)
        self.assertTrue(body.endswith('\r\n'))

    def test_exports_session_details(self):
        plan = self.active_plan()
        session = self.make_session(plan=plan, description='Draft intro, outline; notes')

        body = self.client.get(self.url).content.decode()
        lines = unfold(body)

        self.assertEqual(body.count('BEGIN:VEVENT'), 1)
        self.assertIn(f'UID:session-{session.pk}@canvasgpt', lines)
        self.assertIn('DTSTART:20261001T180000Z', lines)
        self.assertIn('DTEND:20261001T183000Z', lines)
        self.assertIn('SUMMARY:Draft intro\\, outline\\; notes', lines)
        detail_url = reverse('canvas_sync:assignment_detail', args=[self.assignment.pk])
        self.assertIn(f'URL:http://testserver{detail_url}', lines)
        description = next(line for line in lines if line.startswith('DESCRIPTION:'))
        self.assertIn('Assignment: Scheduler Lab', description)
        self.assertIn('Course: Operating Systems', description)

    def test_all_physical_lines_within_75_octets(self):
        plan = self.active_plan()
        self.make_session(plan=plan, description='Long task ' * 30)
        body = self.client.get(self.url).content.decode()
        for line in body.split('\r\n'):
            self.assertLessEqual(len(line.encode('utf-8')), 75)

    def test_excludes_other_users_sessions(self):
        self.make_session(plan=self.active_plan(), description='Mine')
        self.make_session(
            user=self.other, plan=self.active_plan(self.other), description='Theirs'
        )
        body = self.client.get(self.url).content.decode()
        self.assertIn('SUMMARY:Mine', body)
        self.assertNotIn('Theirs', body)

    def test_excludes_inactive_plans(self):
        old = self.active_plan()
        self.make_session(plan=old, description='Old plan task')
        old.is_active = False
        old.save()
        self.make_session(plan=self.active_plan(), description='Current task')

        body = self.client.get(self.url).content.decode()
        self.assertIn('Current task', body)
        self.assertNotIn('Old plan task', body)

    def test_completed_sessions_excluded_by_default(self):
        plan = self.active_plan()
        self.make_session(plan=plan, description='Finished', is_completed=True)
        self.make_session(plan=plan, description='Pending')

        body = self.client.get(self.url).content.decode()
        self.assertIn('Pending', body)
        self.assertNotIn('Finished', body)

    def test_completed_sessions_included_when_requested(self):
        plan = self.active_plan()
        self.make_session(plan=plan, description='Finished', is_completed=True)

        body = self.client.get(self.url, {'include_completed': '1'}).content.decode()
        self.assertIn('SUMMARY:[Done] Finished', unfold(body))

    def test_times_are_utc_across_dst_change(self):
        StudentProfile.objects.update_or_create(
            user=self.user, defaults={'timezone': 'America/Chicago'}
        )
        chicago = ZoneInfo('America/Chicago')
        plan = self.active_plan()
        # US DST ends Nov 1, 2026: 6 PM local is 23:00Z before, 00:00Z after.
        self.make_session(
            plan=plan,
            description='Before DST ends',
            scheduled_start=datetime.datetime(2026, 10, 31, 18, tzinfo=chicago),
        )
        self.make_session(
            plan=plan,
            description='After DST ends',
            scheduled_start=datetime.datetime(2026, 11, 2, 18, tzinfo=chicago),
        )

        lines = unfold(self.client.get(self.url).content.decode())
        self.assertIn('DTSTART:20261031T230000Z', lines)
        self.assertIn('DTSTART:20261103T000000Z', lines)


class PlanExportButtonTests(PlannerViewTestCase):
    def test_button_shown_with_unfinished_sessions(self):
        plan = StudyPlan.objects.create(
            user=self.user,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 1),
        )
        self.make_session(plan=plan)
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertContains(response, reverse('planner:plan_export'))

    def test_button_hidden_without_plan(self):
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertNotContains(response, reverse('planner:plan_export'))
