import httpx
import json

# API key removed: keep secrets in a private .env file (loaded via pydantic-settings)

# Models jo hum test karenge
MODELS_TO_TEST = [
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-pro-latest",
    "gemini-2.0-flash" # Agar yeh chal gaya toh best hai
]

payload = {
    "contents": [{"parts": [{"text": "Hello, reply with exactly: 'API is working perfectly!'"}]}]
}

print("🚀 Testing Gemini API...\n")

for model in MODELS_TO_TEST:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
    
    print(f"Testing Model: {model} ...")
    try:
        response = httpx.post(url, json=payload, timeout=15.0)
        
        if response.status_code == 200:
            data = response.json()
            reply = data['candidates'][0]['content']['parts'][0]['text']
            print(f"✅ SUCCESS! Model '{model}' is working.")
            print(f"🤖 Gemini Reply: {reply}\n")
            break # Agar ek model chal gaya, toh loop rok dein
        else:
            print(f"❌ Failed. Status Code: {response.status_code}")
            # Error ka detail nikaalein
            error_msg = response.json().get("error", {}).get("message", "Unknown error")
            print(f"Reason: {error_msg}\n")
            
    except Exception as e:
        print(f"❌ Network Error: {str(e)}\n")