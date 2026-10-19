from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("api/documents/", views.document_list, name="document-list"),
    path("api/upload/", views.upload_documents, name="document-upload"),
    path("api/chat/", views.chat, name="chat"),
    path("api/chat/clear/", views.clear_chat, name="chat-clear"),
]
