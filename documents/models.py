from django.db import models


class UploadedDocument(models.Model):
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/", blank=True)
    source_url = models.URLField(max_length=2048, blank=True)
    extracted_text = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ChatMessage(models.Model):
    USER = "user"
    ASSISTANT = "assistant"
    ROLE_CHOICES = [(USER, "User"), (ASSISTANT, "Assistant")]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
