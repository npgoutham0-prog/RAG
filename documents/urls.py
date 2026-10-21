from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("api/documents/", views.document_list, name="document-list"),
    path("api/documents/<int:document_id>/delete/", views.delete_document, name="document-delete"),
    path("api/upload/", views.upload_documents, name="document-upload"),
    path("api/upload/presign/", views.create_direct_upload, name="document-upload-presign"),
    path("api/upload/complete/", views.complete_direct_upload, name="document-upload-complete"),
    path("api/crawl/", views.crawl_document, name="document-crawl"),
    path("api/chat/", views.chat, name="chat"),
    path("api/chat/clear/", views.clear_chat, name="chat-clear"),
]
