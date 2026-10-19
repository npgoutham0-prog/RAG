from unittest.mock import patch

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import ChatMessage, UploadedDocument
from .services import (
    NoRelevantContentError,
    answer_question,
    retrieve_relevant_chunks,
    split_into_chunks,
)


class DocumentServiceTests(TestCase):
    def test_chunks_are_overlapped_without_losing_text(self):
        text = ("solar energy creates electricity from sunlight. " * 40).strip()
        chunks = split_into_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunks))
        self.assertIn(text[:100], chunks[0])
        self.assertTrue(set(chunks[0].split()) & set(chunks[1].split()))

    def test_retrieval_ranks_matching_document(self):
        relevant = UploadedDocument(
            name="solar.txt",
            extracted_text="Solar panels convert sunlight into electricity using photovoltaic cells.",
        )
        unrelated = UploadedDocument(
            name="cooking.txt",
            extracted_text="A sourdough starter needs flour, water, and regular feeding.",
        )

        results = retrieve_relevant_chunks("How do solar panels generate electricity?", [unrelated, relevant])

        self.assertEqual(results[0]["name"], "solar.txt")

    @patch("documents.services.ChatOllama")
    def test_missing_ollama_is_reported_as_setup_error(self, mock_chat):
        mock_chat.return_value.invoke.side_effect = httpx.ConnectError("offline")
        document = UploadedDocument(
            name="solar.txt",
            extracted_text="Solar panels convert sunlight into electricity using photovoltaic cells.",
        )

        with self.assertRaisesRegex(RuntimeError, "Ollama is running"):
            answer_question("How do solar panels generate electricity?", [document])

    @patch.dict("os.environ", {}, clear=False)
    @patch("documents.services.ChatOllama")
    def test_default_model_and_timeout_message(self, mock_chat):
        import os

        os.environ.pop("OLLAMA_MODEL", None)
        mock_chat.return_value.invoke.side_effect = httpx.ReadTimeout("slow model")
        document = UploadedDocument(
            name="solar.txt",
            extracted_text="Solar panels convert sunlight into electricity using photovoltaic cells.",
        )

        with self.assertRaisesRegex(RuntimeError, "timed out"):
            answer_question("How do solar panels generate electricity?", [document])

        self.assertEqual(mock_chat.call_args.kwargs["model"], "llama3.2:1b")


class DocumentApiTests(TestCase):
    def test_home_renders_workspace(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Understand your")
        self.assertContains(response, "Sources")

    def test_upload_extracts_text_and_lists_source(self):
        upload = SimpleUploadedFile(
            "notes.txt",
            b"These are searchable project notes.",
            content_type="text/plain",
        )

        response = self.client.post("/api/upload/", {"files": upload})

        self.assertEqual(response.status_code, 201)
        document = UploadedDocument.objects.get()
        self.assertEqual(document.extracted_text, "These are searchable project notes.")
        self.assertEqual(self.client.get("/api/documents/").json()["documents"][0]["name"], "notes.txt")

    def test_upload_rejects_unsupported_file(self):
        upload = SimpleUploadedFile("script.exe", b"not a document")

        response = self.client.post("/api/upload/", {"files": upload})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(UploadedDocument.objects.count(), 0)

    @patch("documents.views.answer_question", return_value={"answer": "Sunlight.", "sources": ["notes.txt"]})
    def test_chat_requires_selected_documents_and_saves_exchange(self, mock_answer):
        document = UploadedDocument.objects.create(
            name="notes.txt",
            file=SimpleUploadedFile("notes.txt", b"Sunlight."),
            extracted_text="Sunlight creates electricity.",
        )

        response = self.client.post(
            "/api/chat/",
            data={"question": "What creates electricity?", "document_ids": [document.id]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Sunlight.")
        self.assertEqual(ChatMessage.objects.count(), 2)
        mock_answer.assert_called_once()

    @patch(
        "documents.views.answer_question",
        side_effect=NoRelevantContentError("No relevant text found."),
    )
    def test_chat_reports_no_matching_text_as_unprocessable(self, _answer):
        document = UploadedDocument.objects.create(
            name="notes.txt",
            file=SimpleUploadedFile("notes.txt", b"Bird migration patterns."),
            extracted_text="Bird migration patterns.",
        )

        response = self.client.post(
            "/api/chat/",
            data={"question": "Explain solar panel warranties.", "document_ids": [document.id]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "No relevant text found.")
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_clear_chat_removes_saved_messages(self):
        ChatMessage.objects.create(role=ChatMessage.USER, content="Earlier question")

        response = self.client.post("/api/chat/clear/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 0)
