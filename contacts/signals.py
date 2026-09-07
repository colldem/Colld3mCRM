from django.core.exceptions import ValidationError
from django.utils.translation import gettext as tr
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import Person


@receiver(m2m_changed, sender=Person.tags.through)
@receiver(m2m_changed, sender=Person.categories.through)
def enforce_three_item_limit(sender, instance, action, pk_set, **kwargs):
    if action != "pre_add":
        return
    relation = instance.tags if sender is Person.tags.through else instance.categories
    existing = relation.count()
    incoming = len(pk_set or set())
    if existing + incoming > 3:
        raise ValidationError(tr("Galima pasirinkti ne daugiau kaip 3 reikšmes."))
