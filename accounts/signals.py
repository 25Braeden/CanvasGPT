from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StudentProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_student_profile(sender, instance, created, raw, **kwargs):
    if created and not raw:
        StudentProfile.objects.create(user=instance)
