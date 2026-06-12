"""
Quick Telegram test — run: python test_telegram.py
"""
import urllib.request, json

TOKEN  = "8856332073:AAFTQs0NhEh3PoUsRw9YXRuJfTBJvkBh0bg"
CHAT_ID = "554649373"

# 1. Check bot info
print("1. Checking bot token ...")
url = f"https://api.telegram.org/bot{TOKEN}/getMe"
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        print(f"   Bot name: {data['result']['first_name']}")
        print(f"   Username: @{data['result']['username']}")
except Exception as e:
    print(f"   ERROR: {e}")

# 2. Get updates to find real chat id
print("\n2. Getting recent messages (to find your chat ID) ...")
url2 = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
try:
    with urllib.request.urlopen(url2, timeout=10) as r:
        data = json.loads(r.read())
        updates = data.get("result", [])
        if updates:
            for u in updates[-3:]:
                msg = u.get("message", {})
                chat = msg.get("chat", {})
                print(f"   Chat ID: {chat.get('id')}  | from: {chat.get('first_name','?')}")
        else:
            print("   No messages found — send /start to your bot first")
except Exception as e:
    print(f"   ERROR: {e}")

# 3. Try sending message
print(f"\n3. Sending test message to chat_id={CHAT_ID} ...")
url3 = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
data = json.dumps({"chat_id": CHAT_ID, "text": "✅ Test from XT Scanner!"}).encode()
req = urllib.request.Request(url3, data=data, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
        if result.get("ok"):
            print("   SUCCESS — message sent!")
        else:
            print(f"   FAILED: {result.get('description')}")
except Exception as e:
    print(f"   ERROR: {e}")
