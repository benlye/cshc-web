""" Reconciles the shirt-number pool with the configured ClubInfo max per gender,
    and recomputes stored status against the derived truth for every shirt.

    Usage:
      python manage.py sync_shirt_pool          # fix and report
      python manage.py sync_shirt_pool --check  # report only; exit non-zero if any discrepancy

    This is idempotent and safe to run at any time.
"""

import sys

from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from core.models import Gender
from members.models import ShirtNumber, ShirtNumberAssignment
from members.models.shirt_number import get_max_shirt_number


class Command(BaseCommand):
    help = (
        "Ensures the ShirtNumber pool matches the configured ClubInfo max per gender, "
        "and reconciles every shirt's stored status against the derived truth."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--check',
            action='store_true',
            dest='check_only',
            help='Report discrepancies without applying fixes. Exit non-zero if any are found.',
        )

    def handle(self, *args, **options):
        check_only = options['check_only']
        today = timezone.now().date()

        discrepancies = 0

        # 1. Extend the pool up to the current ClubInfo max for each gender.
        for gender in (Gender.Male, Gender.Female):
            max_n = get_max_shirt_number(gender)
            existing = set(
                ShirtNumber.objects.filter(gender=gender)
                .values_list('number', flat=True)
            )
            missing = [n for n in range(0, max_n + 1) if n not in existing]
            if missing:
                discrepancies += len(missing)
                self.stdout.write(
                    "{} missing {} rows for {}: {}".format(
                        "Would create" if check_only else "Creating",
                        len(missing), gender, missing))
                if not check_only:
                    for n in missing:
                        ShirtNumber.objects.create(number=n, gender=gender)

        # 2. Reconcile stored status against derived truth for every shirt.
        for shirt in ShirtNumber.objects.all().order_by('gender', 'number'):
            old, new = shirt.recompute_status(save=not check_only, today=today)
            if old != new:
                discrepancies += 1
                self.stdout.write(
                    "{} #{}: {} -> {} ({})".format(
                        shirt.gender, shirt.number, old, new,
                        "would fix" if check_only else "fixed"))

        # 3. Report any shirt whose number is above the configured max.
        for gender in (Gender.Male, Gender.Female):
            max_n = get_max_shirt_number(gender)
            over = ShirtNumber.objects.filter(gender=gender, number__gt=max_n).order_by('number')
            for shirt in over:
                active = shirt.current_assignment(today=today)
                if active:
                    discrepancies += 1
                    self.stdout.write(
                        "{} #{} is above the configured max ({}); currently held by {}".format(
                            shirt.gender, shirt.number, max_n, active.member.full_name()))

        # 4. Report shirts with more than one active assignment.
        active_qs = ShirtNumberAssignment.objects.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today))
        shirt_offenders = (
            active_qs.values('shirt').annotate(c=Count('id')).filter(c__gt=1)
            .values_list('shirt', flat=True)
        )
        for shirt_id in shirt_offenders:
            discrepancies += 1
            holders = active_qs.filter(shirt_id=shirt_id).select_related('shirt', 'member')
            self.stdout.write(
                "Shirt {} has {} active assignments: {}".format(
                    holders.first().shirt,
                    holders.count(),
                    ', '.join(a.member.full_name() for a in holders)))

        # 5. Report members with more than one active assignment.
        member_offenders = (
            active_qs.values('member').annotate(c=Count('id')).filter(c__gt=1)
            .values_list('member', flat=True)
        )
        for member_id in member_offenders:
            discrepancies += 1
            held = active_qs.filter(member_id=member_id).select_related('shirt', 'member')
            self.stdout.write(
                "Member {} holds {} active shirts: {}".format(
                    held.first().member.full_name(),
                    held.count(),
                    ', '.join(str(a.shirt) for a in held)))

        self.stdout.write('')
        if discrepancies == 0:
            self.stdout.write("Shirt pool is in sync; no discrepancies.")
        else:
            self.stdout.write("{} discrepanc{} found.".format(
                discrepancies, 'y' if discrepancies == 1 else 'ies'))
            if check_only:
                sys.exit(1)
