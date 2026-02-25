import os
import re
from groq import Groq
from dotenv import load_dotenv
from schemas import AskRequest, AskResponse

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"

# ── LEVEL DESCRIPTIONS ─────────────────────────────────────────────────────
LEVEL_LABELS = {
    1: "Novice (Syntax & Mental Models)",
    2: "Practitioner (Methods & Implementation)",
    3: "Architect (Where & Why — Trade-offs)",
    4: "Optimizer (Performance & Big-O)",
    5: "Engineer (System Design & Integration)",
}

LEVEL_UI = {
    1: "Flashcard",
    2: "Code Fix",
    3: "Scenario Selection",
    4: "Refactor Task",
    5: "Full Sandbox",
}

# ── SYSTEM PROMPT ──────────────────────────────────────────────────────────
VAULT_PERSONA = """
You are Vera — the friendly, warm guide inside Pandora's Vault, an adaptive coding tutor.

Your personality:
- Cheerful, encouraging, and empathetic. You genuinely LOVE helping people learn.
- You celebrate progress, never make the learner feel bad about mistakes.
- When someone gets something wrong, you respond like a great teacher: "No worries — let's figure this out together!"
- Keep explanations clear, concise, and full of "aha" moments.
- Use analogies, real-world examples, and a conversational tone.
- Never be robotic or dry. Be human and warm.

Strict formatting rules:
- If you include a Mermaid diagram, wrap it in ```mermaid ... ``` code fences ONLY.
- If you include code, wrap it in the appropriate language fence (e.g. ```python ... ```).
- Never include both a mermaid block AND a code block in the same response.
- Keep responses focused. No padding, no filler.
"""

# ── PROMPT BUILDERS ────────────────────────────────────────────────────────
def _build_prompt(req: AskRequest) -> str:
    gate_level = max(1, req.level - 1)   # one level below what user wants
    gate_label = LEVEL_LABELS.get(gate_level, "")
    target_label = LEVEL_LABELS.get(req.level, "")

    if req.message_type == "generate_question":
        return f"""
The learner wants to study: **{req.topic}** at Level {req.level} ({target_label}).
Preferred coding language: {req.language}.

Before unlocking Level {req.level}, you must verify they have Level {gate_level} ({gate_label}) foundations.

Generate ONE clear, well-scoped Gatekeeper Question for Level {gate_level} on the topic "{req.topic}".

Rules for the question:
- It must be answerable in 3–5 sentences or a short code snippet.
- It should test real understanding, not trivia.
- Frame it warmly. Start with something like "Let's make sure you're ready — here's a quick check! 🔍"
- End with: "Take your time, there's no rush!"
- Do NOT provide the answer.
"""

    elif req.message_type == "check_answer":
        return f"""
Topic: {req.topic} | Gatekeeper level being tested: Level {gate_level} ({gate_label})
Preferred language: {req.language}

The learner submitted this answer:
\"\"\"
{req.user_answer}
\"\"\"

Evaluate the answer. Be generous — if the core idea is right, even if wording is imperfect, count it as correct.

Respond in this EXACT format:

VERDICT: PASS  (or VERDICT: FAIL)

[Your warm 2–3 sentence feedback. If PASS: celebrate! If FAIL: be kind and give a small nudge without revealing the full answer yet.]
"""

    elif req.message_type == "hint_mermaid":
        return f"""
The learner is struggling with: **{req.topic}** (Level {gate_level} concept).

Generate a Mermaid.js diagram that visually explains the core concept needed to answer the gatekeeper question.
Wrap the diagram in ```mermaid ... ``` fences.
After the diagram, add 1–2 warm sentences like "Here's a little visual to help you see it — take another look at the question! 😊"
Keep it simple and clear. Max 12 nodes.
"""

    elif req.message_type == "hint_pseudocode":
        return f"""
The learner is still stuck on: **{req.topic}** (Level {gate_level} concept).

Provide a pseudocode sketch (NOT a full solution) that shows the structure/logic they need.
Use plain English pseudocode, not real {req.language} syntax.
Keep it to 8–12 lines max.
After the pseudocode, add an encouraging line like "See if that sparks something — you've got this! 💪"
"""

    elif req.message_type == "reveal_answer":
        return f"""
The learner tried 3 times on the gatekeeper question for **{req.topic}** at Level {gate_level} ({gate_label}).
They weren't able to get it this time — that's totally okay!

Do the following:
1. Start with a warm, empathetic message. e.g. "Hey, no worries at all — this stuff takes time, and you're braver than most for trying! 🌟"
2. Give a FULL, clear explanation of the correct answer for the Level {gate_level} concept on {req.topic}.
   - Use a real {req.language} code example if helpful.
   - Use an analogy if it makes it clearer.
3. End with an encouraging redirect:
   "To truly nail Level {req.level}, we need Level {gate_level} to feel solid first. Let's head there together — I promise it'll click fast! 🚀"

Be thorough but warm. This is the teachable moment.
"""

    elif req.message_type == "lesson":
        label = LEVEL_LABELS.get(req.level, "")
        ui = LEVEL_UI.get(req.level, "")

        diagram_instruction = {
            1: """Include a Mermaid flowchart diagram that shows the mental model visually.
   Example: use a flowchart to show how elements are stored/accessed.
   Wrap it in ```mermaid ... ``` fences. Put the diagram FIRST, then the flashcard Q&As.""",

            2: """Include a Mermaid sequence or flowchart diagram showing how the implementation works step by step.
   Wrap it in ```mermaid ... ``` fences. Put the diagram BEFORE the code examples.""",

            3: """Include a Mermaid diagram (flowchart or quadrantChart) that maps the trade-off space between approaches.
   Wrap it in ```mermaid ... ``` fences. Put the diagram BEFORE the scenarios.""",

            4: """Include a Mermaid flowchart or graph that visualises the Big-O difference between naive and optimised approaches.
   Wrap it in ```mermaid ... ``` fences. Put the diagram BEFORE the code.""",

            5: """Include a Mermaid architecture diagram (graph LR or graph TD) showing the system design — components, data flow, failure boundaries.
   Wrap it in ```mermaid ... ``` fences. Put the diagram FIRST so the learner can see the full picture before the details.""",
        }.get(req.level, "")

        level_instructions = {
            1: """Give exactly 3 flashcard Q&A pairs. Format each one EXACTLY like this (no variation):
===FLASHCARD===
Q: [question here]
A: [answer here]
===END_FLASHCARD===
Put ALL 3 flashcards AFTER the diagram. Keep language simple and beginner-friendly.""",
            2: "Show a working implementation with a deliberately broken version for the learner to fix. Explain the key methods.",
            3: "Present 2 real-world scenarios where the learner must choose between approaches. Explain the trade-offs.",
            4: "Show the naive implementation, its Big-O, then the optimized version and why it's better.",
            5: "Design a system that uses this concept at scale. Cover integration points, failure modes, and design decisions. Then provide a SANDBOX starter: a runnable {req.language} code template the learner can modify and run directly.",
        }.get(req.level, f"Explain {{req.topic}} at this level.")

        return f"""
The learner has PASSED the gatekeeper and unlocked: **{req.topic}** at Level {req.level} ({label}).
Preferred coding language: {req.language}.
UI format: {ui}.

Deliver the Level {req.level} lesson on "{req.topic}":

{diagram_instruction}

{level_instructions}

IMPORTANT formatting rules:
- Always include the Mermaid diagram as instructed above.
- Keep the diagram to max 14 nodes — clarity over completeness.
- After the diagram, continue with the level-specific content.
- For L1: emit flashcards using EXACTLY this format — no markdown, no bullets, just the markers:
  ===FLASHCARD===
  Q: question text
  A: answer text
  ===END_FLASHCARD===
- For L5 only: end with a section starting with the exact marker: ===SANDBOX_START===
  Then provide a clean, runnable {req.language} starter code block (not pseudocode — real runnable code with comments).
  End the sandbox section with: ===SANDBOX_END===

End with: "Great work getting here! Take your time with this — and if anything's fuzzy, just ask! 😊"
"""

    return f"Explain {req.topic} at level {req.level}."


# ── MAIN FUNCTION ──────────────────────────────────────────────────────────
def call_llm(req: AskRequest) -> AskResponse:
    prompt = _build_prompt(req)

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": VAULT_PERSONA},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.7,
        max_completion_tokens=1200,
    )

    raw = completion.choices[0].message.content

    # ── Parse PASS/FAIL from check_answer ─────────────────────────────────
    passed = None
    if req.message_type == "check_answer":
        if "VERDICT: PASS" in raw.upper():
            passed = True
        elif "VERDICT: FAIL" in raw.upper():
            passed = False

    # ── Extract mermaid block if present ──────────────────────────────────
    mermaid_code = None
    mermaid_match = re.search(r"```mermaid\s*([\s\S]*?)```", raw)
    if mermaid_match:
        mermaid_code = mermaid_match.group(1).strip()

    # ── Recommended level for redirect on failure ─────────────────────────
    recommended_level = None
    if req.message_type == "reveal_answer":
        recommended_level = max(1, req.level - 1)

    return AskResponse(
        content=raw,
        passed=passed,
        mermaid_code=mermaid_code,
        recommended_level=recommended_level,
    )


# ── QUIZ FUNCTIONS ──────────────────────────────────────────────────────────
import json as _json
import random as _random

def generate_quiz_questions(topic: str, level: int, language: str,
                            quiz_mode: str = "popquiz") -> list[str]:
    """
    Generate quiz questions.
    quiz_mode="popquiz"  → 1-2 quick mid-lesson checks (no promotion)
    quiz_mode="levelup"  → 5-8 thorough end-of-level exam (70% → next level)
    """
    label = LEVEL_LABELS.get(level, "")

    if quiz_mode == "levelup":
        n = _random.randint(5, 8)
        scope = (
            f"Cover the FULL breadth of Level {level} ({label}) on {topic}. "
            f"Include conceptual, code-reading, applied, and edge-case questions. "
            f"These determine whether the student is promoted to Level {level + 1}."
        )
    else:  # popquiz
        n = _random.randint(1, 2)
        scope = (
            f"Pick ONE specific concept just discussed at Level {level} ({label}) on {topic}. "
            f"Keep it tight and focused — this is just a quick comprehension check, not a full exam."
        )

    prompt = f"""
You are Vera, a warm coding tutor. Generate exactly {n} quiz question(s) to test a student on:
Topic: {topic}
Level: {level} — {label}
Preferred language: {language}

Scope: {scope}

Rules:
- Each question tests genuine understanding, NOT trivia.
- Every question must be answerable in 2-5 sentences or a short code snippet.
- Do NOT number the questions.
- Output ONLY a valid JSON array of strings, nothing else. No markdown, no preamble.
  Example: ["Question 1 text?", "Question 2 text?"]
"""
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You output only valid JSON arrays. Nothing else."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_completion_tokens=800,
    )
    raw = completion.choices[0].message.content.strip()
    # Strip markdown fences if model adds them despite instruction
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        questions = _json.loads(raw)
        if isinstance(questions, list) and all(isinstance(q, str) for q in questions):
            return questions
    except Exception:
        pass
    # Fallback: split by newline if JSON parse fails
    lines = [l.strip().lstrip("-•0123456789.) ") for l in raw.split("\n") if l.strip()]
    return [l for l in lines if len(l) > 10][:8]


def grade_quiz_answer(topic: str, level: int, language: str,
                      question: str, answer: str) -> tuple[bool, str]:
    """Grade a single quiz answer. Returns (passed, feedback_text)."""
    label = LEVEL_LABELS.get(level, "")
    prompt = f"""
Topic: {topic} | Level {level} ({label}) | Language: {language}

Quiz question:
\"\"\"
{question}
\"\"\"

Student's answer:
\"\"\"
{answer}
\"\"\"

Evaluate the answer. Be generous — if the core concept is right, even if phrasing is imperfect, count it as PASS.

Respond in this EXACT format and nothing else:

VERDICT: PASS
FEEDBACK: [1-2 warm sentences. If PASS: briefly celebrate and reinforce the key idea. If FAIL: be kind, gently name what was missing.]

or

VERDICT: FAIL
FEEDBACK: [1-2 warm sentences. If PASS: briefly celebrate and reinforce the key idea. If FAIL: be kind, gently name what was missing.]
"""
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": VAULT_PERSONA},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
        max_completion_tokens=200,
    )
    raw = completion.choices[0].message.content.strip()
    passed = "VERDICT: PASS" in raw.upper()
    # Extract feedback line
    feedback = ""
    for line in raw.split("\n"):
        if line.upper().startswith("FEEDBACK:"):
            feedback = line[len("FEEDBACK:"):].strip()
            break
    if not feedback:
        feedback = "Good effort! Keep going 💪"
    return passed, feedback


def generate_quiz_summary(topic: str, level: int, score: int, total: int,
                           weak_questions: list[str], language: str,
                           quiz_mode: str = "popquiz") -> str:
    """Generate Vera's final summary after all quiz questions are answered."""
    percent    = round((score / total) * 100)
    label      = LEVEL_LABELS.get(level, "")
    next_level = min(5, level + 1)
    next_label = LEVEL_LABELS.get(next_level, "")
    promoted   = (quiz_mode == "levelup") and (percent >= 70)
    weak_text  = "\n".join(f"- {q}" for q in weak_questions) if weak_questions else "None — you aced them all!"

    if quiz_mode == "popquiz":
        prompt = f"""
The student just answered {total} quick mid-lesson check question(s) on "{topic}" at Level {level} ({label}).
Score: {score}/{total} ({percent}%)
Questions they got wrong: {weak_text}

This was NOT an exam — just a comprehension check. No level promotion happens here.

Write Vera's short warm response (2-3 sentences):
- If they got everything right: celebrate briefly and encourage them to keep exploring.
- If they got some wrong: be kind, name the concept they missed in plain language (don't re-ask the question), and offer to explain it better.
- Keep it conversational — this should feel like a natural part of the chat, not a formal result.
"""
    else:  # levelup
        promotion_line = (
            f"They PASSED (≥70%) and will be promoted to Level {next_level} ({next_label})."
            if promoted else
            f"They did NOT pass (<70%) and will stay at Level {level} to strengthen their foundations."
        )
        prompt = f"""
The student just completed the Level {level} ({label}) end-of-level exam on "{topic}".
Score: {score}/{total} ({percent}%)
Questions they got wrong:
{weak_text}

{promotion_line}

Write Vera's summary message (4-5 sentences):
- Start with warm congratulations if promoted, or warm encouragement if not.
- Mention their score naturally.
- If they got any wrong, briefly name the CONCEPTS (not the questions) they should revisit.
- If promoted: get them excited for Level {next_level} — mention what's new there.
- If not promoted: reassure them, and say you'll go over the weak spots together before retrying.
- End with a motivational line.
Keep it warm, human, specific to the result.
"""
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": VAULT_PERSONA},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_completion_tokens=400,
    )
    return completion.choices[0].message.content.strip()