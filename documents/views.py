import json
import zipfile

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage, UploadedDocument
from .services import NoRelevantContentError, answer_question, read_document


def home(request):
    documents = UploadedDocument.objects.order_by("-uploaded_at")
    messages = ChatMessage.objects.order_by("created_at", "id")
    return render(
        request,
        "documents/home.html",
        {"documents": documents, "chat_messages": messages},
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
    if not isinstance(document_ids, list) or not document_ids:
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
