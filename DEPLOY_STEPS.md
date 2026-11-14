# Deployment

Deploy the API to a Hugging Face Docker Space, use Neon for PostgreSQL with pgvector,
and deploy the React frontend to Vercel. No secret values belong in this file or in
the repository.

## Environment variable names

Set these in the Hugging Face Space settings:

- `APP_ENV`
- `APP_DEBUG`
- `APP_SECRET_KEY`
- `DATABASE_URL`
- `STORAGE_PROVIDER`
- `ALLOWED_ORIGINS`
- `JWT_ALGORITHM`
- `JWT_EXPIRE_MINUTES`
- `MAX_UPLOAD_SIZE_MB`
- `STT_PROVIDER`
- `TTS_PROVIDER`
- `VOICE_CLONE_PROVIDER`
- `GNANI_API_KEY`
- `GNANI_PRISMA_ENDPOINT`
- `GNANI_TIMBRE_ENDPOINT`
- `GNANI_VOICE_CLONE_ENDPOINT`
- `GNANI_TTS_MODEL`
- `GNANI_TTS_VOICE`
- `VOICE_CLONE_MAX_PROFILES`
- `VOICE_CLONE_CREATE_RATE_LIMIT`
- `VOICE_CLONE_PREVIEW_RATE_LIMIT`
- `VOICE_CLONE_RATE_WINDOW_SECONDS`
- `LLM_PROVIDER`
- `LLM_MODEL`
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `EMBEDDING_MODEL`
- `SIMILARITY_THRESHOLD`
- `RAG_DEBUG`
- `GNANI_EVON_ENDPOINT`

`GNANI_API_KEY` is needed when real Gnani services are selected. Set the key for
the selected LLM provider (`GEMINI_API_KEY` or `OPENAI_API_KEY`). `GNANI_TIMBRE_ENDPOINT`,
`GNANI_VOICE_CLONE_ENDPOINT`, `GNANI_TTS_MODEL`, `GNANI_TTS_VOICE`,
`EMBEDDING_MODEL`, `SIMILARITY_THRESHOLD`, and `RAG_DEBUG` have application defaults
and only need to be set when overriding them.

Set `VITE_API_URL` in the Vercel project to the backend origin. Add the exact
Vercel origin to `ALLOWED_ORIGINS`. The frontend calls the backend directly, so no
Vercel API proxy or local-disk audio store is required.

Vercel environment variable: `VITE_API_URL`

The legacy `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and
`DATABASE_PASSWORD` settings are only a development fallback. A non-empty
`DATABASE_URL` takes precedence over all of them.

## Prepare Neon

Create a Neon PostgreSQL database with the `vector` extension available. Use its
pooled or direct connection string as `DATABASE_URL`; the application accepts
either `postgres://` or `postgresql://` URLs. Set `STORAGE_PROVIDER` to `database`
for the Space so document uploads survive container restarts.

## Push the backend Space

Install the Hugging Face CLI and authenticate interactively; do not place an access
token in a command, URL, or script:

```powershell
hf auth login
.\deploy\huggingface\sync.ps1 -SpaceRemote "https://huggingface.co/spaces/<namespace>/<space>"
```

The sync script creates a temporary clean deployment bundle containing only the
backend application, Alembic files, root Dockerfile, startup script, requirements,
and Space README. The container applies `alembic upgrade head` before Uvicorn starts.

Create the Docker Space and set its Hugging Face and Neon variables before pushing
the first source commit so migrations have a persistent database available at boot.
Do not add `.env` files to the Space repository.

## Deploy the frontend

Configure the Vercel project with `frontend` as its root directory, `npm run build`
as the build command, and `dist` as the output directory. Set `VITE_API_URL` in the
Vercel project environment and redeploy. Add the Vercel site origin to the
Hugging Face Space's `ALLOWED_ORIGINS`.

## Seed fake demo data

After backend configuration, run this from the repository root to apply migrations
and create an idempotent fake teacher, fake student, subject, chapter, and sample
document:

```powershell
python scripts/seed_demo.py
```

The demo accounts use reserved `example.test` email addresses and a clearly fake
password defined only in the seed script. Never use that password for a real account.
