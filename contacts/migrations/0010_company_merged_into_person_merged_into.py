from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("contacts", "0009_duplicate_settings")]

    operations = [
        migrations.AddField(
            model_name="company",
            name="merged_into",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="merged_companies", to="contacts.company"),
        ),
        migrations.AddField(
            model_name="person",
            name="merged_into",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="merged_people", to="contacts.person"),
        ),
    ]
