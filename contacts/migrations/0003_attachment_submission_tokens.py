from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("contacts", "0002_savedfilter")]
    operations = [
        migrations.AddField(model_name="activity", name="submission_token", field=models.CharField(blank=True, max_length=64, null=True, unique=True)),
        migrations.AddField(model_name="reminder", name="submission_token", field=models.CharField(blank=True, max_length=64, null=True, unique=True)),
        migrations.CreateModel(name="Attachment", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
            ("file", models.FileField(upload_to="attachments/%Y/%m/")),
            ("original_name", models.CharField(max_length=255)),
            ("content_type", models.CharField(blank=True, max_length=120)),
            ("size", models.PositiveIntegerField(default=0)),
            ("activity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attachments", to="contacts.activity")),
        ], options={"ordering": ["created_at"]}),
    ]
