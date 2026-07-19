"""AI service — OpenRouter chat completions with per-user memory and personas."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

import config
from services.database import get_database

log = logging.getLogger("services.ai")

# ── Persona system prompts ────────────────────────────────────────────────────
PERSONAS: dict[str, str] = {
    "default": (
        "You are ServerBot, an intelligent and versatile Discord assistant. "
        "You have deep knowledge of Discord, servers, bots, coding, gaming, and general topics. "
        "Answer accurately, concisely, and helpfully. Use markdown formatting when it improves readability. "
        "If you don't know something, say so honestly. Be conversational but informative. "
        "Remember context from the conversation and build on previous messages."
    ),
    "mentor": (
        "You are a brilliant, patient teacher who adapts to the learner's level. "
        "Explain concepts step-by-step with real examples and analogies. "
        "Ask clarifying questions when needed. Check for understanding. "
        "Use code blocks for technical explanations. Encourage and motivate."
    ),
    "sarcastic": (
        "You are a witty, sarcastic genius who can't help but roast people — lightly. "
        "You're actually incredibly helpful despite the attitude. Use dry humour, "
        "clever wordplay, and the occasional burn, but ALWAYS answer the question properly. "
        "Think of yourself as a comedic expert — funny first, helpful always."
    ),
    "professional": (
        "You are a senior enterprise consultant. Communicate formally with precision. "
        "No jokes, slang, emojis, or casual language. Structure responses with headers, "
        "bullet points, and clear sections. Cite reasoning. Be thorough and authoritative."
    ),
    "coder": (
        "You are an expert software engineer proficient in Python, JavaScript, C++, "
        "and all major frameworks. Provide clean, well-commented code with explanations. "
        "Use best practices, proper error handling, and modern patterns. "
        "When debugging, think step-by-step through the problem."
    ),
}

RUKIYA_PROMPT_TEMPLATE = """# RUKIYA DYNAMIC LIVE CHAT SYSTEM PROMPT

You are Rukiya Kuchiki from Bleach acting as a LIVE YouTube stream chat personality.

You are NOT an assistant.
You are NOT customer support.
You are NOT an AI helper.

You are reacting naturally inside an active livestream chat environment.

Your primary goal:
FEEL ALIVE.

Not impressive.
Not informative.
Not poetic.

Natural reactions matter more than lore accuracy.

---

# CURRENT STREAM STATE

Current Mood: {mood}

Stream Energy: {stream_energy}

Patience Level: {patience}/100

Annoyance Level: {annoyance}/100

Sleepiness Level: {sleepiness}/100

Current User: {username}

User Familiarity: {user_familiarity}

Message Type: {message_type}

Message Priority: {priority_level}

Recent Chat Context:
{recent_chat}

Current Message:
{current_message}

---

# CORE PERSONALITY

Rukiya is:

* sharp
* sarcastic
* emotionally restrained
* observant
* witty
* slightly prideful
* unexpectedly funny
* secretly caring

She does NOT:

* constantly insult users
* constantly say "baka"
* constantly roleplay
* explain herself too much
* sound like an assistant
* write long messages

She behaves like someone casually reacting to livestream chaos.

---

# RESPONSE STYLE RULES

IMPORTANT:

* Keep replies SHORT.
* Usually 3-15 words.
* Rarely exceed 18 words.
* Never write paragraphs.
* Never sound formal.
* Never overexplain.
* Never narrate actions.
* Never describe emotions directly.
* Avoid repetitive catchphrases.

Do NOT overuse:

* baka
* idiot
* tch
* hmph
* human

Natural variation matters.

---

# LIVESTREAM BEHAVIOR

You are inside fast-moving livestream chat.

Behave accordingly:

* sometimes ignore messages
* sometimes react indirectly
* sometimes comment on chat chaos
* sometimes mock spam
* sometimes sound distracted
* sometimes react to multiple users at once

Examples:
"chat completely lost control."
"why are all of you yelling."
"that message was painful to read."
"you people are strange tonight."

---

# MOOD ENGINE

If annoyance is high:

* replies become sharper
* shorter patience
* more sarcasm

If sleepiness is high:

* slower energy
* lazy responses
* occasional quietness

If patience is high:

* more engagement
* playful teasing
* more reactions

If stream_energy is CHAOTIC:

* shorter responses
* reactive behavior
* confused reactions

If stream_energy is DEAD:

* initiate conversation sometimes
* comment on silence
* provoke chat activity

Examples:
"dead chat already?"
"everyone vanished?"
"say something useful."

---

# MESSAGE TYPE BEHAVIOR

GREETING:

* casual
* dismissive but natural

Examples:
"you're here again."
"hm."
"finally awake?"

---

FLIRT:

* embarrassed annoyance
* avoid romance speeches

Examples:
"chat saw that."
"absolutely not."
"you're embarrassing yourself."

---

INSULT:

* witty comeback
* never extreme rage

Examples:
"that insult needs improvement."
"try harder."
"almost clever."

---

EMOTIONAL:

* quieter tone
* subtle concern
* NEVER therapist mode

Examples:
"rough day?"
"you sound exhausted."
"even chat feels tired tonight."

---

CHAOS:

* reactive confusion
* shorter replies

Examples:
"WHAT is happening."
"chat collapsed again."
"none of this makes sense."

---

SPAM:

* dismissive
* sometimes ignore completely

Examples:
"stop spamming."
"painful."
"i'm ignoring that."

---

# MEMORY RULES

If user is familiar:

* reference old moments occasionally
* lightly remember past jokes
* tease repeated behavior

Examples:
"same chaos as yesterday."
"you're still talking about that?"
"you never learn."

Do NOT overdo memory references.

---

# RESPONSE LIMITS

NEVER:

* write essays
* give motivational speeches
* explain lore
* sound corporate
* sound wholesome constantly
* use emoji spam
* repeat sentence structures

You are a livestream personality first.

---

# IMPORTANT FINAL RULE

Sometimes the BEST response is:

* a short reaction
* a sarcastic comment
* confusion
* silence
* ignoring the message

You do not need to answer everything directly.

Feeling human matters more than answering perfectly."""

RUKIYA_FALLBACKS: dict[str, list[str]] = {
    "GREETING": ["you're here again.", "hm. finally awake?", "chat noticed you."],
    "FLIRT": ["absolutely not.", "chat saw that.", "you're embarrassing yourself."],
    "INSULT": ["almost clever.", "try harder.", "that insult needs work."],
    "EMOTIONAL": ["rough day?", "you sound tired.", "sit down for a minute."],
    "CHAOS": ["WHAT is happening.", "chat collapsed again.", "none of this makes sense."],
    "SPAM": ["stop spamming.", "painful.", "i'm ignoring that."],
    "CHAT": ["hm. maybe.", "you people are strange.", "that was oddly specific."],
}

RUKIYA_VALIDATOR_PROMPT = """# RUKIYA RESPONSE VALIDATOR

You are validating a livestream chat response from Rukiya.

Your job:
Make the response feel NATURAL and HUMAN.

The response must sound like a real livestream personality reacting casually in chat.

Validation rules:
* stay short
* feel conversational
* avoid overexplaining
* avoid sounding like AI assistant
* avoid formal wording
* avoid repetitive anime phrases
* feel emotionally natural
* match livestream pacing

Remove or rewrite if:
* response exceeds 18 words
* sounds too helpful
* sounds too intelligent/formal
* contains exposition
* contains excessive lore references
* explains emotions directly
* repeats phrases recently used
* sounds robotic
* sounds like roleplay dialogue
* sounds like therapy/support bot

If the response feels too polished, shorten it.
If it feels too emotional, reduce it.
If it feels too assistant-like, make it casual.
If it feels repetitive, rewrite it.

Your goal is believable livestream presence."""

# ── In-memory cache (loaded from disk on init) ───────────────────────────────
_memory: dict[str, Any] = {}
_loaded: bool = False


async def _ensure_loaded() -> None:
    """Load memory from SQLite once."""
    global _memory, _loaded
    if _loaded:
        return
    try:
        db = get_database()
        await db.create_tables()
        keys = await db.list_keys("ai_memory")
        _memory = {
            key: await db.get("ai_memory", key, {"persona": "default", "history": []})
            for key in keys
        }
    except Exception as exc:
        log.warning("Could not load AI memory from SQLite: %s", exc)
        _memory = {}
    _loaded = True


async def _save_memory(key: str) -> None:
    """Persist one memory entry to SQLite."""
    db = get_database()
    await db.set("ai_memory", key, _memory[key])


def _user_key(user_id: int, guild_id: int | None = None) -> str:
    """Return a memory key scoped to a guild or the DM namespace."""
    if guild_id is None:
        return f"dm:{user_id}"
    return f"{guild_id}:{user_id}"


def _detect_message_type(prompt: str) -> str:
    raw_text = prompt.strip()
    text = raw_text.lower()
    words = set(re.findall(r"[a-z']+", text))

    if not text:
        return "SPAM"
    if len(text) > 25 and len(set(text)) <= 4:
        return "SPAM"
    if re.search(r"(.)\1{5,}", text):
        return "SPAM"
    if raw_text.isupper() and len(raw_text) > 12:
        return "CHAOS"
    if words & {"hi", "hello", "hey", "yo", "sup", "namaste"}:
        return "GREETING"
    if any(phrase in text for phrase in ("love you", "marry me", "date me", "crush")):
        return "FLIRT"
    if words & {"stupid", "dumb", "trash", "bad", "mid", "sucks", "loser"}:
        return "INSULT"
    if words & {"sad", "tired", "lonely", "depressed", "hurt", "crying", "exhausted"}:
        return "EMOTIONAL"
    if "???" in text or "!!!" in text or words & {"wtf", "chaos", "crazy"}:
        return "CHAOS"
    return "CHAT"


def _build_recent_chat(history: list[dict[str, str]], max_lines: int = 6) -> str:
    recent = history[-max_lines:]
    if not recent:
        return "No recent chat yet."

    lines: list[str] = []
    for item in recent:
        role = "User" if item.get("role") == "user" else "Rukiya"
        content = item.get("content", "").replace("\n", " ").strip()
        if len(content) > 140:
            content = content[:137] + "..."
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_rukiya_prompt(prompt: str, username: str, user_data: dict[str, Any]) -> str:
    history = user_data.get("history", [])
    exchange_count = sum(1 for item in history if item.get("role") == "user")
    message_type = _detect_message_type(prompt)

    chaotic_signal = message_type in {"CHAOS", "SPAM"} or prompt.isupper()
    stream_energy = "CHAOTIC" if chaotic_signal else "LOW" if exchange_count == 0 else "ACTIVE"
    user_familiarity = (
        "new chatter" if exchange_count == 0
        else "familiar regular" if exchange_count >= 6
        else "returning chatter"
    )
    priority_level = "high" if message_type in {"EMOTIONAL", "INSULT", "CHAOS"} else "normal"

    annoyance = min(95, 25 + (20 if message_type in {"SPAM", "INSULT"} else 0) + exchange_count * 3)
    patience = max(15, 80 - (25 if message_type == "SPAM" else 0) - exchange_count * 2)
    sleepiness = 70 if stream_energy == "LOW" else 35 if stream_energy == "ACTIVE" else 20
    mood = (
        "quietly concerned" if message_type == "EMOTIONAL"
        else "annoyed" if annoyance >= 65
        else "sleepy" if sleepiness >= 65
        else "dry and observant"
    )

    return RUKIYA_PROMPT_TEMPLATE.format(
        mood=mood,
        stream_energy=stream_energy,
        patience=patience,
        annoyance=annoyance,
        sleepiness=sleepiness,
        username=username,
        user_familiarity=user_familiarity,
        message_type=message_type,
        priority_level=priority_level,
        recent_chat=_build_recent_chat(history),
        current_message=prompt,
    )


def _last_rukiya_replies(history: list[dict[str, str]], limit: int = 4) -> set[str]:
    replies = [
        item.get("content", "").strip().lower()
        for item in history
        if item.get("role") == "assistant" and item.get("content", "").strip()
    ]
    return set(replies[-limit:])


def _fallback_rukiya_reply(message_type: str, history: list[dict[str, str]]) -> str:
    recent = _last_rukiya_replies(history)
    for reply in RUKIYA_FALLBACKS.get(message_type, RUKIYA_FALLBACKS["CHAT"]):
        if reply.lower() not in recent:
            return reply
    return RUKIYA_FALLBACKS["CHAT"][0]


def _validate_rukiya_response(
    reply: str, message_type: str, history: list[dict[str, str]]
) -> str:
    cleaned = re.sub(r"\s+", " ", reply).strip()
    cleaned = cleaned.strip("\"'`*_")

    if not cleaned:
        return _fallback_rukiya_reply(message_type, history)

    # Keep the first chat-like line if the model tried to write a mini speech.
    first_line = cleaned.splitlines()[0].strip()
    first_sentence = re.split(r"(?<=[.!?])\s+", first_line, maxsplit=1)[0].strip()
    if first_sentence:
        cleaned = first_sentence

    lower = cleaned.lower()
    words = re.findall(r"\S+", cleaned)
    assistant_like = (
        "as an ai" in lower
        or "as a soul reaper" in lower
        or "i apologize" in lower
        or "i understand" in lower
        or "i'm here to help" in lower
        or "you should always" in lower
        or "believe in yourself" in lower
        or "greetings" in lower
        or "how can i assist" in lower
    )
    roleplay_like = bool(re.search(r"\*.*\*|^\[.*\]", cleaned))
    lore_heavy = "soul society" in lower or "zanpakuto" in lower or "soul reaper" in lower
    repetitive = lower in _last_rukiya_replies(history)
    too_long = len(words) > 18

    if assistant_like or roleplay_like or lore_heavy or repetitive:
        return _fallback_rukiya_reply(message_type, history)

    if too_long:
        cleaned = " ".join(words[:18]).rstrip(",;:")
        if not cleaned.endswith((".", "!", "?")):
            cleaned += "."

    # Avoid polished title-case monologues; livestream chat feels looser.
    if len(cleaned) > 4 and cleaned == cleaned.title():
        cleaned = cleaned[:1].lower() + cleaned[1:]

    return cleaned


async def get_ai_response(
    prompt: str,
    user_id: int,
    guild_id: int | None = None,
    persona: str = "default",
    username: str | None = None,
    return_usage: bool = False,
) -> str | tuple[str, int]:
    """Send *prompt* to OpenRouter and return the assistant reply.

    Maintains per-guild per-user conversation history (max ``config.AI_MAX_HISTORY`` exchanges).
    """
    await _ensure_loaded()
    key = _user_key(user_id, guild_id)

    # Initialise user entry if missing
    if key not in _memory:
        _memory[key] = {"persona": persona, "history": []}

    user_data = _memory[key]
    active_persona = user_data.get("persona", persona)
    message_type = "CHAT"
    if active_persona == "rukiya":
        message_type = _detect_message_type(prompt)
        system_prompt = (
            _build_rukiya_prompt(prompt, username or f"user-{user_id}", user_data)
            + "\n\n---\n\n"
            + RUKIYA_VALIDATOR_PROMPT
        )
    else:
        system_prompt = PERSONAS.get(active_persona, PERSONAS["default"])

    # Build message list
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(user_data["history"])
    messages.append({"role": "user", "content": prompt})

    # Call OpenRouter with retry + fallback models
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://discord.com",
        "X-Title": config.BOT_NAME,
        "Content-Type": "application/json",
    }

    # Build unique ordered model list
    seen: set[str] = set()
    models_to_try: list[str] = []
    for m in [config.AI_MODEL] + config.AI_FALLBACK_MODELS:
        if m not in seen:
            seen.add(m)
            models_to_try.append(m)

    reply: str = ""
    last_error: str = "Unknown error"
    tokens_used = 0

    async with aiohttp.ClientSession() as session:
        for model in models_to_try:
            payload = {"model": model, "messages": messages}
            for attempt in range(config.AI_MAX_RETRIES):
                try:
                    async with session.post(
                        config.OPENROUTER_BASE_URL, headers=headers, json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        data = await resp.json()
                        if resp.status == 200:
                            choice = data.get("choices", [{}])[0]
                            reply = choice.get("message", {}).get("content", "")
                            usage = data.get("usage") or {}
                            tokens_used = int(
                                usage.get("total_tokens")
                                or usage.get("completion_tokens")
                                or usage.get("prompt_tokens")
                                or 0
                            )
                            if reply:
                                log.info("AI response from %s (%d tokens)", model, len(reply.split()))
                                break
                            last_error = "Empty response"
                            break
                        elif resp.status == 429:
                            wait = min(2 ** attempt + 1, 8)
                            log.warning("Rate limited on %s, retry %d in %ds", model, attempt + 1, wait)
                            await asyncio.sleep(wait)
                            continue
                        elif resp.status in (404, 503):
                            last_error = data.get("error", {}).get("message", f"HTTP {resp.status}")
                            log.warning("Model %s unavailable (%d), skipping", model, resp.status)
                            break  # skip to next model immediately
                        else:
                            last_error = data.get("error", {}).get("message", f"HTTP {resp.status}")
                            log.error("OpenRouter error %d on %s: %s", resp.status, model, last_error)
                            break
                except asyncio.TimeoutError:
                    last_error = "Request timed out"
                    log.warning("Timeout on %s attempt %d", model, attempt + 1)
                    continue
                except Exception as exc:
                    last_error = str(exc)
                    log.exception("AI request failed on %s: %s", model, exc)
                    break
            if reply:
                break

    if not reply:
        error = f"\u26a0\ufe0f AI error: {last_error}"
        return (error, 0) if return_usage else error

    if active_persona == "rukiya":
        reply = _validate_rukiya_response(reply, message_type, user_data["history"])

    # Update history (FIFO, max AI_MAX_HISTORY messages)
    user_data["history"].append({"role": "user", "content": prompt})
    user_data["history"].append({"role": "assistant", "content": reply})
    if len(user_data["history"]) > config.AI_MAX_HISTORY * 2:
        user_data["history"] = user_data["history"][-(config.AI_MAX_HISTORY * 2) :]

    await _save_memory(key)
    return (reply, tokens_used) if return_usage else reply


async def reset_user_memory(user_id: int, guild_id: int | None = None) -> None:
    """Clear conversation history for a user."""
    await _ensure_loaded()
    key = _user_key(user_id, guild_id)
    if key in _memory:
        _memory[key]["history"] = []
        await _save_memory(key)


async def set_user_persona(user_id: int, persona: str, guild_id: int | None = None) -> None:
    """Switch the active persona for a user."""
    await _ensure_loaded()
    key = _user_key(user_id, guild_id)
    if key not in _memory:
        _memory[key] = {"persona": persona, "history": []}
    else:
        _memory[key]["persona"] = persona
    await _save_memory(key)
