""" Management command for exporting a CSV of a season's player appearances.

    For each member who has made at least one appearance in the season, the CSV
    contains one column per team they played for (showing the number of games
    they played for that team) and a 'Total' column.

    Usage:
    python manage.py export_season_appearances

    Optional arguments:
    --season <slug>  : Export for the specified season (default: current season).
    --output <path>  : Write the CSV to this path (default: season_appearances.csv).
    --stdout         : Write the CSV to stdout instead of a file.
"""

import csv
import sys
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from competitions.models import Season
from matches.models import Appearance
from teams.models import ClubTeam


class Command(BaseCommand):
    help = (
        "Writes a CSV of all members who played a match in the current "
        "season, with games-played per team and a total column."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--season',
            dest='season_slug',
            help='Season slug (e.g. "2025-2026"). Defaults to the current season.',
        )
        parser.add_argument(
            '--output',
            dest='output_path',
            default='season_appearances.csv',
            help='Path to write the CSV to. Defaults to "season_appearances.csv".',
        )
        parser.add_argument(
            '--stdout',
            action='store_true',
            help='Write the CSV to stdout instead of a file.',
        )

    def handle(self, *args, **options):
        season_slug = options['season_slug']
        output_path = options['output_path']
        use_stdout = options['stdout']

        if season_slug:
            try:
                season = Season.objects.get(slug=season_slug)
            except Season.DoesNotExist:
                raise CommandError('Season "{}" does not exist.'.format(season_slug))
        else:
            season = Season.current()

        appearances = (
            Appearance.objects
            .filter(match__season=season)
            .select_related('member', 'match__our_team')
        )

        counts = defaultdict(lambda: defaultdict(int))
        members = {}
        team_ids_seen = set()
        for appearance in appearances:
            member = appearance.member
            team = appearance.match.our_team
            members[member.pk] = member
            team_ids_seen.add(team.pk)
            counts[member.pk][team.pk] += 1

        teams = list(
            ClubTeam.objects.filter(pk__in=team_ids_seen).order_by('position')
        )

        header = ['Member', 'Shirt number', 'Current member']
        header.extend(team.short_name for team in teams)
        header.append('Total')

        sorted_members = sorted(
            members.values(),
            key=lambda m: (m.pref_first_name().lower(), m.last_name.lower()),
        )

        if use_stdout:
            output_file = sys.stdout
            close_file = False
        else:
            output_file = open(output_path, 'w', newline='', encoding='utf-8-sig')
            close_file = True

        try:
            writer = csv.writer(output_file)
            writer.writerow(header)
            for member in sorted_members:
                member_counts = counts[member.pk]
                row = [
                    member.full_name(),
                    (member.shirt_number or '').strip(),
                    'yes' if member.is_current else 'no',
                ]
                total = 0
                for team in teams:
                    count = member_counts.get(team.pk, 0)
                    row.append(count)
                    total += count
                row.append(total)
                writer.writerow(row)
        finally:
            if close_file:
                output_file.close()

        if not use_stdout:
            self.stdout.write(
                'Wrote appearances for {} members across {} teams ({}) to {}.'.format(
                    len(sorted_members), len(teams), season.slug, output_path,
                )
            )
