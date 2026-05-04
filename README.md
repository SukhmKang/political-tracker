# State Political Tracker Demo

## Purpose

This tool is intended for modern-day muckrackers like accountability-focused nonprofits, investigative journalists, think-tanks, government watchdogs, and politically curious onlookers. In the tool, you can search any entity across 19 states' campaign finance data and view its donations as a network. When campaign finance disclosures lead to a dead end in the investigation, you can use an Exa AI agent to expand the graph and find new connections in the influence graph.

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
