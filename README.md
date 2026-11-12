# ShikshaSaathi Voice 🎓🎤

> Multilingual AI-powered educational voice tutor for Indian-language learners.

Students ask questions through their microphone in supported Indian languages. The application transcribes their questions, retrieves relevant information from teacher-uploaded study materials, generates grounded educational explanations, and speaks the answers back — all powered by **Gnani Technologies**.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite |
| Backend | Python 3.11+ / FastAPI |
| Database | PostgreSQL + pgvector |
| Real-time | WebSockets |
| Speech-to-Text | Gnani Prisma |
| LLM Reasoning | Gnani Evon |
| Text-to-Speech | Gnani Timbre |
| Voice Cloning | Gnani Voice Cloning |

---

## Project Structure

```
shikshasathi-voice/
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── api/            # Route handlers
│   │   ├── core/           # Settings, security, database
│   │   ├── models/         # SQLAlchemy / Pydantic models
│   │   ├── services/       # Business logic & AI orchestration
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   └── main.py         # Application entry point
│   └── alembic/            # Database migrations
├── frontend/               # React + Vite application
│   ├── src/
│   │   ├── components/     # Reusable UI components
│   │   ├── pages/          # Route-level views
│   │   ├── hooks/          # Custom React hooks
│   │   ├── services/       # API client helpers
│   │   ├── store/          # State management
│   │   └── App.tsx
│   └── public/
├── docs/                   # Documentation & architecture notes
├── tests/                  # Test suites (backend & frontend)
│   ├── backend/
│   └── frontend/
├── .env.example            # Environment variable template
├── requirements.txt        # Python dependencies
├── DEVELOPMENT_PLAN.md     # Phased development roadmap
└── README.md               # ← You are here
```

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** & **npm 9+**
- **PostgreSQL 15+** with the `pgvector` extension
- A **Gnani Technologies** API key (for AI features in later phases)

### 1. Clone & configure

```bash
git clone <repo-url> shikshasathi-voice
cd shikshasathi-voice
cp .env.example .env
# Edit .env with your database credentials and (later) API keys
```

### 2. Backend

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r ../requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API will be available at **http://localhost:8000**. Interactive docs at `/docs`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server will start at **http://localhost:5173**.

---

## Development

See **[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)** for the phased roadmap.

### Running Tests

```bash
# Backend tests
pytest tests/backend/

# Frontend tests
cd frontend && npm test
```

---

## License

This project is proprietary. All rights reserved.
