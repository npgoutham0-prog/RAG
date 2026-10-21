import json
import mimetypes
import zipfile
from uuid import uuid4
from urllib.parse import urlsplit

from botocore.exceptions import ClientError
from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage, UploadedDocument
from .services import (
    MAX_UPLOAD_SIZE,
    NoRelevantContentError,
    SUPPORTED_EXTENSIONS,
    WebCrawlError,
    answer_question,
    crawl_url,
    is_builtin_question,
    read_document,
)


def home(request):
    documents = UploadedDocument.objects.order_by("-uploaded_at")
    messages = ChatMessage.objects.order_by("created_at", "id")
    return render(
        request,
        "documents/home.html",
        {
            "documents": documents,
            "chat_messages": messages,
            "direct_uploads": settings.DIRECT_UPLOADS_ENABLED,
        },
    )


@require_GET
def document_list(_request):
    documents = UploadedDocument.objects.order_by("-uploaded_at")
    return JsonResponse(
        {
            "documents": [
                {
                    "id": document.id,
                    "name": document.name,
                    "uploaded_at": document.uploaded_at.isoformat(),
                }
                for document in documents
            ]
        }
    )


@require_POST
def delete_document(_request, document_id):
    document = UploadedDocument.objects.filter(id=document_id).first()
    if document is None:
        return JsonResponse({"error": "Source not found."}, status=404)
    if document.file:
        document.file.delete(save=False)
    document.delete()
    return JsonResponse({"deleted": True})


@require_POST
def upload_documents(request):
    uploads = request.FILES.getlist("files")
    if not uploads:
        return JsonResponse({"error": "Choose at least one file to upload."}, status=400)

    parsed = []
    for upload in uploads:
        try:
            extracted_text = read_document(upload)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return JsonResponse(
                {"error": f"Could not read {upload.name}: {exc}"},
                status=400,
            )
        parsed.append((upload, extracted_text))

    created = []
    for upload, extracted_text in parsed:
        document = UploadedDocument(
            name=upload.name,
            file=upload,
            extracted_text=extracted_text,
        )
        document.save()
        created.append({"id": document.id, "name": document.name})
    return JsonResponse({"documents": created}, status=201)


@require_POST
def create_direct_upload(request):
    if not settings.DIRECT_UPLOADS_ENABLED:
        return JsonResponse({"error": "Direct uploads are not configured."}, status=503)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Send a valid JSON request."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Send a JSON object with file details."}, status=400)

    name = payload.get("name")
    size = payload.get("size")
    if not isinstance(name, str) or not name.strip():
        return JsonResponse({"error": "Choose a file to upload."}, status=400)
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        return JsonResponse({"error": "The file size is invalid."}, status=400)

    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        name = get_valid_filename(name)
    except SuspiciousFileOperation:
        return JsonResponse({"error": "The file name is invalid."}, status=400)
    if not name or len(name) > 255:
        return JsonResponse({"error": "The file name is invalid or too long."}, status=400)
    extension = f".{name.rsplit('.', 1)[-1].lower()}" if "." in name else ""
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        return JsonResponse(
            {"error": f"Unsupported file type. Use: {supported}."},
            status=400,
        )
    if size > MAX_UPLOAD_SIZE:
        return JsonResponse({"error": "Each file must be 20 MB or smaller."}, status=400)

    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    now = timezone.now()
    key = f"documents/{now:%Y/%m}/{uuid4().hex}_{name}"
    storage = default_storage
    upload_url = storage.connection.meta.client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": storage.bucket_name,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size,
        },
        ExpiresIn=600,
    )
    upload_token = signing.dumps(
        {
            "key": key,
            "name": name,
            "size": size,
            "content_type": content_type,
        },
        salt="documents.direct-upload",
    )
    return JsonResponse(
        {
            "upload_url": upload_url,
            "upload_token": upload_token,
            "content_type": content_type,
        }
    )


@require_POST
def complete_direct_upload(request):
    if not settings.DIRECT_UPLOADS_ENABLED:
        return JsonResponse({"error": "Direct uploads are not configured."}, status=503)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Send a valid JSON request."}, status=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("upload_token"), str):
        return JsonResponse({"error": "A valid upload token is required."}, status=400)

    try:
        upload_data = signing.loads(
            payload["upload_token"],
            salt="documents.direct-upload",
            max_age=900,
        )
    except signing.BadSignature:
        return JsonResponse({"error": "The upload token is invalid or expired."}, status=400)

    if (
        not isinstance(upload_data, dict)
        or not isinstance(upload_data.get("key"), str)
        or not upload_data["key"].startswith("documents/")
        or not isinstance(upload_data.get("name"), str)
        or not isinstance(upload_data.get("size"), int)
        or not isinstance(upload_data.get("content_type"), str)
    ):
        return JsonResponse({"error": "The upload token is invalid."}, status=400)

    existing_document = UploadedDocument.objects.filter(file=upload_data["key"]).first()
    if existing_document is not None:
        return JsonResponse(
            {"id": existing_document.id, "name": existing_document.name},
            status=200,
        )

    storage = default_storage
    client = storage.connection.meta.client
    try:
        object_metadata = client.head_object(
            Bucket=storage.bucket_name,
            Key=upload_data["key"],
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return JsonResponse({"error": "The uploaded file was not found."}, status=400)
        raise

    if (
        object_metadata.get("ContentLength") != upload_data["size"]
        or object_metadata.get("ContentType") != upload_data["content_type"]
    ):
        storage.delete(upload_data["key"])
        return JsonResponse({"error": "The uploaded file did not match its signed details."}, status=400)

    try:
        with storage.open(upload_data["key"], "rb") as stored_file:
            upload = SimpleUploadedFile(
                upload_data["name"],
                stored_file.read(),
                content_type=upload_data["content_type"],
            )
        extracted_text = read_document(upload)
    except ValidationError as exc:
        storage.delete(upload_data["key"])
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        storage.delete(upload_data["key"])
        return JsonResponse(
            {"error": f"Could not read {upload_data['name']}: {exc}"},
            status=400,
        )

    try:
        document = UploadedDocument.objects.create(
            name=upload_data["name"],
            file=upload_data["key"],
            extracted_text=extracted_text,
        )
    except DatabaseError:
        storage.delete(upload_data["key"])
        raise
    return JsonResponse({"id": document.id, "name": document.name}, status=201)


@require_POST
def crawl_document(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Send a valid JSON request."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "Send a JSON object with a URL."}, status=400)
    url = payload.get("url", "")
    if not isinstance(url, str) or not url.strip():
        return JsonResponse({"error": "Enter a URL to crawl."}, status=400)

    try:
        result = crawl_url(url.strip())
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    except WebCrawlError as exc:
        return JsonResponse({"error": str(exc)}, status=422)
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    parsed_url = urlsplit(result["url"])
    name = f"{parsed_url.netloc}{parsed_url.path}".rstrip("/") or parsed_url.netloc
    document = UploadedDocument.objects.create(
        name=name[:255],
        source_url=result["url"],
        extracted_text=result["text"],
    )
    return JsonResponse({"id": document.id, "name": document.name}, status=201)


@require_POST
def chat(request):
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Send a valid JSON request."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "Send a JSON object with your question."}, status=400)
    question = payload.get("question", "")
    if not isinstance(question, str):
        return JsonResponse({"error": "Question must be text."}, status=400)
    question = question.strip()
    document_ids = payload.get("document_ids", [])
    if not question:
        return JsonResponse({"error": "Enter a question first."}, status=400)
    if len(question) > 2000:
        return JsonResponse({"error": "Questions must be 2,000 characters or fewer."}, status=400)
    if not isinstance(document_ids, list):
        return JsonResponse({"error": "Select at least one document."}, status=400)
    if not document_ids and not is_builtin_question(question):
        return JsonResponse({"error": "Select at least one document."}, status=400)
    try:
        ids = [int(document_id) for document_id in document_ids]
    except (TypeError, ValueError):
        return JsonResponse({"error": "Document selection is invalid."}, status=400)

    documents = list(UploadedDocument.objects.filter(id__in=ids))
    if len(documents) != len(set(ids)):
        return JsonResponse(
            {"error": "One or more selected documents are no longer available."},
            status=400,
        )

    try:
        result = answer_question(question, documents)
    except NoRelevantContentError as exc:
        return JsonResponse({"error": str(exc)}, status=422)
    except RuntimeError as exc:
        return JsonResponse({"error": str(exc)}, status=503)

    ChatMessage.objects.create(role=ChatMessage.USER, content=question)
    ChatMessage.objects.create(
        role=ChatMessage.ASSISTANT,
        content=result["answer"],
        sources=result["sources"],
    )
    return JsonResponse(result)


@require_POST
def clear_chat(_request):
    ChatMessage.objects.all().delete()
    return JsonResponse({"cleared": True})
