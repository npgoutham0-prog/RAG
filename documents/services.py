"""Document parsing, retrieval, and answer generation."""

import io
import os
import re
import zipfile
from xml.etree import ElementTree

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


class NoRelevantContentError(Exception):
    """Raised when selected documents contain no text matching the question."""


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

    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform([question] + [item[0] for item in candidates])
        scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
    except ValueError:
        return []
    ranked = sorted(
        zip(scores, candidates),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        {"text": chunk, "name": name, "chunk": chunk_number, "score": float(score)}
        for score, (chunk, name, chunk_number) in ranked[:limit]
        if score > 0
    ]


def answer_question(question, documents):
    """Answer using retrieved evidence, returning the answer and source labels."""
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
            "Could not connect to Ollama at http://localhost:11434. "
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
