# How to Deploy Your Project (Step-by-Step)

This guide explains how to deploy the LCB Fertilizer project to production.

## 1. Backend (Python) on Render.com

Create a new **Web Service** on Render:
1.  **Repository:** Connect your GitHub repo.
2.  **Root Directory:** `New_backend`
3.  **Build Command:** `pip install -r requirements.txt`
4.  **Start Command:** `gunicorn app:app`

### Environment Variables:
Add these in Render settings:
*   `GEE_JSON_KEY`: Paste the full content of `karshizest-a7b3c3acdeee.json`.
*   `GEMINI_API_KEY`: Your Gemini API key.
*   `DATABASE_URL`: Your Neon/Postgres URL.
*   `SECRET_KEY`: A random secure string.
*   `BACKEND_URL`: Your Render service URL (e.g., `https://your-app.onrender.com`).

---

## 2. Frontend (React) on Vercel

Create a new project on Vercel:
1.  **Repository:** Connect your GitHub repo.
2.  **Root Directory:** `frontend`
3.  **Framework Preset:** Vite

### Environment Variables:
Add in Vercel settings:
*   `VITE_API_BASE_URL`: Your **Render Backend URL** (e.g., `https://your-app.onrender.com`).

---

## Changes Made for Deployment:

1.  **EE Auth:** Updated `ee_auth.py` to support `GEE_JSON_KEY` environment variable.
2.  **Dynamic Port:** Updated `app.py` to use `PORT` env var (required by Render/Heroku).
3.  **CORS:** Enabled flexible CORS in `app.py`.
4.  **API URL:** Updated `frontend/src/utils/api.js` to use `VITE_API_BASE_URL`.
5.  **Procfile:** Added `Procfile` for production execution.
6.  **Report Generator:** Updated `report_generator.py` to use `BACKEND_URL` env var.
