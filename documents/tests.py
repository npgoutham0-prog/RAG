from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .models import ChatMessage, UploadedDocument
from .services import (
    NoRelevantContentError,
    WebCrawlError,
    answer_question,
    crawl_url,
    retrieve_relevant_chunks,
    split_into_chunks,
    validate_public_url,
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

    def test_retrieval_handles_large_documents(self):
        document = UploadedDocument(
            name="large-report.pdf",
            extracted_text=(
                "General project information and background details. " * 19000
                + "The rare zephyr battery operates at 840 volts."
            ),
        )

        chunks = split_into_chunks(document.extracted_text)
        results = retrieve_relevant_chunks(
            "What voltage does the rare zephyr battery use?",
            [document],
        )

        self.assertLess(len(chunks), 1000)
        self.assertTrue(results)
        self.assertIn("840 volts", results[0]["text"])

    def test_retrieval_matches_morphological_paraphrases_in_large_documents(self):
        document = UploadedDocument(
            name="large-report.pdf",
            extracted_text=(
                "The battery provides power to the device. " * 12000
                + "This model operates at 840 volts."
            ),
        )

        results = retrieve_relevant_chunks("What is the operating voltage?", [document])

        self.assertTrue(results)
        self.assertIn("840 volts", results[0]["text"])

    def test_nexus_creator_question_uses_builtin_project_information(self):
        with patch("documents.services.ChatOllama") as mock_chat:
            result = answer_question("Who built the NEXUS AI?", [])

        self.assertEqual(
            result,
            {
                "answer": "The NEXUS AI was built by ADARSH & GOUTHAM.",
                "sources": ["NEXUS project information"],
            },
        )
        mock_chat.assert_not_called()

    def test_nexus_overview_question_uses_builtin_project_information(self):
        with patch("documents.services.ChatOllama") as mock_chat:
            result = answer_question("What is Nexus AI?", [])

        for detail in (
            "## What is Nexus AI?",
            "AI-powered intelligent chatbot developed by Adarsh and Goutham",
            "document-based information retrieval with AI-generated answers",
            "## Key features",
            "- AI-powered conversations:",
            "- Document-based question answering:",
            "- Intelligent information retrieval:",
            "- Modern user interface:",
            "- Local AI integration:",
            "- Flexible and extensible design:",
            "## Technologies used",
            "- Python —",
            "- Django —",
            "- HTML, CSS and JavaScript —",
            "- Ollama —",
            "- RAG —",
            "- Embeddings and vector search —",
            "## Project vision",
            "Developed by Adarsh & Goutham.",
        ):
            with self.subTest(detail=detail):
                self.assertIn(detail, result["answer"])
        self.assertEqual(result["sources"], ["NEXUS project information"])
        mock_chat.assert_not_called()

    def test_nexus_feature_and_technology_questions_use_builtin_information(self):
        features = answer_question("What are the key features of Nexus AI?", [])
        technologies = answer_question("What technologies does Nexus AI use?", [])

        self.assertIn("document-based question answering", features["answer"])
        self.assertIn("Ollama", features["answer"])
        self.assertIn("Django", technologies["answer"])
        self.assertIn("embeddings and vector search", technologies["answer"])

    def test_hi_and_hello_get_builtin_greeting_without_model_call(self):
        with patch("documents.services.ChatOllama") as mock_chat:
            for greeting in ("Hi", "hi!", "Hello", "HELLO?"):
                with self.subTest(greeting=greeting):
                    result = answer_question(greeting, [])
                    self.assertEqual(
                        result,
                        {"answer": "Hello what can i do for you ?", "sources": []},
                    )

        mock_chat.assert_not_called()

    def test_thank_you_gets_builtin_response_without_model_call(self):
        with patch("documents.services.ChatOllama") as mock_chat:
            for message in ("Thank you", "thank you!", "THANKS.", "Thanks so much!"):
                with self.subTest(message=message):
                    result = answer_question(message, [])
                    self.assertEqual(
                        result,
                        {"answer": "Happy to help. Take care! 👋", "sources": []},
                    )

        mock_chat.assert_not_called()

    def test_crawl_url_validation_rejects_local_and_non_http_urls(self):
        for url in ("http://localhost/admin", "http://127.0.0.1/", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                validate_public_url(url)

    @patch(
        "documents.services.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.0.0.5", 443))],
    )
    def test_crawl_url_validation_rejects_private_dns_results(self, _getaddrinfo):
        with self.assertRaisesRegex(ValidationError, "publicly accessible"):
            validate_public_url("https://private.example/")

    @patch(
        "documents.services.validate_public_url",
        side_effect=["https://example.com", "https://example.com/article"],
    )
    @patch("documents.services._crawl_with_crawl4ai", new_callable=AsyncMock)
    def test_crawl_extracts_markdown_and_uses_final_page_url(
        self, mock_crawl, _validate_url
    ):
        mock_crawl.return_value = SimpleNamespace(
            success=True,
            url="https://example.com/article",
            markdown=SimpleNamespace(raw_markdown="# Article\nSolar power."),
        )

        result = crawl_url("https://example.com")

        self.assertEqual(
            result,
            {"url": "https://example.com/article", "text": "# Article\nSolar power."},
        )

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
        UploadedDocument.objects.create(name="notes.txt", extracted_text="Project notes.")

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Understand your")
        self.assertContains(response, "Sources")
        self.assertContains(response, 'class="delete-document"')
        self.assertContains(response, 'aria-label="Delete notes.txt"')

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

    def test_delete_document_removes_source(self):
        document = UploadedDocument.objects.create(
            name="notes.txt",
            extracted_text="Project notes.",
        )

        response = self.client.post(f"/api/documents/{document.id}/delete/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted": True})
        self.assertFalse(UploadedDocument.objects.filter(id=document.id).exists())

    def test_delete_document_removes_uploaded_file(self):
        document = UploadedDocument.objects.create(
            name="notes.txt",
            file=SimpleUploadedFile("notes.txt", b"Project notes."),
            extracted_text="Project notes.",
        )
        file_name = document.file.name
        storage = document.file.storage

        response = self.client.post(f"/api/documents/{document.id}/delete/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(storage.exists(file_name))

    def test_delete_document_returns_not_found_for_unknown_id(self):
        response = self.client.post("/api/documents/999999/delete/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "Source not found."})

    @patch(
        "documents.views.crawl_url",
        return_value={
            "url": "https://example.com/research",
            "text": "The project uses solar energy.",
        },
    )
    def test_crawl_adds_website_as_selectable_source(self, mock_crawl):
        response = self.client.post(
            "/api/crawl/",
            data={"url": "https://example.com/research"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        document = UploadedDocument.objects.get()
        self.assertEqual(document.name, "example.com/research")
        self.assertEqual(document.source_url, "https://example.com/research")
        self.assertEqual(document.extracted_text, "The project uses solar energy.")
        self.assertFalse(document.file)
        mock_crawl.assert_called_once_with("https://example.com/research")

    def test_crawl_rejects_localhost_url(self):
        response = self.client.post(
            "/api/crawl/",
            data={"url": "http://localhost/admin"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(UploadedDocument.objects.count(), 0)

    def test_crawl_reports_scrape_failure(self):
        with patch(
            "documents.views.crawl_url",
            side_effect=WebCrawlError("The page could not be read."),
        ):
            response = self.client.post(
                "/api/crawl/",
                data={"url": "https://example.com"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "The page could not be read.")

    def test_crawl_reports_browser_setup_error(self):
        with patch(
            "documents.views.crawl_url",
            side_effect=RuntimeError("Run 'crawl4ai-setup' and try again."),
        ):
            response = self.client.post(
                "/api/crawl/",
                data={"url": "https://example.com"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "Run 'crawl4ai-setup' and try again.")

    @patch(
        "documents.views.answer_question",
        return_value={"answer": "Solar energy.", "sources": ["example.com/research"]},
    )
    def test_chat_can_answer_from_a_crawled_source(self, mock_answer):
        document = UploadedDocument.objects.create(
            name="example.com/research",
            source_url="https://example.com/research",
            extracted_text="The project uses solar energy.",
        )

        response = self.client.post(
            "/api/chat/",
            data={"question": "What energy does the project use?", "document_ids": [document.id]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Solar energy.")
        selected_documents = mock_answer.call_args.args[1]
        self.assertEqual(selected_documents[0].extracted_text, "The project uses solar energy.")

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

    def test_chat_answers_nexus_creator_question_without_selected_documents(self):
        response = self.client.post(
            "/api/chat/",
            data={"question": "who build the NEXUS AI?", "document_ids": []},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "answer": "The NEXUS AI was built by ADARSH & GOUTHAM.",
                "sources": ["NEXUS project information"],
            },
        )
        self.assertEqual(ChatMessage.objects.count(), 2)

    def test_chat_answers_nexus_overview_without_selected_documents(self):
        response = self.client.post(
            "/api/chat/",
            data={"question": "What is Nexus AI?", "document_ids": []},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI-powered intelligent chatbot", response.json()["answer"])
        self.assertIn("Retrieval-Augmented Generation", response.json()["answer"])

    def test_chat_answers_hi_or_hello_without_selected_documents(self):
        for greeting in ("Hi", "Hello"):
            with self.subTest(greeting=greeting):
                response = self.client.post(
                    "/api/chat/",
                    data={"question": greeting, "document_ids": []},
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {"answer": "Hello what can i do for you ?", "sources": []},
                )

    def test_chat_answers_thank_you_without_selected_documents(self):
        response = self.client.post(
            "/api/chat/",
            data={"question": "Thank you!", "document_ids": []},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"answer": "Happy to help. Take care! 👋", "sources": []},
        )

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
