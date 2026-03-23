# Mail agent (Gmail + Gemini)

A small Python script: loads the **newest** Gmail **INBOX** message, decodes the body, sends it to **Gemini 2.5 Flash**, and prints **JSON** with category, urgency, suggested action, and a draft reply.

## Repository layout

| File | Role |
|------|------|
| `gmail_analyze.py` | Entry point: OAuth when needed, fetch message, call Gemini, print JSON |
| `gmail_client.py` | Decode bodies from Gmail API (`format=full`, multipart, base64) |
| `.env.example` | Template for `.env` (copy and fill in your API key) |

## Requirements

- Python 3.10+
- Gemini key in `.env` (`GEMINI_API_KEY`)
- Google Cloud project with **Gmail API** enabled, OAuth consent (e.g. testing), your account under **test users**
- **`credentials.json`** (OAuth client type **Desktop app**) in the project root

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy the env template and set your real key:

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholder with your Gemini API key:

```env
GEMINI_API_KEY=your_api_key_here
```

(On Windows: `copy .env.example .env`.)

## Run

```bash
python gmail_analyze.py
```

On first run (or after the token is revoked), a browser opens; sign in with the **Gmail account whose inbox you want to read**. The script writes **`token.json`** (pickled Google credentials - treat it as a secret).

## What the script does

1. Connects to Gmail API (`gmail.readonly`).
2. Lists INBOX with `maxResults=1` → **newest** thread.
3. `messages().get(..., format="full")` → `gmail_client.decode_full_message_body` extracts text (prefers `text/plain`).
4. Gemini receives From / Subject / Date + body and returns JSON matching a fixed schema.

**Note:** the script does **not** send email; it only prints analysis and `suggested_reply` to stdout.

## Example output (JSON)

```json
{
  "category": "normal",
  "urgency": "medium",
  "action": "reply",
  "suggested_reply": "Thank you, I will get back to you shortly."
}
```

Fields:

- `category`: `urgent` \| `normal` \| `spam`
- `urgency`: `high` \| `medium` \| `low`
- `action`: `reply` \| `forward` \| `ignore` \| `mark_read`
- `suggested_reply`: model-generated reply text

## Security

- `credentials.json` and `token.json` are local and **must not be committed** (listed in `.gitignore`).
- Message content is sent to the Gemini API - use accordingly.
