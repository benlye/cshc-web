""" Grants the new ShirtNumber / ShirtNumberAssignment permissions to every
    Group and User that already has `members.change_member`.

    Without this, regular staff who could manage members under the old
    free-text `shirt_number` field suddenly lose access to shirt numbers
    entirely because the auto-generated permissions on the new models aren't
    assigned to any role yet.

    Idempotent: get_or_create for content types and permissions, M2M .add()
    for the grants (which is a no-op on duplicates).
"""

from django.conf import settings
from django.db import migrations


SHIRT_NUMBER_PERMS = (
    ('shirtnumber', 'add_shirtnumber', 'Can add shirt number'),
    ('shirtnumber', 'change_shirtnumber', 'Can change shirt number'),
    ('shirtnumber', 'delete_shirtnumber', 'Can delete shirt number'),
    ('shirtnumberassignment', 'add_shirtnumberassignment', 'Can add shirt number assignment'),
    ('shirtnumberassignment', 'change_shirtnumberassignment', 'Can change shirt number assignment'),
    ('shirtnumberassignment', 'delete_shirtnumberassignment', 'Can delete shirt number assignment'),
)


def grant_shirt_perms(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')

    # Ensure the permissions and their content types exist. Django's
    # post_migrate signal normally creates these, but it fires AFTER all
    # migrations for an app complete, which is too late for a RunPython in
    # the same batch.
    perms = []
    for model_name, codename, name in SHIRT_NUMBER_PERMS:
        ct, _ = ContentType.objects.get_or_create(
            app_label='members', model=model_name)
        perm, _ = Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': name},
        )
        perms.append(perm)

    # Source permission to copy grants from. Fresh installs may not have it
    # yet (no groups configured) — nothing to copy in that case.
    try:
        source = Permission.objects.get(
            codename='change_member',
            content_type__app_label='members',
            content_type__model='member',
        )
    except Permission.DoesNotExist:
        return

    for group in Group.objects.filter(permissions=source):
        group.permissions.add(*perms)

    # Also copy direct user-level permission grants (rare but possible).
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    try:
        User = apps.get_model(app_label, model_name)
    except LookupError:
        return
    for user in User.objects.filter(user_permissions=source):
        user.user_permissions.add(*perms)


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0013_shirt_number'),
        ('auth', '0009_alter_user_last_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(grant_shirt_perms, migrations.RunPython.noop),
    ]
