# NEXUS

NEXUS is a local Django app for uploading documents and asking questions grounded in their contents. The interface is inspired by the attached notebook-style reference: a source library, central chat, and a compact workspace panel.

## Supported documents

PDF, DOCX, Markdown, and plain-text (`.txt`) files are supported. Uploads are limited to 20 MB each. Scanned PDFs without an embedded text layer are not OCR-processed.
You can also add a public HTTP(S) page by URL. NEXUS extracts readable text from static HTML pages and adds it to the source list. Pages that require JavaScript to render their content may not be readable.

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

To use another locally installed Ollama model, such as `llama3.1`, set `OLLAMA_MODEL` before starting Django. If model generation times out, use a smaller model or check that Ollama has enough memory and processing capacity. Uploaded files and extracted text are stored locally in the project directory and SQLite database during local development.

## Deploy to Vercel

Vercel detects Django from the root `manage.py`. The build configuration runs Django migrations, and Vercel collects and serves static files. The app still needs persistent services because Vercel Functions do not provide durable local SQLite or upload storage.

1. Create a Supabase project and a **private** Storage bucket for uploaded documents. Enable its S3-compatible API and allow browser `PUT` requests from your deployed Vercel origin, including the `Content-Type` header.
2. Use the Supabase PostgreSQL connection-pooler URL for `DATABASE_URL`. Use a Supabase S3-compatible endpoint and credentials for uploads.
3. Make an Ollama service reachable from Vercel over HTTPS. Do not use `localhost` or expose an unauthenticated Ollama service to the public internet.
4. Import this GitHub repository into Vercel. Add the environment variables below for Production and Preview, then deploy. Keep all keys and connection strings in Vercel's Environment Variables; never commit them.

Required Vercel environment variables:

| Variable | Value |
| --- | --- |
| `DJANGO_SECRET_KEY` | A long, random secret unique to this deployment |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_ALLOWED_HOSTS` | Your Vercel hostname(s), comma-separated; Vercel deployment hostnames are also detected automatically |
| `DATABASE_URL` | Supabase PostgreSQL pooler connection URL |
| `SUPABASE_S3_ENDPOINT_URL` | The direct Supabase S3 endpoint, for example `https://<project-ref>.storage.supabase.co/storage/v1/s3` |
| `SUPABASE_S3_REGION` | The region configured for the Supabase project |
| `SUPABASE_S3_ACCESS_KEY_ID` | Supabase S3 access key |
| `SUPABASE_S3_SECRET_ACCESS_KEY` | Supabase S3 secret key |
| `SUPABASE_STORAGE_BUCKET_NAME` | The private bucket name |
| `OLLAMA_BASE_URL` | Secure HTTPS URL for the reachable Ollama service |
| `OLLAMA_MODEL` | Model installed on that Ollama service, for example `llama3.2:1b` |
| `OLLAMA_API_KEY` | Optional bearer token if the Ollama endpoint requires one |

If you connect a custom domain, add it to `DJANGO_ALLOWED_HOSTS` and add its HTTPS origin to `DJANGO_CSRF_TRUSTED_ORIGINS`. Generate the S3 access keys in Supabase Storage settings; they grant server-side access across buckets and must only be stored as Vercel environment variables. Supabase direct uploads use short-lived signed URLs. If a browser upload is blocked, check the Supabase Storage CORS configuration for the exact Vercel origin, `PUT`, and `Content-Type`.

Uploaded files are sent directly from the browser to Supabase Storage, avoiding Vercel's 4.5 MB Function request-body limit while retaining the 20 MB per-file limit. URL imports fetch and parse static HTML; JavaScript-rendered websites require a separate browser-based crawler.

**Access warning:** This starter app has no user authentication or per-user data isolation. Anyone who can access the deployed URL can see, add, or delete documents and chat messages. Do not use it for private or sensitive documents until authentication and access controls are added.

## Deploy with Netlify and Render

Netlify does not run this Django application directly. Use Render for the Django server and Netlify as the public URL, proxying requests to the Render service.

1. Connect this repository and the `feature` branch to Render using the root `render.yaml` Blueprint. The Blueprint creates a **free** web service and prompts you for the database, Supabase Storage, Ollama, allowed-host, and CSRF-origin variables. Use the Supabase PostgreSQL and private S3-compatible bucket described above; do not use local SQLite or local file storage for deployed data.
2. Wait for the Render service to deploy. Copy its public `https://<service>.onrender.com` URL.
3. In the Netlify-connected repository, add a `netlify.toml` proxy rewrite for `/*` to `https://<service>.onrender.com/:splat` with status `200` and `force = true`. Replace `<service>` with the actual Render hostname, then deploy the `feature` branch on Netlify. The Netlify site URL must be included in Render's `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` values.
4. Add the Netlify proxy URL to the Supabase Storage CORS allowed origins for browser `PUT` requests with the `Content-Type` header.

The free Render service sleeps after 15 minutes without traffic and can take about a minute to wake. Netlify's proxy requests time out after 26 seconds, so a request that wakes a sleeping service may time out; retry after the service has started. Long-running model responses can also exceed the proxy timeout. For production use, select an always-on backend plan and keep model response times within Netlify's proxy limit.

Keep all credentials in the Render environment settings, not in this repository. The same access warning above applies: this app has no authentication or per-user data isolation.

## Tests

```powershell
python manage.py test documents
```
