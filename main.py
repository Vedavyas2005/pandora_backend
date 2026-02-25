from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.users import router as auth_router
from routes.session import router as session_router
from routes.vault import router as vault_router
from database import supabase
from datetime import datetime

app = FastAPI(
    title="Pandora's Vault API",
    description="Adaptive coding tutor backend — Auth + Session + LLM",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pandorasvault.netlify.app",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(session_router)
app.include_router(vault_router)


@app.get("/")
def root():
    return {"status": "Pandora's Vault is open 🔓", "version": "1.0.0"}


@app.get("/ping")
def ping():
    """
    Keep-alive endpoint — pinged every 10 minutes by cron-job.org
    to prevent Render free tier from sleeping + keeps Supabase active.
    """
    try:
        supabase.table("users").select("id", count="exact").limit(1).execute()
        return {
            "status": "alive",
            "db": "reachable",
            "pinged_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        return {
            "status": "alive",
            "db": "unreachable",
            "error": str(e),
            "pinged_at": datetime.utcnow().isoformat() + "Z",
        }
