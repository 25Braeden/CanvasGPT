from django.core.management.base import BaseCommand
from django.utils import timezone

from ai_assistant.models import SuggestionDraft


class Command(BaseCommand):
    help = 'Delete expired suggestion drafts without changing tasks, plans, or AIRequest audits.'

    def handle(self, *args, **options):
        count, _ = SuggestionDraft.objects.filter(expires_at__lte=timezone.now()).delete()
        self.stdout.write(f'Deleted {count} expired suggestion drafts.')
