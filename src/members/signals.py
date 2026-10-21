""" Signal handlers for the members app.

    - Member.is_current changes trigger shirt-number grace-period logic:
      flipping to False closes active assignments with a reservation end-date
      anchored to the member's last-appearance season; flipping back to True
      re-opens the still-active assignment, if any.
    - ClubInfo saves on the MaxShirtNumber* keys extend the shirt pool.
"""

import logging

from django.db import models
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.models import ClubInfo
from members.models import Member, ShirtNumber
from members.models.shirt_number import CLUBINFO_KEYS, grace_period_end_for


LOG = logging.getLogger(__name__)


@receiver(pre_save, sender=Member, dispatch_uid='member_cache_prev_is_current')
def _cache_prev_is_current(sender, instance, **kwargs):
    """ Cache the pre-save value of is_current on the instance so the post_save
        handler can tell whether it flipped.
    """
    if instance.pk:
        try:
            instance._prev_is_current = (
                Member.objects.only('is_current').get(pk=instance.pk).is_current
            )
        except Member.DoesNotExist:
            instance._prev_is_current = None
    else:
        instance._prev_is_current = None


@receiver(post_save, sender=Member, dispatch_uid='member_handle_is_current_change')
def _handle_is_current_change(sender, instance, created, **kwargs):
    """ React to is_current flips:
          True → False  : close active assignments with end_date = grace end.
          False → True  : if an active assignment survives, clear its end_date.
    """
    if created:
        return
    prev = getattr(instance, '_prev_is_current', None)
    if prev is None or prev == instance.is_current:
        return

    today = timezone.now().date()
    if prev is True and instance.is_current is False:
        # Departure: close every active assignment at grace end-date.
        grace_end = grace_period_end_for(instance, today=today)
        active = instance.shirt_assignments.filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))
        for assignment in active:
            assignment.end_date = grace_end
            assignment.save()
    elif prev is False and instance.is_current is True:
        # Re-activation: resume the most recent still-active assignment, if
        # any. Includes NULL end_dates (defence-in-depth: if clean() was
        # bypassed somewhere and the member retains a NULL-ended row despite
        # is_current=False, picking it up here puts them back in a clean state).
        active = instance.shirt_assignments.filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today)
        ).order_by(models.F('end_date').desc(nulls_last=True)).first()
        if active is not None and active.end_date is not None:
            active.end_date = None
            active.save()


@receiver(post_save, sender=ClubInfo, dispatch_uid='clubinfo_extend_shirt_pool')
def _extend_shirt_pool(sender, instance, created, **kwargs):
    """ When a MaxShirtNumber* ClubInfo key is saved, create any missing
        ShirtNumber rows up to the new max.

        Does NOT delete rows when the max is lowered (we never destroy history).
        A lowered max will be flagged by `check_members` if any shirt above the
        new max still has an active assignment.
    """
    gender_by_key = {v: k for k, v in CLUBINFO_KEYS.items()}
    gender = gender_by_key.get(instance.key)
    if not gender:
        return
    try:
        new_max = int(instance.value)
    except (TypeError, ValueError):
        LOG.warning("ClubInfo key %s has non-integer value %r; skipping pool extension.",
                    instance.key, instance.value)
        return
    for n in range(0, new_max + 1):
        ShirtNumber.objects.get_or_create(number=n, gender=gender)
