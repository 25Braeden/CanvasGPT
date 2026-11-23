from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from canvas_sync.models import Assignment, CanvasConnection, Course


class SyncNoticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='sync-notice-user')
        cls.connection = CanvasConnection.objects.create(
            user=cls.user, canvas_base_url='https://canvas.example.com',
            access_token='private-token', sync_status=CanvasConnection.SyncStatus.SUCCESS,
            last_synchronized_at=timezone.now(),
        )
        course = Course.objects.create(user=cls.user, canvas_course_id=501, name='Course')
        cls.assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=601, title='Notice assignment',
            sync_status=Assignment.SyncStatus.SUCCESS, last_synchronized_at=timezone.now(),
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_successful_dashboard_notice_is_dismissible(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, ' data-sync-notice', count=1)
        self.assertContains(response, 'data-dismiss-sync hidden', count=1)
        self.assertContains(response, 'aria-label="Dismiss successful Canvas sync notification"')
        self.assertContains(response, '/static/accounts/sync-notices.js')

    def test_stale_and_failed_dashboard_notices_cannot_be_dismissed(self):
        for status in (CanvasConnection.SyncStatus.SUCCESS, CanvasConnection.SyncStatus.FAILED):
            with self.subTest(status=status):
                CanvasConnection.objects.filter(pk=self.connection.pk).update(
                    sync_status=status, last_synchronized_at=timezone.now() - timedelta(days=2),
                )
                response = self.client.get(reverse('dashboard'))
                self.assertNotContains(response, ' data-sync-notice')
                self.assertNotContains(response, 'data-dismiss-sync hidden')
                self.assertContains(response, 'Sync now')

    def test_successful_assignment_notice_is_also_dismissible(self):
        response = self.client.get(reverse('canvas_sync:assignment_detail', args=[self.assignment.pk]))
        self.assertContains(response, ' data-sync-notice', count=2)
        self.assertContains(response, 'data-dismiss-sync hidden', count=2)

    def test_non_success_assignment_notice_stays_visible(self):
        for status in (Assignment.SyncStatus.SUCCESS, Assignment.SyncStatus.FAILED):
            with self.subTest(status=status):
                Assignment.objects.filter(pk=self.assignment.pk).update(
                    sync_status=status, last_synchronized_at=timezone.now() - timedelta(days=2),
                )
                response = self.client.get(reverse('canvas_sync:assignment_detail', args=[self.assignment.pk]))
                # Only the successful dashboard notice is dismissible, not the assignment warning/error.
                self.assertContains(response, ' data-sync-notice', count=1)
                self.assertContains(response, 'data-dismiss-sync hidden', count=1)
                self.assertContains(response, 'Sync now')
