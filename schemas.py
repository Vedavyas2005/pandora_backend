from pydantic import BaseModel, EmailStr, model_validator
from typing import Optional, Literal

# ── AUTH SCHEMAS (from plugin) ─────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str

    @model_validator(mode='after')
    def passwords_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        if len(self.password) < 8:
            raise ValueError("Password must be at least 8 characters")
        return self

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class OnboardRequest(BaseModel):
    username: str
    profile_pic_url: Optional[str] = None

class UpdateProfileRequest(BaseModel):
    username: Optional[str] = None
    profile_pic_url: Optional[str] = None

class UserResponse(BaseModel):
    id: str
    email: str
    username: Optional[str]
    profile_pic_url: Optional[str]
    is_onboarded: bool

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# ── VAULT / SESSION SCHEMAS ────────────────────────────────────────────────
class SessionData(BaseModel):
    topic: Optional[str] = None
    current_level: Optional[int] = None          # 1–5
    diagnostic_attempts: Optional[int] = 0       # 0–3
    diagnostic_passed: Optional[bool] = False
    hint_stage: Optional[int] = 0                # 0=none 1=mermaid 2=pseudocode

class SessionUpdateRequest(BaseModel):
    topic: Optional[str] = None
    current_level: Optional[int] = None
    diagnostic_attempts: Optional[int] = None
    diagnostic_passed: Optional[bool] = None
    hint_stage: Optional[int] = None

# ── LLM SCHEMAS ───────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    topic: str                                    # e.g. "Hashing"
    level: int                                    # 1–5, the level user WANTS to study
    language: Optional[str] = "Python"           # coding language preference
    message_type: Literal[
        "generate_question",   # gatekeeper: generate a question for level-1
        "check_answer",        # check user's answer, return pass/fail + hint
        "lesson",              # generate the actual lesson content
        "hint_mermaid",        # generate mermaid diagram hint
        "hint_pseudocode",     # generate pseudocode hint
        "reveal_answer",       # attempt 3 failed: show full answer + explanation
    ]
    user_answer: Optional[str] = None            # filled when message_type = check_answer

class AskResponse(BaseModel):
    content: str                                 # main LLM text response
    passed: Optional[bool] = None               # for check_answer: True/False
    mermaid_code: Optional[str] = None          # extracted mermaid block if any
    recommended_level: Optional[int] = None     # set when redirecting user

# ── QUIZ SCHEMAS ───────────────────────────────────────────────────────────
class QuizStartRequest(BaseModel):
    topic: str
    level: int
    language: Optional[str] = "Python"
    # "popquiz" = 1-2 mid-lesson checks (no promotion)
    # "levelup" = 5-8 end-of-level exam (70% → next level)
    quiz_mode: Optional[str] = "popquiz"

class QuizAnswerRequest(BaseModel):
    topic: str
    level: int
    language: Optional[str] = "Python"
    question_index: int          # which question (0-based) is being answered
    question_text: str           # the question text (so LLM has context)
    user_answer: str             # the user's answer

class QuizResult(BaseModel):
    question_index: int
    question_text: str
    user_answer: str
    passed: bool
    feedback: str                # Vera's per-question feedback

class QuizSubmitResponse(BaseModel):
    # returned after EACH answer
    passed: bool                 # did they pass THIS question
    feedback: str                # warm per-question feedback
    quiz_complete: bool          # is the full quiz done?
    quiz_mode: Optional[str] = "popquiz"     # "popquiz" or "levelup"
    # only set when quiz_complete=True:
    score: Optional[int] = None              # e.g. 6 (out of total)
    total: Optional[int] = None              # e.g. 8
    percent: Optional[int] = None           # e.g. 75
    promoted: Optional[bool] = None         # True = levelled up (levelup mode only)
    next_level: Optional[int] = None        # level they move to
    weak_topics: Optional[list] = None      # question texts they got wrong
    summary: Optional[str] = None           # Vera's full summary message

class NextQuestionResponse(BaseModel):
    question_text: str
    question_index: int
    total_questions: int