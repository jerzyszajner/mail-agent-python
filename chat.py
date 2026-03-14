from dotenv import load_dotenv
from google import genai
from google.genai import types
from datetime import datetime
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
        response = chat.send_message(test_email)
        print(f"📧 TEST MAIL: {test_email}")
        print(f"🤖 {response.text}")
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


