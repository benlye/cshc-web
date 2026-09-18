from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0012_auto_20190108_0657'),
    ]

    operations = [
        migrations.AddField(
            model_name='member',
            name='anonymous',
            field=models.BooleanField(default=False, help_text="If set, this member is shown as 'Anonymous Player' on the public website", verbose_name='Anonymous'),
        ),
    ]
