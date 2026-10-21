""" Management command for validating current member records.

    Usage:
    python manage.py check_members

    Optional arguments:
    --inactive-seasons <n> : Report current members if they have been inactive for n full completed seasons.
    --include-never-played : Include current members who have never made an appearance.
    --email-to <address> : Override the report recipient for this run only.
    --no-email : Suppress sending email and only write output to the console.
"""

from collections import OrderedDict

from django.conf import settings
from django.core.mail import mail_admins, send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from django.utils import timezone

from competitions.models import Season
from matches.models import Appearance
from members.models import Member, ShirtNumberAssignment
from members.models.shirt_number import get_max_shirt_number


class Command(BaseCommand):
    help = (
        "Checks current members for duplicate shirt numbers and prolonged inactivity, "
        "emailing website admins if any issues are found."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--inactive-seasons',
            dest='inactive_seasons',
            type=int,
            default=2,
            help=(
                "Number of full completed seasons of inactivity required before a member is reported. "
                "Defaults to 2."
            ),
        )
        parser.add_argument(
            '--no-email',
            action='store_true',
            dest='no_email',
            help='Suppress sending email and only write the validation report to the console.',
        )
        parser.add_argument(
            '--include-never-played',
            action='store_true',
            dest='include_never_played',
            help='Include current members who have never made an appearance in the stale-member report.',
        )
        parser.add_argument(
            '--email-to',
            dest='email_to',
            help='Override the recipient email address for this run only.',
        )

    def handle(self, *args, **options):
        inactive_seasons = options['inactive_seasons']
        no_email = options['no_email']
        include_never_played = options['include_never_played']
        email_to = options['email_to']
        if inactive_seasons < 1:
            raise CommandError('--inactive-seasons must be at least 1')
        if no_email and email_to:
            raise CommandError('--email-to cannot be used with --no-email')

        current_members = Member.objects.filter(is_current=True)
        duplicate_numbers = self.get_duplicate_shirt_numbers()
        multi_shirt_members = self.get_members_with_multiple_shirts()
        over_max_shirts = self.get_shirts_above_max()
        activity_seasons = self.get_activity_seasons(inactive_seasons)
        inactive_members = self.get_inactive_members(
            current_members,
            activity_seasons,
            include_never_played=include_never_played,
        )

        self.write_console_summary(
            current_members.count(),
            duplicate_numbers,
            multi_shirt_members,
            over_max_shirts,
            inactive_members,
            activity_seasons,
            include_never_played=include_never_played,
        )

        if duplicate_numbers or multi_shirt_members or over_max_shirts or inactive_members:
            report = self.build_report(
                current_members.count(),
                inactive_seasons,
                activity_seasons,
                duplicate_numbers,
                multi_shirt_members,
                over_max_shirts,
                inactive_members,
                include_never_played=include_never_played,
            )
            if no_email:
                self.stdout.write('Validation issues found. Email suppressed by --no-email.')
                self.stdout.write(report)
            elif email_to:
                send_mail(
                    'Member validation issues detected',
                    report,
                    settings.SERVER_EMAIL,
                    [email_to],
                )
                self.stdout.write('Validation report emailed to {}.'.format(email_to))
            else:
                mail_admins('Member validation issues detected', report)
                self.stdout.write('Validation report emailed to website admins.')
        else:
            self.stdout.write('No validation issues found. No email sent.')

    def get_duplicate_shirt_numbers(self):
        """ Integrity probe: shirts with more than one active assignment.

            Should normally return nothing — a hit means the save/clean
            enforcement in ShirtNumberAssignment was bypassed.
        """
        today = timezone.now().date()
        active = ShirtNumberAssignment.objects.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today))
        offenders = (
            active.values('shirt').annotate(c=Count('id')).filter(c__gt=1)
            .values_list('shirt', flat=True)
        )
        groups = OrderedDict()
        for assignment in active.filter(shirt__in=list(offenders)).select_related('shirt', 'member'):
            key = (assignment.shirt.gender, assignment.shirt.number)
            groups.setdefault(key, []).append(assignment.member)
        return OrderedDict(sorted(groups.items()))

    def get_members_with_multiple_shirts(self):
        """ Integrity probe: members with more than one active assignment.

            Should normally return nothing — a hit means the save/clean
            enforcement in ShirtNumberAssignment was bypassed.
        """
        today = timezone.now().date()
        active = ShirtNumberAssignment.objects.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today))
        offenders = (
            active.values('member').annotate(c=Count('id')).filter(c__gt=1)
            .values_list('member', flat=True)
        )
        groups = OrderedDict()
        for assignment in active.filter(member__in=list(offenders)).select_related('shirt', 'member'):
            groups.setdefault(assignment.member, []).append(assignment.shirt)
        return groups

    def get_shirts_above_max(self):
        """ Active shirts whose number exceeds the current ClubInfo max for their gender. """
        today = timezone.now().date()
        active = ShirtNumberAssignment.objects.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today),
        ).select_related('shirt', 'member')

        offenders = []
        for assignment in active:
            max_n = get_max_shirt_number(assignment.shirt.gender)
            if assignment.shirt.number > max_n:
                offenders.append((assignment.shirt, assignment.member, max_n))
        offenders.sort(key=lambda row: (row[0].gender, row[0].number))
        return offenders

    def get_activity_seasons(self, completed_season_count):
        seasons = []
        season = Season.current()

        while season is not None and len(seasons) < completed_season_count + 1:
            seasons.append(season)
            season = Season.objects.previous(season)

        return seasons

    def get_inactive_members(self, current_members, activity_seasons, include_never_played=False):
        today = timezone.now().date()
        recent_member_ids = set(Appearance.objects.filter(
            member__is_current=True,
            match__season__in=activity_seasons,
            match__date__lte=today,
        ).values_list('member_id', flat=True).distinct())

        inactive_members = list(current_members.exclude(pk__in=recent_member_ids))
        if not inactive_members:
            return []

        last_appearance_by_member = {}
        appearances = Appearance.objects.filter(
            member__in=inactive_members,
            match__date__lte=today,
        ).select_related('member', 'match__season').order_by('member_id', '-match__season__start', '-match__date')

        for appearance in appearances:
            if appearance.member_id not in last_appearance_by_member:
                last_appearance_by_member[appearance.member_id] = appearance.match.season.slug

        members_with_last_appearance = [
            (member, last_appearance_by_member.get(member.pk))
            for member in inactive_members
        ]

        if include_never_played:
            return members_with_last_appearance

        return [
            (member, last_season)
            for member, last_season in members_with_last_appearance
            if last_season is not None
        ]

    def write_console_summary(
            self,
            member_count,
            duplicate_numbers,
            multi_shirt_members,
            over_max_shirts,
            inactive_members,
            activity_seasons,
            include_never_played=False):
        self.stdout.write('Checked {} current members.'.format(member_count))

        if duplicate_numbers:
            self.stdout.write('Found {} duplicate shirt number assignments.'.format(len(duplicate_numbers)))
            for (gender, shirt_number), members in duplicate_numbers.items():
                self.stdout.write(
                    '  {} shirt {}: {}'.format(
                        gender,
                        shirt_number,
                        ', '.join(member.full_name() for member in members),
                    )
                )
        else:
            self.stdout.write('No duplicate shirt numbers found.')

        if multi_shirt_members:
            self.stdout.write(
                'Found {} members holding multiple active shirts.'.format(len(multi_shirt_members)))
            for member, shirts in multi_shirt_members.items():
                self.stdout.write(
                    '  {}: {}'.format(
                        member.full_name(),
                        ', '.join(str(s) for s in shirts),
                    )
                )
        else:
            self.stdout.write('No members with multiple active shirts.')

        if over_max_shirts:
            self.stdout.write(
                'Found {} active shirts above the current ClubInfo max:'.format(len(over_max_shirts)))
            for shirt, member, max_n in over_max_shirts:
                self.stdout.write(
                    '  {} #{} (max {}): {}'.format(shirt.gender, shirt.number, max_n, member.full_name()))
        else:
            self.stdout.write('No shirts in use above the configured max.')

        season_list = ', '.join(season.slug for season in activity_seasons)
        never_played_suffix = ' (including never-played members)' if include_never_played else ''
        if inactive_members:
            self.stdout.write(
                'Found {} inactive current members with no appearances in: {}{}.'.format(
                    len(inactive_members),
                    season_list,
                    never_played_suffix,
                )
            )
            for member, last_season in inactive_members:
                self.stdout.write(
                    '  {}'.format(self.format_inactive_member(member, last_season))
                )
        else:
            self.stdout.write(
                'No inactive current members found when checking seasons: {}{}.'.format(
                    season_list,
                    never_played_suffix,
                )
            )

    def build_report(
            self,
            member_count,
            inactive_seasons,
            activity_seasons,
            duplicate_numbers,
            multi_shirt_members,
            over_max_shirts,
            inactive_members,
            include_never_played=False):
        lines = [
            'Member validation report',
            '',
            'Current members checked: {}'.format(member_count),
            'Inactive completed season threshold: {}'.format(inactive_seasons),
            'Seasons checked for recent activity: {}'.format(', '.join(season.slug for season in activity_seasons)),
            'Include never-played members: {}'.format('yes' if include_never_played else 'no'),
            '',
        ]

        if duplicate_numbers:
            lines.append('### Duplicate shirt numbers ###')
            lines.append('Action: investigate these duplicate shirt numbers and resolve any incorrect assignments.')
            lines.append('')
            for (gender, shirt_number), members in duplicate_numbers.items():
                lines.append(
                    '{} shirt {}: {}'.format(
                        gender,
                        shirt_number,
                        ', '.join(member.full_name() for member in members),
                    )
                )
            lines.append('')

        if multi_shirt_members:
            lines.append('### Members holding multiple active shirts ###')
            lines.append('Action: review these members and end whichever assignments are no longer current.')
            lines.append('')
            for member, shirts in multi_shirt_members.items():
                lines.append('{}: {}'.format(
                    member.full_name(),
                    ', '.join(str(s) for s in shirts),
                ))
            lines.append('')

        if over_max_shirts:
            lines.append('### Shirts above configured max ###')
            lines.append('Action: either raise the ClubInfo MaxShirtNumber* value, or reassign these members.')
            lines.append('')
            for shirt, member, max_n in over_max_shirts:
                lines.append('{} #{} (max {}): {}'.format(
                    shirt.gender, shirt.number, max_n, member.full_name()))
            lines.append('')

        if inactive_members:
            lines.append('### Inactive current members ###')
            lines.append('Action: review these members and unset "current" for anyone who is no longer a current player.')
            lines.append('')
            for member, last_season in inactive_members:
                lines.append(self.format_inactive_member(member, last_season))

            lines.append('')

        return '\n'.join(lines)

    def format_inactive_member(self, member, last_season):
        assignment = member.current_shirt_number()
        if assignment is None:
            shirt = '-'
        elif assignment.end_date is not None:
            shirt = '{} (grace until {})'.format(assignment.shirt.number, assignment.end_date)
        else:
            shirt = str(assignment.shirt.number)
        return '{} (shirt: {}; last appearance: {})'.format(
            member.full_name(),
            shirt,
            last_season or 'never',
        )
