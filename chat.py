from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client()

user_input = input("Your message: ")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=user_input,
)
print(response.text)
