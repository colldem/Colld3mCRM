"""Background commands that report when they last succeeded or failed.

The worker loop and the Kubernetes CronJobs run these; ``/metrics`` exposes the
timestamps so monitoring can alert on a worker that silently stopped.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class TrackedCommand(BaseCommand):
    def execute(self, *args, **options):
        from contacts.models import JobHeartbeat

        name = self.__module__.rsplit(".", 1)[-1]
        try:
            result = super().execute(*args, **options)
        except Exception as error:
            JobHeartbeat.objects.update_or_create(
                name=name, defaults={"last_failure_at": timezone.now(), "last_error": repr(error)[:500]})
            raise
        JobHeartbeat.objects.update_or_create(name=name, defaults={"last_success_at": timezone.now()})
        return result
