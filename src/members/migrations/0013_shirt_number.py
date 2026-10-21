""" Introduces the ShirtNumber and ShirtNumberAssignment models.

    Operations (in order):
      1. Create the ShirtNumber table.
      2. Create the ShirtNumberAssignment table.
      3. Seed ClubInfo MaxShirtNumberMale/Female (defaults to 170 each).
      4. Populate the shirt pool (1..max) for both genders.
      5. Migrate existing Member.shirt_number data into assignments. Current
         members get an open assignment (end_date=None); non-current members
         get a historic assignment with a plausible prior start_date and an
         end_date of yesterday.
"""

from datetime import date, timedelta

from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.utils import timezone

DEFAULT_MAX = 170


def seed_clubinfo_max(apps, schema_editor):
    ClubInfo = apps.get_model('core', 'ClubInfo')
    for key in ('MaxShirtNumberMale', 'MaxShirtNumberFemale'):
        ClubInfo.objects.get_or_create(key=key, defaults={'value': str(DEFAULT_MAX)})


def delete_clubinfo_max(apps, schema_editor):
    ClubInfo = apps.get_model('core', 'ClubInfo')
    ClubInfo.objects.filter(key__in=('MaxShirtNumberMale', 'MaxShirtNumberFemale')).delete()


def _read_max(ClubInfo, gender):
    key = 'MaxShirtNumberMale' if gender == 'Male' else 'MaxShirtNumberFemale'
    try:
        return int(ClubInfo.objects.get(key=key).value)
    except (ClubInfo.DoesNotExist, ValueError, TypeError):
        return DEFAULT_MAX


def populate_pool(apps, schema_editor):
    ShirtNumber = apps.get_model('members', 'ShirtNumber')
    ClubInfo = apps.get_model('core', 'ClubInfo')
    for gender in ('Male', 'Female'):
        max_n = _read_max(ClubInfo, gender)
        for n in range(0, max_n + 1):
            ShirtNumber.objects.get_or_create(
                number=n, gender=gender,
                defaults={'status': 'Available'})


def delete_pool(apps, schema_editor):
    ShirtNumber = apps.get_model('members', 'ShirtNumber')
    ShirtNumber.objects.all().delete()


def _earliest_activity(member):
    """ Earliest known date the member was active (squad roster or appearance). """
    candidates = []

    sm = member.squadmembership.order_by('season__start').first()
    if sm:
        candidates.append(sm.season.start)

    appearance = member.appearances.select_related('match').order_by('match__date').first()
    if appearance:
        candidates.append(appearance.match.date)

    if member.user_id:
        try:
            joined = member.user.date_joined
            candidates.append(joined.date() if hasattr(joined, 'date') else joined)
        except Exception:
            pass

    return min(candidates) if candidates else None


def _latest_activity(member):
    """ Latest known date the member was active (appearance or squad season end). """
    candidates = []

    sm = member.squadmembership.order_by('-season__end').first()
    if sm:
        candidates.append(sm.season.end)

    appearance = member.appearances.select_related('match').order_by('-match__date').first()
    if appearance:
        candidates.append(appearance.match.date)

    return max(candidates) if candidates else None


def migrate_existing_shirt_numbers(apps, schema_editor):
    Member = apps.get_model('members', 'Member')
    ShirtNumber = apps.get_model('members', 'ShirtNumber')
    ShirtNumberAssignment = apps.get_model('members', 'ShirtNumberAssignment')
    ClubInfo = apps.get_model('core', 'ClubInfo')

    today = date.today()
    yesterday = today - timedelta(days=1)
    fallback_start = today - timedelta(days=365)
    max_by_gender = {g: _read_max(ClubInfo, g) for g in ('Male', 'Female')}
    claimed = set()  # (gender, number) tuples that have an active assignment this migration

    # Process current members first so they win over any historic rows if a
    # non-current member happens to share their shirt number.
    members = sorted(Member.objects.all(), key=lambda m: (not m.is_current, m.pk))

    for member in members:
        raw = (member.shirt_number or '').strip()
        if not raw:
            continue
        try:
            n = int(raw)
        except ValueError:
            print("[0013] Skipping member {} ({}): non-numeric shirt_number {!r}".format(
                member.pk, member.gender, raw))
            continue
        if n < 0 or n > max_by_gender.get(member.gender, DEFAULT_MAX):
            print("[0013] Skipping member {} ({}): shirt_number {} out of range".format(
                member.pk, member.gender, n))
            continue
        try:
            shirt = ShirtNumber.objects.get(number=n, gender=member.gender)
        except ShirtNumber.DoesNotExist:
            print("[0013] Skipping member {} ({}): shirt {} not in pool".format(
                member.pk, member.gender, n))
            continue

        if member.is_current:
            key = (member.gender, n)
            if key in claimed:
                print("[0013] Collision: current member {} wants {} #{} but it's already taken".format(
                    member.pk, member.gender, n))
                continue
            # Infer a plausible start date from their earliest known activity.
            # Fall back to today if the member has no history yet.
            start = _earliest_activity(member) or today
            if start > today:
                start = today
            ShirtNumberAssignment.objects.create(
                shirt=shirt, member=member, start_date=start, end_date=None)
            claimed.add(key)
            ShirtNumber.objects.filter(pk=shirt.pk).update(status='Assigned')
        else:
            # Historic assignment. Overlaps with other historic rows on the same
            # shirt are permitted because the uniqueness rule only applies to
            # active assignments (end_date NULL or in the future).
            start = _earliest_activity(member) or fallback_start
            end = _latest_activity(member) or yesterday
            # Clamp end into the past so the assignment reads as historic.
            if end >= today:
                end = yesterday
            if start > end:
                start = end
            ShirtNumberAssignment.objects.create(
                shirt=shirt, member=member, start_date=start, end_date=end)


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0012_auto_20190108_0657'),
        ('core', '0006_auto_20190917_0745'),
        ('competitions', '0003_auto_20191027_0850'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShirtNumber',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.PositiveSmallIntegerField(validators=[MinValueValidator(0)])),
                ('gender', models.CharField(choices=[('Male', 'Male'), ('Female', 'Female')], max_length=6)),
                ('status', models.CharField(
                    choices=[('Available', 'Available'), ('Assigned', 'Assigned'), ('Unavailable', 'Unavailable')],
                    default='Available', max_length=12)),
                ('unavailable_reason', models.CharField(
                    blank=True, default='', max_length=255,
                    help_text=("Reason the shirt is unavailable (e.g. 'Retired number'). "
                               "Setting a reason marks the shirt as Unavailable until the "
                               "optional end date is reached."))),
                ('unavailable_until', models.DateField(
                    blank=True, null=True,
                    help_text=("Optional end date for the unavailable period. "
                               "When this date has passed, the shirt returns to the pool "
                               "on the next recompute."))),
            ],
            options={
                'ordering': ('gender', 'number'),
                'unique_together': {('number', 'gender')},
            },
        ),
        migrations.CreateModel(
            name='ShirtNumberAssignment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField(default=timezone.now)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('member', models.ForeignKey(
                    on_delete=models.deletion.CASCADE, related_name='shirt_assignments',
                    to='members.Member')),
                ('shirt', models.ForeignKey(
                    on_delete=models.deletion.CASCADE, related_name='assignments',
                    to='members.ShirtNumber')),
            ],
            options={
                'ordering': ('-start_date',),
            },
        ),
        migrations.AddIndex(
            model_name='shirtnumberassignment',
            index=models.Index(fields=['shirt', 'end_date'], name='members_shi_shirt_i_idx'),
        ),
        migrations.RunPython(seed_clubinfo_max, delete_clubinfo_max),
        migrations.RunPython(populate_pool, delete_pool),
        migrations.RunPython(migrate_existing_shirt_numbers, migrations.RunPython.noop),
    ]
