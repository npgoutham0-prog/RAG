"""Document parsing, retrieval, and answer generation."""

import ipaddress
import io
import os
import re
import socket
import zipfile
from xml.etree import ElementTree
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx
from django.core.exceptions import ValidationError
from langchain_ollama import ChatOllama
from ollama import ResponseError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
MAX_CRAWL_URL_LENGTH = 2048
MAX_CRAWLED_TEXT_LENGTH = 1_000_000
MAX_CRAWL_RESPONSE_SIZE = 5 * 1024 * 1024
MAX_CRAWL_REDIRECTS = 5
NEXUS_CREATOR_ANSWER = "The NEXUS AI was built by ADARSH & GOUTHAM."
NEXUS_OVERVIEW_ANSWER = (
    "## What is Nexus AI?\n"
    "Nexus AI is an AI-powered intelligent chatbot developed by Adarsh and "
    "Goutham to make information easier to access, understand, and explore. "
    "It is designed to interact with users through natural language, answer "
    "questions, retrieve relevant information from documents, and generate "
    "meaningful responses using Artificial Intelligence (AI).\n\n"
    "Nexus AI uses Retrieval-Augmented Generation (RAG) to combine "
    "document-based information retrieval with AI-generated answers. This "
    "enables users to ask questions about their uploaded documents and "
    "receive relevant, context-aware responses. By integrating a language "
    "model with a document retrieval system, Nexus AI aims to provide a "
    "smarter and more useful information assistant.\n\n"
    "## Key features\n"
    "- AI-powered conversations: Interacts with users and responds to "
    "questions in natural language.\n"
    "- Document-based question answering: Retrieves relevant information "
    "from uploaded documents using RAG.\n"
    "- Intelligent information retrieval: Finds useful content related to "
    "the user's query.\n"
    "- Modern user interface: Provides a clean, interactive, and user-friendly "
    "chatting experience.\n"
    "- Local AI integration: Can use Ollama to run supported language models "
    "locally.\n"
    "- Flexible and extensible design: Can be expanded with additional AI "
    "capabilities and features.\n\n"
    "## Technologies used\n"
    "- Python — Core programming and AI logic.\n"
    "- Django — Backend development and request handling.\n"
    "- HTML, CSS and JavaScript — Interactive frontend and user experience.\n"
    "- Ollama — Local language model execution.\n"
    "- RAG — Document retrieval and context-aware response generation.\n"
    "- Embeddings and vector search — Finding relevant information within "
    "documents.\n\n"
    "## Project vision\n"
    "Our vision is to build an intelligent, accessible, and efficient AI "
    "assistant that connects users with the information they need. Nexus AI "
    "aims to bring together conversational AI and document intelligence in "
    "one platform.\n\n"
    "Developed by Adarsh & Goutham."
)
NEXUS_RAG_ANSWER = (
    "Nexus AI uses Retrieval-Augmented Generation (RAG): it searches selected "
    "documents for relevant passages, then provides those passages to a "
    "language model so it can generate a context-aware answer grounded in "
    "the documents."
)
NEXUS_FEATURES_ANSWER = (
    "Nexus AI features natural-language conversations, document-based "
    "question answering with RAG, intelligent information retrieval, a "
    "modern interactive interface, local language-model integration through "
    "Ollama, and an extensible design for additional AI capabilities."
)
NEXUS_TECHNOLOGIES_ANSWER = (
    "Nexus AI uses Python for its core logic, Django for its backend, HTML, "
    "CSS, and JavaScript for its interface, Ollama for local language-model "
    "execution, and Retrieval-Augmented Generation (RAG) with embeddings "
    "and vector search for document retrieval."
)
NEXUS_VISION_ANSWER = (
    "The vision for Nexus AI is to build an intelligent, accessible, and "
    "efficient assistant that connects people with the information they "
    "need by bringing conversational AI and document intelligence together."
)
GREETING_ANSWER = "Hello what can i do for you ?"
THANK_YOU_ANSWER = "Happy to help. Take care! 👋"


class NoRelevantContentError(Exception):
    """Raised when selected documents contain no text matching the question."""


class WebCrawlError(Exception):
    """Raised when Crawl4AI cannot extract readable page content."""


def is_greeting(question):
    """Return whether the message is a simple hi or hello greeting."""
    normalized = re.sub(r"[^\w\s]", "", question.lower()).strip()
    return normalized in {"hi", "hello"}


def is_thank_you(question):
    """Return whether the message is a simple expression of thanks."""
    normalized = re.sub(r"[^\w\s]", "", question.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized in {"thank you", "thanks", "thank you so much", "thanks so much"}


def nexus_project_answer(question):
    """Return built-in Nexus project information for recognized questions."""
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    if not re.search(r"\bnexus\b", normalized):
        return None

    if re.search(
        r"\b(build|built|builder|builders|create|created|creator|creators|"
        r"develop|developed|developer|developers|founder|founders|founded|made)\b",
        normalized,
    ):
        return NEXUS_CREATOR_ANSWER
    if re.search(r"\b(feature|features|capability|capabilities)\b", normalized):
        return NEXUS_FEATURES_ANSWER
    if re.search(r"\b(technology|technologies|tech stack|framework|language)\b", normalized):
        return NEXUS_TECHNOLOGIES_ANSWER
    if re.search(r"\b(vision|goal|goals|purpose)\b", normalized):
        return NEXUS_VISION_ANSWER
    if re.search(r"\b(rag|retrieval|how does .* work|how .* work)\b", normalized):
        return NEXUS_RAG_ANSWER
    if re.search(r"\b(what is|what's|who is|tell me about|describe|about)\b", normalized):
        return NEXUS_OVERVIEW_ANSWER
    return None


def is_nexus_knowledge_question(question):
    """Return whether a question can be answered from built-in Nexus facts."""
    return nexus_project_answer(question) is not None


def is_builtin_question(question):
    """Return whether a question can be answered without document sources."""
    return (
        is_greeting(question)
        or is_thank_you(question)
        or is_nexus_knowledge_question(question)
    )


def validate_public_url(url):
    """Validate an HTTP(S) URL and reject hosts that resolve to non-public IPs."""
    if len(url) > MAX_CRAWL_URL_LENGTH:
        raise ValidationError("URLs must be 2,048 characters or fewer.")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Enter a valid public HTTP or HTTPS URL.") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValidationError("Enter a valid public HTTP or HTTPS URL.")

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
            raise ValidationError("Only publicly accessible websites can be crawled.")
        try:
            addresses = {
                ipaddress.ip_address(address[4][0])
                for address in socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80))
            }
        except (OSError, ValueError) as exc:
            raise ValidationError("The website hostname could not be resolved.") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise ValidationError("Only publicly accessible websites can be crawled.")
    return url


def crawl_url(url):
    """Fetch a public HTML page and return readable text without a browser."""
    current_url = validate_public_url(url)
    try:
        with httpx.Client(
            follow_redirects=False,
            headers={"User-Agent": "NEXUS-document-crawler/1.0"},
            timeout=httpx.Timeout(20.0, connect=5.0),
        ) as client:
            for redirect_count in range(MAX_CRAWL_REDIRECTS + 1):
                with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise WebCrawlError("The website returned an invalid redirect.")
                        if redirect_count == MAX_CRAWL_REDIRECTS:
                            raise WebCrawlError("The website redirected too many times.")
                        current_url = validate_public_url(urljoin(current_url, location))
                        continue

                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise WebCrawlError(
                            f"The website returned HTTP {response.status_code}."
                        ) from exc

                    content_type = response.headers.get("content-type", "").lower()
                    if not any(
                        media_type in content_type
                        for media_type in ("text/html", "application/xhtml+xml", "text/plain")
                    ):
                        raise WebCrawlError("The URL did not return an HTML or plain-text page.")

                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_CRAWL_RESPONSE_SIZE:
                            raise WebCrawlError("The website response is too large to crawl.")
                    page_content = bytes(content).decode(
                        response.encoding or "utf-8",
                        errors="replace",
                    )
                    if "text/plain" in content_type:
                        text = page_content.strip()
                    else:
                        soup = BeautifulSoup(page_content, "html.parser")
                        for element in soup.select("script, style, noscript, template, svg"):
                            element.decompose()
                        content_element = soup.find("main") or soup.body or soup
                        text = content_element.get_text(separator="\n", strip=True)
                    break
            else:
                raise WebCrawlError("The website redirected too many times.")
    except httpx.TimeoutException as exc:
        raise WebCrawlError("The website took too long to respond.") from exc
    except httpx.RequestError as exc:
        raise WebCrawlError(f"The website could not be fetched: {exc}") from exc

    text = text.strip()
    if not text:
        raise WebCrawlError("No readable page content was found at this URL.")
    if len(text) > MAX_CRAWLED_TEXT_LENGTH:
        raise WebCrawlError("The page contains too much text to add as a source.")
    return {"url": current_url, "text": text}


def read_document(upload):
    """Extract readable text from one supported uploaded document."""
    suffix = os.path.splitext(upload.name)[1].lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValidationError(f"Unsupported file type. Use: {supported}.")
    if upload.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Each file must be 20 MB or smaller.")

    content = upload.read()
    if suffix == ".pdf":
        try:
            pages = PdfReader(io.BytesIO(content)).pages
            text = "\n\n".join(page.extract_text() or "" for page in pages)
        except PdfReadError as exc:
            raise ValidationError(f"{upload.name} is not a readable PDF.") from exc
    elif suffix == ".docx":
        text = _read_docx(content)
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("Text documents must use UTF-8 encoding.") from exc

    text = text.strip()
    if not text:
        raise ValidationError(f"No readable text was found in {upload.name}.")
    return text


def _read_docx(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = ElementTree.fromstring(archive.read("word/document.xml"))

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in xml.findall(".//w:p", namespace):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        if parts:
            paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def split_into_chunks(text):
    """Split extracted text into overlapping chunks suitable for retrieval."""
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_SIZE, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def retrieve_relevant_chunks(question, documents, limit=4):
    """Return the most relevant extracted text chunks with their source names."""
    candidates = []
    for document in documents:
        candidates.extend(
            (chunk, document.name, index + 1)
            for index, chunk in enumerate(split_into_chunks(document.extracted_text))
        )
    if not candidates:
        return []

    texts = [item[0] for item in candidates]
    try:
        word_vectorizer = TfidfVectorizer(stop_words="english")
        word_matrix = word_vectorizer.fit_transform([question] + texts)
        word_scores = cosine_similarity(word_matrix[0:1], word_matrix[1:]).ravel()

        char_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            max_features=100_000,
        )
        char_matrix = char_vectorizer.fit_transform([question] + texts)
        char_scores = cosine_similarity(char_matrix[0:1], char_matrix[1:]).ravel()
    except ValueError:
        return []

    scores = word_scores + char_scores
    ranked = sorted(
        zip(scores, word_scores, char_scores, candidates),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        {"text": chunk, "name": name, "chunk": chunk_number, "score": float(score)}
        for score, word_score, char_score, (chunk, name, chunk_number) in ranked
        if word_score > 0 or char_score >= 0.08
    ][:limit]


def answer_question(question, documents):
    """Answer using retrieved evidence, returning the answer and source labels."""
    if is_greeting(question):
        return {"answer": GREETING_ANSWER, "sources": []}
    if is_thank_you(question):
        return {"answer": THANK_YOU_ANSWER, "sources": []}

    project_answer = nexus_project_answer(question)
    if project_answer:
        return {
            "answer": project_answer,
            "sources": ["NEXUS project information"],
        }

    matches = retrieve_relevant_chunks(question, documents)
    if not matches:
        raise NoRelevantContentError(
            "I couldn't find relevant text in the selected documents. "
            "Try another question or select a document with searchable text."
        )

    context = "\n\n".join(
        f"[Source: {item['name']}, section {item['chunk']}]\n{item['text']}"
        for item in matches
    )
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ollama_api_key = os.environ.get("OLLAMA_API_KEY")
    client_kwargs = (
        {"headers": {"Authorization": f"Bearer {ollama_api_key}"}}
        if ollama_api_key
        else {}
    )
    prompt = (
        "You answer questions using only the supplied document excerpts. "
        "If the excerpts do not contain the answer, say that you do not know. "
        "Keep the answer clear and concise and cite source names in brackets.\n\n"
        f"Document excerpts:\n{context}\n\n"
        f"Question: {question}\n"
        "Answer:"
    )
    try:
        response = ChatOllama(
            model=model,
            base_url=ollama_base_url,
            client_kwargs=client_kwargs,
            temperature=0,
            sync_client_kwargs={"timeout": httpx.Timeout(120.0, connect=5.0)},
        ).invoke(prompt)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Ollama model '{model}' timed out while generating an answer. "
            "Try a smaller model such as 'llama3.2:1b' or check that Ollama "
            "has enough memory and processing capacity."
        ) from exc
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Could not connect to Ollama at {ollama_base_url}. "
            "Make sure Ollama is running."
        ) from exc
    except ResponseError as exc:
        raise RuntimeError(
            f"Ollama could not run model '{model}': {exc}. "
            "Confirm the model is installed with 'ollama list'."
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Could not communicate with Ollama for model '{model}': {exc}"
        ) from exc

    source_names = list(dict.fromkeys(item["name"] for item in matches))
    return {"answer": str(response.content).strip(), "sources": source_names}
