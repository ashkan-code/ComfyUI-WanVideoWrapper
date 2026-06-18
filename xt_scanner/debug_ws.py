"""
Quick diagnostic — connects to XT.com WebSocket for one symbol
and prints every raw message received for 30 seconds.
Run: python debug_ws.py
"""
import asyncio, json, websockets

WS_URL  = "wss://stream.xt.com/public"
SYMBOL  = "btc_usdt"
TIMEOUT = 30

async def main():
    print(f"Connecting to {WS_URL} ...")
    async with websockets.connect(WS_URL, ping_interval=20) as ws:
        print("Connected! Sending subscriptions ...")

        subs = [
            {"method": "subscribe", "params": [f"trade@{SYMBOL}"], "id": 1},
            {"method": "subscribe", "params": [f"depth@{SYMBOL},5"], "id": 2},
        ]
        for s in subs:
            await ws.send(json.dumps(s))
            print(f"  Sent: {s}")

        print(f"\nWaiting {TIMEOUT}s for messages ...\n")
        try:
            async with asyncio.timeout(TIMEOUT):
                count = 0
                async for raw in ws:
                    msg = json.loads(raw)
                    count += 1
                    print(f"[MSG #{count}] {json.dumps(msg)[:400]}")
                    if count >= 20:
                        print("Got 20 messages, stopping.")
                        break
        except asyncio.TimeoutError:
            print("Timeout — no more messages.")

asyncio.run(main())
