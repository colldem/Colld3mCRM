from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("contacts", "0003_attachment_submission_tokens")]

    operations = [
        migrations.AlterField(
            model_name="activity",
            name="person",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="activities", to="contacts.person"),
        ),
        migrations.AddField(
            model_name="activity",
            name="company",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="activities", to="contacts.company"),
        ),
    ]
