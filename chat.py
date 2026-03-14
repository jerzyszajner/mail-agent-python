from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client()
chat = client.chats.create(model="gemini-2.5-flash")
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

    chat_history.append({"role": "user", "content": user_input})

    response = chat.send_message(user_input)
    assistant_text = response.text

    chat_history.append({"role": "assistant", "content": assistant_text})
    print(assistant_text)


