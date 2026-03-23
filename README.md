# Mail agent v1 (Gmail + Gemini)

Minimal CLI: fetches the **newest** message from Gmail `INBOX`, analyzes it with Gemini, and prints **one JSON** to stdout.

## What v1 does

- Run only: `python gmail_analyze.py`
- Reads only the newest email (`maxResults=1`)
- Does not send emails and does not create drafts
- Returns JSON matching a fixed schema

## Requirements

- Python 3.10+
- Gemini key in `.env` (`GEMINI_API_KEY`)
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
```

## Run

```bash
python gmail_analyze.py
```

On first run, a browser will open for OAuth login. The app stores local credentials cache in `token.json` (treat it as a secret).

## JSON contract

```json
{
  "category": "urgent | normal | spam",
  "urgency": "high | medium | low",
  "action": "reply | forward | ignore | mark_read",
  "suggested_reply": "string"
}
```

If INBOX is empty, the script prints `No messages in INBOX.` and exits without an error.
