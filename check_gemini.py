import os
from dotenv import load_dotenv
load_dotenv()
from google import genai
key = os.getenv("GEMINI_API_KEY", "")
print("key length:", len(key), "| starts with:", key[:4])
model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
try:
    client = genai.Client(api_key=key)
    r = client.models.generate_content(model=model, contents="Say OK")
    print("WORKS:", r.text)
except Exception as e:
    print(type(e).__name__, str(e)[:300])
