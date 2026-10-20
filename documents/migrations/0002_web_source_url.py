from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="uploadeddocument",
            name="file",
            field=models.FileField(blank=True, upload_to="documents/%Y/%m/"),
        ),
        migrations.AddField(
            model_name="uploadeddocument",
            name="source_url",
            field=models.URLField(blank=True, max_length=2048),
        ),
    ]
