# Mail agent v1 (Gmail + Gemini)

Minimal CLI: fetches the **newest** message from Gmail `INBOX`, analyzes it with Gemini, and prints **one JSON** to stdout.

## What v1 does

- Run only: `python gmail_analyze.py`
- Reads only the newest email (`maxResults=1`)
- Optional: creates a reply draft with `--draft` (never sends automatically)
- Returns JSON matching a fixed schema

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

```bash
python gmail_analyze.py
```

Create a Gmail draft reply (safe mode, no sending):

```bash
python gmail_analyze.py --draft
```

On first run, a browser will open for OAuth login. The app stores local credentials cache in `token.json` (file permissions `0600`, treat it as a secret).
If you used an older token from read-only mode, remove `token.json` once to refresh OAuth scopes for draft creation.

## JSON contract

```json
{
  "category": "urgent | normal | spam",
  "urgency": "high | medium | low",
  "action": "reply | forward | ignore | mark_read",
  "suggested_reply": "string"
}
```

## Analysis pipeline

- `analysis.py` orchestrates the flow: input pre-screen -> generate -> validate -> anti-echo retry
- `analysis_schema.py` contains the fixed schema and strict JSON validation (`additionalProperties=false`, text limits)
- `analysis_text.py` contains reply text normalization, reply composition, similarity checks, and injection signal heuristics

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
- API calls enforce a 60-second timeout to prevent indefinite hangs

## Known limits

- No prompt-injection defense is perfect; filters can produce false positives or false negatives
- Treat model output as assistive, not authoritative — review before using `--draft`
