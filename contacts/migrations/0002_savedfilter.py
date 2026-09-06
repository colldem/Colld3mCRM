from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("contacts", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="SavedFilter", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=100)),
            ("filters", models.JSONField(default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="crm_saved_filters", to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["name"]}),
        migrations.AddConstraint(model_name="savedfilter", constraint=models.UniqueConstraint(fields=("user", "name"), name="unique_saved_filter_name")),
    ]
