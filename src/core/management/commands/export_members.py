""" Management command for exporting a CSV of members.

    The CSV contains one row per member with their name, gender, shirt
    number, current-member flag and details of their most recent
    appearance (season slug and season start date).

    Usage:
    python manage.py export_members

    Optional arguments:
    --output <path>  : Write the CSV to this path (default: members.csv).
    --stdout         : Write the CSV to stdout instead of a file.
"""

import csv
import sys

from django.core.management.base import BaseCommand
from django.db.models import OuterRef, Subquery

from matches.models import Appearance
from members.models import Member


class Command(BaseCommand):
    help = (
        "Writes a CSV of all members with their details and most recent "
        "appearance information."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            dest='output_path',
            default='members.csv',
            help='Path to write the CSV to. Defaults to "members.csv".',
        )
        parser.add_argument(
            '--stdout',
            action='store_true',
            help='Write the CSV to stdout instead of a file.',
        )

    def handle(self, *args, **options):
        output_path = options['output_path']
        use_stdout = options['stdout']

        fieldnames = [
            'first_name',
            'known_as',
            'last_name',
            'gender',
            'shirt_number',
            'is_current',
            'last_appearance_season_slug',
            'last_appearance_season_start_date',
        ]

        latest_season_slug = Subquery(
            Appearance.objects.filter(member=OuterRef('pk'))
            .order_by('-match__date')
            .values('match__season__slug')[:1]
        )
        latest_season_start = Subquery(
            Appearance.objects.filter(member=OuterRef('pk'))
            .order_by('-match__date')
            .values('match__season__start')[:1]
        )

        members = list(
            Member.objects.annotate(
                last_appearance_season_slug=latest_season_slug,
                last_appearance_season_start_date=latest_season_start,
            ).order_by('last_name', 'first_name')
        )

        if use_stdout:
            output_file = sys.stdout
            close_file = False
        else:
            output_file = open(output_path, 'w', newline='', encoding='utf-8')
            close_file = True

        try:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames)
            writer.writeheader()
            for member in members:
                start_date = member.last_appearance_season_start_date
                writer.writerow({
                    'first_name': member.first_name,
                    'known_as': member.known_as or '',
                    'last_name': member.last_name,
                    'gender': member.get_gender_display(),
                    'shirt_number': member.shirt_number,
                    'is_current': member.is_current,
                    'last_appearance_season_slug': member.last_appearance_season_slug or 'N/A',
                    'last_appearance_season_start_date': start_date.isoformat() if start_date else 'N/A',
                })
        finally:
            if close_file:
                output_file.close()

        if not use_stdout:
            self.stdout.write(
                'Wrote {} members to {}.'.format(len(members), output_path)
            )
