""" The ShirtNumber model represents a single shirt in the club's pool, and the
    ShirtNumberAssignment model tracks the history of which member has worn
    which shirt and when.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from datetime import date

from core.models import ClubInfo, Gender, ShirtNumberStatus
from competitions.models import Season
from competitions.models.season import SEASON_END_DAY, SEASON_END_MONTH


DEFAULT_MAX_SHIRT_NUMBER = 170
CLUBINFO_KEYS = {
    Gender.Male: 'MaxShirtNumberMale',
    Gender.Female: 'MaxShirtNumberFemale',
}


def get_max_shirt_number(gender):
    """ Returns the current max shirt number for the given gender, as configured in ClubInfo.

        Falls back to DEFAULT_MAX_SHIRT_NUMBER if the ClubInfo value is missing or invalid.
    """
    key = CLUBINFO_KEYS.get(gender)
    if not key:
        return DEFAULT_MAX_SHIRT_NUMBER
    try:
        return int(ClubInfo.objects.get(key=key).value)
    except (ClubInfo.DoesNotExist, ValueError, TypeError):
        return DEFAULT_MAX_SHIRT_NUMBER


def _synthetic_next_season_end(last_season):
    """ Compute the end date of the season following `last_season` when the
        next Season row hasn't been created yet.

        Uses the configured season end month/day on year = last_season.end.year + 1.
    """
    return date(last_season.end.year + 1, SEASON_END_MONTH, SEASON_END_DAY)


def grace_period_end_for(member, today=None):
    """ Returns the date on which a member's shirt reservation should end if their
        is_current flag is set to False today.

        The reservation runs until the end of the season immediately following
        the season of the member's most recent match appearance. If the member
        has no appearances at all, the returned value is `today` and the caller
        closes the assignment immediately.

        If the "next season" row doesn't exist in the DB yet (common when the
        departing player played in the current season), a synthetic end-date
        is computed from the standard season end month/day.
    """
    if today is None:
        today = timezone.now().date()
    last_appearance = (
        member.appearances
        .select_related('match')
        .order_by('-match__date')
        .first()
    )
    if not last_appearance:
        return today
    try:
        last_season = Season.objects.by_date(last_appearance.match.date)
    except Season.DoesNotExist:
        return today
    next_season = Season.objects.next(last_season)
    if next_season:
        return next_season.end
    return _synthetic_next_season_end(last_season)


class ShirtNumberManager(models.Manager):
    """ Queries that relate to shirt numbers """

    def by_gender(self, gender):
        return self.get_queryset().filter(gender=gender)

    def available(self):
        return self.get_queryset().filter(status=ShirtNumberStatus.Available)

    def unavailable(self):
        return self.get_queryset().filter(status=ShirtNumberStatus.Unavailable)


class ShirtNumber(models.Model):
    """ A single shirt in the club's pool.

        One (number, gender) pair is unique: Male #42 and Female #42 are
        distinct shirts. Status is derived from the current assignment and the
        unavailable_* fields via `recompute_status()`.
    """

    number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0)])
    """ The shirt number (non-negative integer, 0..N where N is configured in ClubInfo) """

    gender = models.CharField(
        max_length=6, choices=Gender.Choices)
    """ The gender category of this shirt (Male/Female) """

    status = models.CharField(
        max_length=12, choices=ShirtNumberStatus.Choices,
        default=ShirtNumberStatus.Available)
    """ The current status of the shirt. Derived; see recompute_status(). """

    unavailable_reason = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Reason the shirt is unavailable (e.g. 'Retired number'). "
                  "Setting a reason marks the shirt as Unavailable until the "
                  "optional end date is reached.")

    unavailable_until = models.DateField(
        null=True, blank=True,
        help_text="Optional end date for the unavailable period. "
                  "When this date has passed, the shirt returns to the pool "
                  "on the next recompute.")

    objects = ShirtNumberManager()

    class Meta:
        app_label = 'members'
        ordering = ('gender', 'number')
        unique_together = ('number', 'gender')

    def __str__(self):
        return "{} #{}".format(self.gender, self.number)

    def current_assignment(self, today=None):
        """ Returns the single active assignment on this shirt, or None.

            Active = end_date is NULL (ongoing) OR end_date >= today (grace
            period not yet elapsed).
        """
        if today is None:
            today = timezone.now().date()
        return (
            self.assignments
            .filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))
            .order_by('-start_date')
            .first()
        )

    def _derive_status(self, today=None):
        """ Pure derivation of the correct status given current DB state. """
        if today is None:
            today = timezone.now().date()
        current = self.current_assignment(today=today)
        if current is not None:
            if current.member.is_current:
                return ShirtNumberStatus.Assigned
            return ShirtNumberStatus.Unavailable
        if self.unavailable_reason:
            if self.unavailable_until is None or self.unavailable_until >= today:
                return ShirtNumberStatus.Unavailable
        return ShirtNumberStatus.Available

    def recompute_status(self, save=True, today=None):
        """ Recomputes the stored status from the ground truth.

            Returns the (old, new) pair so callers can log a correction. If
            `save=True`, writes the new status to the DB when it changes.
        """
        old = self.status
        new = self._derive_status(today=today)
        if new != old:
            self.status = new
            if save and self.pk:
                type(self).objects.filter(pk=self.pk).update(status=new)
        return old, new

    def save(self, *args, **kwargs):
        # Ensure stored status reflects reality on every ORM save.
        self.status = self._derive_status()
        super().save(*args, **kwargs)


class ShirtNumberAssignmentManager(models.Manager):
    """ Queries that relate to shirt number assignments """

    def get_queryset(self):
        return super().get_queryset().select_related('shirt', 'member')

    def by_member(self, member):
        return self.get_queryset().filter(member=member)

    def by_shirt(self, shirt):
        return self.get_queryset().filter(shirt=shirt)

    def active(self, today=None):
        """ Returns all currently active assignments (open or in grace). """
        if today is None:
            today = timezone.now().date()
        return self.get_queryset().filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))

    def current(self):
        """ Returns only truly open assignments (end_date is NULL). """
        return self.get_queryset().filter(end_date__isnull=True)


class ShirtNumberAssignment(models.Model):
    """ Represents a member being assigned a particular shirt.

        An assignment with end_date=NULL is the current one. An assignment
        with end_date in the future represents a departing member whose shirt
        is held in reservation for a grace period. An assignment with end_date
        in the past is historic.
    """

    shirt = models.ForeignKey(
        ShirtNumber, on_delete=models.CASCADE, related_name='assignments')

    member = models.ForeignKey(
        'Member', on_delete=models.CASCADE, related_name='shirt_assignments')

    start_date = models.DateField(default=timezone.now)

    end_date = models.DateField(null=True, blank=True)

    objects = ShirtNumberAssignmentManager()

    class Meta:
        app_label = 'members'
        ordering = ('-start_date',)
        indexes = [models.Index(fields=['shirt', 'end_date'])]

    def __str__(self):
        return "{} ← {} ({})".format(
            self.shirt, self.member,
            "current" if self.end_date is None
            else "until {}".format(self.end_date))

    def is_active(self, today=None):
        if today is None:
            today = timezone.now().date()
        return self.end_date is None or self.end_date >= today

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({
                'end_date': "End date cannot be before start date."
            })
        # Guard every check on shirt_id/member_id — Django's full_clean() still
        # invokes clean() even when clean_fields() already recorded a "required
        # FK missing" error, and accessing self.shirt / self.member on an
        # unsaved blank row would raise RelatedObjectDoesNotExist.
        if not self.shirt_id:
            return
        if self.member_id and self.member.gender != self.shirt.gender:
            raise ValidationError(
                "Shirt gender ({}) must match member gender ({})."
                .format(self.shirt.gender, self.member.gender))

        today = timezone.now().date()
        if self.is_active(today=today):
            # No other active row on the same shirt.
            qs = ShirtNumberAssignment.objects.filter(shirt_id=self.shirt_id).filter(
                models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "Shirt {} is already assigned (or on grace-period hold).".format(self.shirt))
            # No other active row on the same member — one-to-one in both directions.
            if self.member_id:
                qs = ShirtNumberAssignment.objects.filter(member_id=self.member_id).filter(
                    models.Q(end_date__isnull=True) | models.Q(end_date__gte=today))
                if self.pk:
                    qs = qs.exclude(pk=self.pk)
                other = qs.select_related('shirt').first()
                if other is not None:
                    raise ValidationError(
                        "{} already has an active assignment on shirt {}."
                        .format(self.member, other.shirt))

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.shirt.recompute_status(save=True)

    def delete(self, *args, **kwargs):
        shirt = self.shirt
        with transaction.atomic():
            super().delete(*args, **kwargs)
            shirt.recompute_status(save=True)
