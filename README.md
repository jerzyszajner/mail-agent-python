# Mail agent v2 (Gmail + Gemini)

Batch CLI: fetches **unread** threads from Gmail `INBOX`, analyzes each with Gemini, and applies Gmail actions based on classification.

## What v2 does

- **Thread-aware**: groups unread messages by thread, fetches full conversation context via `threads.get`, and replies to the latest message from the external sender
- Processes up to N unread threads in one run (default 10)
- Classifies each thread: category, urgency, recommended action
- `--draft` creates reply drafts for messages classified as `reply`
- `--apply` executes Gmail actions: move spam, archive ignored, mark read
- Without `--apply` the run is analysis-only (safe preview mode)
- Returns a JSON array with results for all processed messages

## Requirements

- Python 3.10+
- Gemini key in `.env` (`GEMINI_API_KEY`)
- Reply signature name in `.env` (`REPLY_NAME`)
- `credentials.json` (OAuth client type: **Desktop app**) in the project root
- In Google Cloud: Gmail API enabled + OAuth consent configured + your account added as a test user

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

```env
GEMINI_API_KEY=your_api_key_here
REPLY_NAME=Your Name
```

## Run

Analyze up to 10 unread messages (read-only preview):

```bash
python gmail_analyze.py
```

Analyze and create draft replies where appropriate:

```bash
python gmail_analyze.py --draft
```

Full mode — drafts + Gmail actions (spam, archive, mark read):

```bash
python gmail_analyze.py --draft --apply
```

Limit to 3 messages:

```bash
python gmail_analyze.py --max 3 --draft --apply
```

On first run, a browser will open for OAuth login. The app stores local credentials cache in `token.json` (file permissions `0600`, treat it as a secret).

**Upgrading from v1:** remove `token.json` to refresh OAuth scopes (`gmail.modify` replaces the old `gmail.readonly` + `gmail.compose`).

## Action dispatch

| Classification | Gmail action (`--apply`) | Draft? |
|---|---|---|
| `category: spam` | move to spam | no |
| `action: ignore` | archive (remove from INBOX) | no |
| `action: mark_read` | mark as read | no |
| `action: reply` | — | yes (with `--draft`) |
| `action: forward` | mark as read | no (forward manually) |

Without `--apply`, no Gmail modifications are made — the output shows what *would* happen.

## JSON contract

Output is a JSON array (one entry per thread):

```json
[
  {
    "from": "sender@example.com",
    "subject": "Meeting tomorrow",
    "category": "urgent | normal | spam",
    "urgency": "high | medium | low",
    "action": "reply | forward | ignore | mark_read",
    "suggested_reply": "string (empty for non-reply actions)",
    "result": "draft created | moved to spam | archived | marked as read | analysis only | analysis failed"
  }
]
```

## Analysis pipeline

- `gmail_analyze.py` fetches unread threads via `threads.get` API, builds full conversation context with `[SENDER]`/`[ME]` role markers, and dispatches actions
- `analysis.py` orchestrates the Gemini flow: input pre-screen -> generate -> validate -> anti-echo retry
- `analysis_schema.py` contains the fixed schema and strict JSON validation (`additionalProperties=false`, text limits)
- `analysis_text.py` contains reply text normalization, reply composition, similarity checks, and injection signal heuristics
- `drafts.py` creates reply drafts with proper `In-Reply-To` and `References` threading headers
- `gmail_actions.py` contains Gmail label operations (mark read, archive, report spam)

## Tests

```bash
python -m unittest discover tests/ -v
```

## Security behavior (prompt injection hardening)

- Multi-layer defense: regex pre-screen, LLM guard (via `system_instruction`), schema validation, output inspection, anti-echo
- Randomized boundary markers around untrusted email content (prevents marker spoofing)
- Detects Unicode confusables, ROT13, base64-encoded payloads, typoglycemia, split markers, zero-width characters
- ROT13 detection uses heuristic gating to reduce false positives on normal English text
- HTML stripping removes hidden content: `display:none`, `visibility:hidden`, `opacity:0`, `font-size:0`
- Suspicious inputs are blocked with a generic message (no feedback to attacker)
- Draft creation blocked for high-risk situations
- Suspicious threads are marked as read with `--apply` to prevent infinite re-processing, but stay in INBOX for manual review (not moved to spam — avoids false-positive risk)
- Technical failures (API errors) leave threads untouched for retry on next run
- API calls enforce a 60-second timeout to prevent indefinite hangs

## Known limits

- No prompt-injection defense is perfect; filters can produce false positives or false negatives
- Treat model output as assistive, not authoritative — review before using `--draft`
- Each thread requires separate Gemini API calls (guard + analysis); processing 10 threads takes ~30-60 seconds
