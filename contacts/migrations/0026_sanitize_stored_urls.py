"""Blank any WebLink / Company URL that is not a plain http(s) link.

Historic rows could hold `javascript:` and similar because `objects.create()`
skips model validation; those render as active hrefs on the card.
"""
from django.db import migrations

from contacts.sanitizers import safe_url


def scrub(apps, schema_editor):
    WebLink = apps.get_model("contacts", "WebLink")
    Company = apps.get_model("contacts", "Company")
    for link in WebLink.objects.all().iterator():
        cleaned = safe_url(link.url)
        if cleaned != link.url:
            if cleaned:
                link.url = cleaned
                link.save(update_fields=["url"])
            else:
                link.delete()
    for company in Company.objects.exclude(url="").iterator():
        cleaned = safe_url(company.url)
        if cleaned != company.url:
            company.url = cleaned
            company.save(update_fields=["url"])


class Migration(migrations.Migration):

    dependencies = [
        ("contacts", "0025_reminder_assigned_to_reminder_priority"),
    ]

    operations = [
        migrations.RunPython(scrub, migrations.RunPython.noop),
    ]
