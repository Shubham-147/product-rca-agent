# Product RCA Workbench

React/Vite UI for the read-only A/B/C comparison API.

```bash
# Terminal 1, repository root
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000

# Terminal 2
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The default API is
`http://127.0.0.1:8000/comparison`; override it with `VITE_API_URL`.
