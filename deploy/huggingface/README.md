---
title: ShikshaSaathi Voice
sdk: docker
app_port: 7860
---

# ShikshaSaathi Voice API

This Hugging Face Space runs the FastAPI backend in Docker. The container applies
Alembic migrations before starting Uvicorn on port 7860.

Configure the production environment variables in the Space settings before
launching it. Use a Neon PostgreSQL `DATABASE_URL`, set `STORAGE_PROVIDER` to
`database`, and include the Vercel origin in `ALLOWED_ORIGINS`.

The embedding model is downloaded into the image during the build. Uploaded
documents are stored as database binary data. Generated speech is returned from
memory and is not persisted on the container filesystem.
