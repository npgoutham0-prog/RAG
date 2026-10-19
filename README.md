# DocuChat

DocuChat is a local Django app for uploading documents and asking questions grounded in their contents. The interface is inspired by the attached notebook-style reference: a source library, central chat, and a compact workspace panel.

## Supported documents

PDF, DOCX, Markdown, and plain-text (`.txt`) files are supported. Uploads are limited to 20 MB each. Scanned PDFs without an embedded text layer are not OCR-processed.

## Setup

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

Question answering uses the local Ollama model `llama3.2:1b` by default, which is a smaller model and starts more quickly on modest hardware. Install and start Ollama, then pull the model before using chat:

```powershell
ollama pull llama3.2:1b
```

To use another locally installed Ollama model, such as `llama3.1`, set `OLLAMA_MODEL` before starting Django. If model generation times out, use a smaller model or check that Ollama has enough memory and processing capacity. Uploaded files and extracted text are stored locally in the project directory and SQLite database. This starter app is designed for local, single-user use; authentication and production deployment hardening are not included.

## Tests

```powershell
python manage.py test documents
```
