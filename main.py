from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.users import router as auth_router
from routes.session import router as session_router
from routes.vault import router as vault_router

app = FastAPI(
    title="Pandora's Vault API",
    description="Adaptive coding tutor backend — Auth + Session + LLM",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # change * to frontend production url to protect the website from unwanted connectionss
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