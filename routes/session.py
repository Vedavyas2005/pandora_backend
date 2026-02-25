from fastapi import APIRouter, Depends, HTTPException
from database import supabase
from auth import get_current_user
from schemas import SessionData, SessionUpdateRequest

router = APIRouter(prefix="/session", tags=["session"])


# ── GET SESSION ────────────────────────────────────────────────────────────
@router.get("/", response_model=SessionData)
def get_session(current_user=Depends(get_current_user)):
    """Load the user's last saved topic and level from Supabase."""
    result = (
        supabase.table("user_progress")
        .select("*")
        .eq("id", current_user["id"])
        .execute()
    )
    if not result.data:
        # No progress row yet — return empty session
        return SessionData()
    row = result.data[0]
    return SessionData(
        topic=row.get("topic"),
        current_level=row.get("current_level"),
        diagnostic_attempts=row.get("diagnostic_attempts", 0),
        diagnostic_passed=row.get("diagnostic_passed", False),
        hint_stage=row.get("hint_stage", 0),
    )


# ── PATCH SESSION ──────────────────────────────────────────────────────────
@router.patch("/", response_model=SessionData)
def update_session(body: SessionUpdateRequest, current_user=Depends(get_current_user)):
    """
    Upsert the user's progress.
    Only fields that are set in the request body will be updated.
    """
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Check if a row already exists
    existing = (
        supabase.table("user_progress")
        .select("id")
        .eq("id", current_user["id"])
        .execute()
    )

    if existing.data:
        result = (
            supabase.table("user_progress")
            .update(updates)
            .eq("id", current_user["id"])
            .execute()
        )
    else:
        result = (
            supabase.table("user_progress")
            .insert({"id": current_user["id"], **updates})
            .execute()
        )

    row = result.data[0]
    return SessionData(
        topic=row.get("topic"),
        current_level=row.get("current_level"),
        diagnostic_attempts=row.get("diagnostic_attempts", 0),
        diagnostic_passed=row.get("diagnostic_passed", False),
        hint_stage=row.get("hint_stage", 0),
    )


# ── RESET SESSION ──────────────────────────────────────────────────────────
@router.delete("/")
def reset_session(current_user=Depends(get_current_user)):
    """Reset progress — user wants to start a new topic from scratch."""
    supabase.table("user_progress").delete().eq("id", current_user["id"]).execute()
    return {"message": "Session reset. The Vault awaits you fresh! 🔓"}