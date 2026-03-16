from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os, pickle, base64

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

creds = None
if os.path.exists("token.json"):
    with open("token.json", "rb") as token:
        creds = pickle.load(token)

if not creds:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "wb") as token:
        pickle.dump(creds, token)

service = build("gmail", "v1", credentials=creds)
results = service.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=5).execute()
messages = results.get("messages", [])

print(f"Found {len(messages)} messages")
for m in messages:
    msg = service.users().messages().get(userId="me", id=m["id"]).execute()
    headers = msg["payload"].get("headers", [])
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")
    print("-", subject)