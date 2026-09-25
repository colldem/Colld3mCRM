"""Background commands that report when they last succeeded or failed.

The worker loop and the Kubernetes CronJobs run these; ``/metrics`` exposes the
timestamps so monitoring can alert on a worker that silently stopped.
"""
import signal
import threading

from django.core.management.base import BaseCommand
from django.utils import timezone


class JobStopped(Exception):
    """SIGTERM: the worker's `timeout` or a Kubernetes deadline ended the run."""


def _stop(signum, frame):
    raise JobStopped("stopped by signal %d (time limit reached)" % signum)


class TrackedCommand(BaseCommand):
    def execute(self, *args, **options):
        from contacts.models import JobHeartbeat

        name = self.__module__.rsplit(".", 1)[-1]
        # A command stopped for running too long is a failure worth seeing on
        # the system health page, not a silent gap in its success times.
        main = threading.current_thread() is threading.main_thread()
        previous = signal.signal(signal.SIGTERM, _stop) if main else None
        try:
            result = super().execute(*args, **options)
        except Exception as error:
            JobHeartbeat.objects.update_or_create(
                name=name, defaults={"last_failure_at": timezone.now(), "last_error": repr(error)[:500]})
            raise
        finally:
            if main:
                signal.signal(signal.SIGTERM, previous)
        JobHeartbeat.objects.update_or_create(name=name, defaults={"last_success_at": timezone.now()})
        return result
