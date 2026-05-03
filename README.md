# State Political Tracker Demo

## Structure

- `backend/` - FastAPI API and Exa discovery agent.
- `frontend/` - Vite React TypeScript app with the `InfluenceGraph` component.
- `backend/.env` - backend secrets and database connection.

## Backend

```bash
cd backend
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Frontend

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

The frontend reads `VITE_API_URL`, defaulting cleanly to same-origin requests if it is not set.
