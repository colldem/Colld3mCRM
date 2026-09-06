from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contacts", "0004_activity_company"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedfilter",
            name="scope",
            field=models.CharField(db_index=True, default="contacts", max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name="savedfilter",
            name="unique_saved_filter_name",
        ),
        migrations.AddConstraint(
            model_name="savedfilter",
            constraint=models.UniqueConstraint(fields=("user", "scope", "name"), name="unique_saved_filter_scope_name"),
        ),
    ]
