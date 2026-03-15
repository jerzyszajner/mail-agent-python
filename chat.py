from dotenv import load_dotenv
from google import genai
from google.genai import types
from datetime import datetime
import json
load_dotenv()

client = genai.Client()
chat = client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(
        system_instruction="You are an email assistant. Categorize emails and suggest professional replies.",
        temperature=0.4,
        max_output_tokens=2000,
    )
)
chat_history = []

while True:
    user_input = input("Your message: ")
    if user_input.lower() in ("exit", "quit", "q"):
        break
    if user_input.lower() in ("history", "h"):
        print("chat history:")
        for message in chat_history:
            print(f"{message['role']}: {message['content']}")
        continue

    if user_input.lower() in ("analyze", "a"):
        test_email = "Hi, urgent invoice payment overdue for order #12345"
        email_schema = {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["urgent", "normal", "spam"]},
                "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
                "action": {"type": "string", "enum": ["reply", "forward", "ignore", "mark_read"]},
                "suggested_reply": {"type": "string"},
            },
            "required": ["category", "urgency", "action", "suggested_reply"],
        }

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Analyze this email and return classification plus suggested reply.\n\nEmail: {test_email}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=email_schema,
            ),
        )
        parsed = json.loads(response.text)

        print(f"📧 TEST MAIL: {test_email}")
        print(f"✅ Category: {parsed['category']} | Action: {parsed['action']}")
        print(f"🤖 {json.dumps(parsed, ensure_ascii=False, indent=2)}")
        continue
 
    chat_history.append({"role": "user", "content": user_input})

    response = chat.send_message(user_input)
    assistant_text = response.text

    timestamp = datetime.now().strftime("%H:%M:%S")
    with open("mail_log.txt", "a") as f:
        f.write(f"[{timestamp}] {user_input}\n[{timestamp}] {assistant_text}\n\n")
    print("Saved!")



    chat_history.append({"role": "assistant", "content": assistant_text})
    print(assistant_text)


