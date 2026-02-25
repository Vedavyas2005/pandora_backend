from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from database import supabase
from auth import get_current_user
from schemas import (
    AskRequest, AskResponse,
    QuizStartRequest, QuizAnswerRequest,
    QuizSubmitResponse, NextQuestionResponse,
)
from llm import (
    call_llm, client, MODEL, VAULT_PERSONA, LEVEL_LABELS,
    generate_quiz_questions, grade_quiz_answer, generate_quiz_summary,
)

router = APIRouter(prefix="/vault", tags=["vault"])


# ── HELPER ─────────────────────────────────────────────────────────────────
def _save_progress(user_id: str, updates: dict):
    """Upsert a user_progress row."""
    existing = supabase.table("user_progress").select("id").eq("id", user_id).execute()
    if existing.data:
        supabase.table("user_progress").update(updates).eq("id", user_id).execute()
    else:
        supabase.table("user_progress").insert({"id": user_id, **updates}).execute()


# ── GATEKEEPER ─────────────────────────────────────────────────────────────
@router.post("/gatekeeper", response_model=AskResponse)
def gatekeeper(req: AskRequest, current_user=Depends(get_current_user)):
    """
    L1 → skip gatekeeper, go straight to lesson.
    L2-L5 → generate a verification question for the level below.
    """
    if req.level < 1 or req.level > 5:
        raise HTTPException(status_code=400, detail="Level must be 1-5")

    if req.level == 1:
        lesson_req = AskRequest(
            topic=req.topic,
            level=1,
            language=req.language,
            message_type="lesson",
        )
        response = call_llm(lesson_req)
        _save_progress(current_user["id"], {
            "topic": req.topic,
            "current_level": 1,
            "diagnostic_passed": True,
            "diagnostic_attempts": 0,
            "hint_stage": 0,
        })
        return response

    req.message_type = "generate_question"
    response = call_llm(req)
    _save_progress(current_user["id"], {
        "topic": req.topic,
        "current_level": req.level,
        "diagnostic_passed": False,
        "diagnostic_attempts": 0,
        "hint_stage": 0,
    })
    return response


# ── SUBMIT (3-try gatekeeper logic) ────────────────────────────────────────
@router.post("/submit", response_model=AskResponse)
def submit_answer(req: AskRequest, current_user=Depends(get_current_user)):
    """
    Attempt 1 wrong -> Mermaid hint
    Attempt 2 wrong -> Pseudocode hint
    Attempt 3 wrong -> Full answer reveal + drop level
    Any attempt right -> lesson
    """
    user_id = current_user["id"]

    state_result = supabase.table("user_progress").select("*").eq("id", user_id).execute()
    if not state_result.data:
        raise HTTPException(
            status_code=400,
            detail="No active session. Start from /vault/gatekeeper first.",
        )

    state = state_result.data[0]
    attempts = state.get("diagnostic_attempts", 0)

    check_result = call_llm(AskRequest(
        topic=req.topic,
        level=req.level,
        language=req.language,
        message_type="check_answer",
        user_answer=req.user_answer,
    ))

    # ── PASS ────────────────────────────────────────────────────────────────
    if check_result.passed is True:
        _save_progress(user_id, {
            "diagnostic_passed": True,
            "diagnostic_attempts": attempts + 1,
            "hint_stage": 0,
        })
        lesson = call_llm(AskRequest(
            topic=req.topic,
            level=req.level,
            language=req.language,
            message_type="lesson",
        ))
        lesson.passed = True
        return lesson

    # ── FAIL ────────────────────────────────────────────────────────────────
    new_attempts = attempts + 1
    _save_progress(user_id, {"diagnostic_attempts": new_attempts})

    if new_attempts == 1:
        _save_progress(user_id, {"hint_stage": 1})
        hint = call_llm(AskRequest(
            topic=req.topic, level=req.level,
            language=req.language, message_type="hint_mermaid",
        ))
        hint.passed = False
        return hint

    elif new_attempts == 2:
        _save_progress(user_id, {"hint_stage": 2})
        hint = call_llm(AskRequest(
            topic=req.topic, level=req.level,
            language=req.language, message_type="hint_pseudocode",
        ))
        hint.passed = False
        return hint

    else:
        drop_level = max(1, req.level - 1)
        _save_progress(user_id, {
            "diagnostic_passed": False,
            "current_level": drop_level,
            "hint_stage": 0,
        })
        reveal = call_llm(AskRequest(
            topic=req.topic, level=req.level,
            language=req.language, message_type="reveal_answer",
        ))
        reveal.passed = False
        reveal.recommended_level = drop_level
        return reveal


# ── LESSON ──────────────────────────────────────────────────────────────────
@router.post("/lesson", response_model=AskResponse)
def get_lesson(req: AskRequest, current_user=Depends(get_current_user)):
    """Reload a lesson the user has already unlocked."""
    req.message_type = "lesson"
    return call_llm(req)


# ── CHAT MODELS ─────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str        # "user" or "assistant"
    content: str

class ChatRequest(BaseModel):
    topic: str
    level: int
    language: str = "Python"
    history: List[ChatMessage]

class ChatResponse(BaseModel):
    content: str
    trigger_quiz: bool = False       # mid-lesson pop quiz (1-2 Qs)
    trigger_levelup: bool = False    # end-of-level exam (5-8 Qs, promotion)


# ── CHAT ────────────────────────────────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, current_user=Depends(get_current_user)):
    """
    Multi-turn chat with Vera.
    Vera appends [QUIZ_TRIGGER] when she decides the learner is ready for a quiz.
    """
    level_label = LEVEL_LABELS.get(req.level, "")
    user_turns  = sum(1 for m in req.history if m.role == "user")

    quiz_done      = any("QUIZ_DONE"    in m.content for m in req.history)
    levelup_done   = any("LEVELUP_DONE" in m.content for m in req.history)

    system = (
        VAULT_PERSONA
        + f"""

Context:
- Topic: {req.topic} | Level {req.level} ({level_label}) | Language: {req.language}
- User messages exchanged so far: {user_turns}

Your job: Answer the student's question warmly and helpfully.

You have TWO optional signal tags you can append (one at most, on its own line at the end):

[POPQUIZ_TRIGGER]
  → Use this for a quick 1-2 question mid-lesson check.
  → Only trigger when ALL true:
      1. Between 3 and 6 user messages exchanged
      2. A specific concept was just explained and the conversation hit a natural pause
      3. "QUIZ_DONE" does NOT appear in history
      4. Student is not confused or mid-question

[LEVELUP_TRIGGER]
  → Use this when you judge the ENTIRE level content has been fully taught.
  → Only trigger when ALL true:
      1. At least 7 user messages exchanged
      2. All key concepts for Level {req.level} on {req.topic} have been covered
      3. "LEVELUP_DONE" does NOT appear in history
      4. Student seems ready — not confused

Rules:
- Only ever emit ONE tag per response, never both.
- Never mention either tag or any upcoming quiz to the student.
- If neither condition is met, emit no tag at all.
"""
    )

    messages = [{"role": "system", "content": system}]
    for msg in req.history:
        messages.append({"role": msg.role, "content": msg.content})

    completion = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
        max_completion_tokens=900,
    )
    raw = completion.choices[0].message.content

    trigger_quiz    = "[POPQUIZ_TRIGGER]"  in raw and not quiz_done
    trigger_levelup = "[LEVELUP_TRIGGER]"  in raw and not levelup_done

    clean = (raw
             .replace("[POPQUIZ_TRIGGER]", "")
             .replace("[LEVELUP_TRIGGER]", "")
             .strip())

    return ChatResponse(content=clean, trigger_quiz=trigger_quiz, trigger_levelup=trigger_levelup)


# ── QUIZ IN-MEMORY STORE ────────────────────────────────────────────────────
# { user_id: { questions, current_index, results, topic, level, language } }
# Resets on server restart — intentional, quizzes are per-session only
_quiz_store: dict = {}


@router.post("/quiz/start", response_model=NextQuestionResponse)
def quiz_start(req: QuizStartRequest, current_user=Depends(get_current_user)):
    """Generate questions for this topic+level and return the first one."""
    user_id   = current_user["id"]
    mode      = req.quiz_mode or "popquiz"
    questions = generate_quiz_questions(req.topic, req.level, req.language, quiz_mode=mode)
    if not questions:
        raise HTTPException(status_code=500, detail="Failed to generate quiz questions.")

    _quiz_store[user_id] = {
        "questions":     questions,
        "current_index": 0,
        "results":       [],
        "topic":         req.topic,
        "level":         req.level,
        "language":      req.language,
        "quiz_mode":     mode,          # stored so quiz/answer knows whether to promote
    }
    return NextQuestionResponse(
        question_text=questions[0],
        question_index=0,
        total_questions=len(questions),
    )


@router.post("/quiz/answer", response_model=QuizSubmitResponse)
def quiz_answer(req: QuizAnswerRequest, current_user=Depends(get_current_user)):
    """Grade the current answer and return next question or final summary."""
    user_id = current_user["id"]
    store   = _quiz_store.get(user_id)
    if not store:
        raise HTTPException(status_code=400, detail="No active quiz. Call /quiz/start first.")

    passed, feedback = grade_quiz_answer(
        topic=req.topic,
        level=req.level,
        language=req.language,
        question=req.question_text,
        answer=req.user_answer,
    )
    store["results"].append({
        "question_index": req.question_index,
        "question_text":  req.question_text,
        "user_answer":    req.user_answer,
        "passed":         passed,
        "feedback":       feedback,
    })
    store["current_index"] = req.question_index + 1
    is_last = store["current_index"] >= len(store["questions"])

    # More questions left
    if not is_last:
        return QuizSubmitResponse(
            passed=passed,
            feedback=feedback,
            quiz_complete=False,
        )

    # ── All done ─────────────────────────────────────────────────────────
    results    = store["results"]
    score      = sum(1 for r in results if r["passed"])
    total      = len(results)
    percent    = round((score / total) * 100)
    mode       = store.get("quiz_mode", "popquiz")
    # Promotion only happens on the level-up exam, not on pop quizzes
    promoted   = (mode == "levelup") and (percent >= 70)
    next_level = min(5, store["level"] + 1) if promoted else store["level"]
    weak_questions = [r["question_text"] for r in results if not r["passed"]]

    summary = generate_quiz_summary(
        topic=store["topic"],
        level=store["level"],
        score=score,
        total=total,
        weak_questions=weak_questions,
        language=store["language"],
        quiz_mode=mode,
    )

    if promoted and next_level != store["level"]:
        _save_progress(user_id, {
            "current_level":      next_level,
            "diagnostic_passed":  True,
            "diagnostic_attempts": 0,
            "hint_stage":         0,
        })

    del _quiz_store[user_id]

    return QuizSubmitResponse(
        passed=passed,
        feedback=feedback,
        quiz_complete=True,
        score=score,
        total=total,
        percent=percent,
        promoted=promoted,
        next_level=next_level,
        weak_topics=weak_questions,
        summary=summary,
        quiz_mode=mode,
    )


@router.get("/quiz/next", response_model=NextQuestionResponse)
def quiz_next(current_user=Depends(get_current_user)):
    """Return the next unanswered question in the active quiz."""
    user_id = current_user["id"]
    store   = _quiz_store.get(user_id)
    if not store:
        raise HTTPException(status_code=400, detail="No active quiz.")
    idx = store["current_index"]
    if idx >= len(store["questions"]):
        raise HTTPException(status_code=400, detail="Quiz already complete.")
    return NextQuestionResponse(
        question_text=store["questions"][idx],
        question_index=idx,
        total_questions=len(store["questions"]),
    )