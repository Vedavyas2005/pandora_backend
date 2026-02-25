from fastapi import APIRouter, HTTPException, Depends
from schemas import (
    SignupRequest, LoginRequest, OnboardRequest,
    UpdateProfileRequest, UserResponse, TokenResponse
)
from database import supabase
from auth import hash_password, verify_password, create_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# Take in user details lke username,pfp for the first signup
def fmt_user(u: dict) -> UserResponse:
    return UserResponse(
        id=str(u["id"]),
        email=u["email"],
        username=u.get("username"),
        profile_pic_url=u.get("profile_pic_url"),
        is_onboarded=u.get("is_onboarded", False),
    )


# ── SIGNUP ──────────────────────────────────────────────────────────────────
@router.post("/signup", response_model=TokenResponse)
def signup(body: SignupRequest):
    existing = supabase.table("users").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = hash_password(body.password)
    result = supabase.table("users").insert({
        "email": body.email,
        "hashed_password": hashed,
    }).execute()

    user = result.data[0]
    token = create_token(str(user["id"]))
    return TokenResponse(access_token=token, user=fmt_user(user))


# ── LOGIN ───────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    result = supabase.table("users").select("*").eq("email", body.email).execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user = result.data[0]
    if not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(str(user["id"]))
    return TokenResponse(access_token=token, user=fmt_user(user))


# ── ONBOARD ─────────────────────────────────────────────────────────────────
@router.post("/onboard", response_model=UserResponse)
def onboard(body: OnboardRequest, current_user=Depends(get_current_user)):
    if current_user["is_onboarded"]:
        raise HTTPException(status_code=400, detail="Already onboarded")

    existing = supabase.table("users").select("id").eq("username", body.username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Username already taken")

    result = supabase.table("users").update({
        "username": body.username,
        "profile_pic_url": body.profile_pic_url,
        "is_onboarded": True,
    }).eq("id", current_user["id"]).execute()

    return fmt_user(result.data[0])


# ── UPDATE PROFILE ───────────────────────────────────────────────────────────
@router.patch("/profile", response_model=UserResponse)
def update_profile(body: UpdateProfileRequest, current_user=Depends(get_current_user)):
    updates = body.dict(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    if "username" in updates:
        existing = supabase.table("users").select("id").eq("username", updates["username"]).execute()
        if existing.data and existing.data[0]["id"] != current_user["id"]:
            raise HTTPException(status_code=400, detail="Username already taken")

    result = supabase.table("users").update(updates).eq("id", current_user["id"]).execute()
    return fmt_user(result.data[0])


# ── GET ME ───────────────────────────────────────────────────────────────────
@router.get("/me", response_model=UserResponse)
def get_me(current_user=Depends(get_current_user)):
    return fmt_user(current_user)