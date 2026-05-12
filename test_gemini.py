import urllib.request
import json
import os
import ssl
import certifi
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('GEMINI_API_KEY')
api_url = os.getenv('GEMINI_API_URL')
model = os.getenv('GEMINI_MODEL')

payload = {
    'model': model,
    'messages': [
        {'role': 'system', 'content': 'You are a test bot.'},
        {'role': 'user', 'content': 'Say hello in Albanian'}
    ],
    'temperature': 0.3
}

context = ssl.create_default_context(cafile=certifi.where())

req = urllib.request.Request(
    api_url, 
    data=json.dumps(payload).encode('utf-8'),
    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    method='POST'
)

try:
    with urllib.request.urlopen(req, context=context) as resp:
        print(json.loads(resp.read().decode('utf-8')))
except Exception as e:
    print(e)
    # read error response body if available
    if hasattr(e, 'read'):
        print(e.read().decode('utf-8'))
