#!/usr/bin/env python3
"""
XT.com Triangular Arbitrage Bot — فایل تک‌تکه
اجرا: python xt_arb.py --check
      python xt_arb.py               (dry-run)
      python xt_arb.py --live        (معامله واقعی)
"""
import argparse, hashlib, hmac, json, logging, os, sys, time, urllib.parse
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import httpx
except ImportError:
    print("نصب: pip install httpx")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════
# تنظیمات
# ══════════════════════════════════════════════════════════════
API_KEY    = os.getenv("XT_API_KEY", "")
API_SECRET = os.getenv("XT_API_SECRET", "")
BASE_URL   = "https://sapi.xt.com"

TRADING_FEE     = 0.002   # کارمزد هر معامله ۰.۲٪  (اگه VIP داری کمتر کن)
MIN_PROFIT_PCT  = 0.10    # حداقل سود خالص ۰.۱٪ بعد از کارمزد
TRADE_USDT      = 100.0   # حجم هر چرخه آربیتراژ به USDT
SCAN_INTERVAL   = 1.0     # هر ۱ ثانیه اسکن
MAX_TRADES_MIN  = 10      # حداکثر ۱۰ معامله در دقیقه
MAX_FAIL        = 5       # توقف بعد از ۵ شکست متوالی
MAX_DAILY_LOSS  = 20.0    # حد ضرر روزانه (USDT)
DRY_RUN         = True    # False = معامله واقعی

# ══════════════════════════════════════════════════════════════
# کلاینت API
# ══════════════════════════════════════════════════════════════
class XTClient:
    def __init__(self, key="", secret=""):
        self.key = key
        self.secret = secret
        self.http = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)
        )

    def _sign(self, path, qs="", body=""):
        ts = str(int(time.time() * 1000))
        parts = []
        if path:  parts.append(f"path={path}")
        if qs:    parts.append(f"query={qs}")
        if body:  parts.append(f"body={body}")
        sig = hmac.new(self.secret.encode(), "&".join(parts).encode(), hashlib.sha256).hexdigest()
        return ts, sig

    def _hdrs(self, path, qs="", body=""):
        ts, sig = self._sign(path, qs, body)
        return {"validate-appkey": self.key, "validate-timestamp": ts,
                "validate-signature": sig, "validate-algorithms": "HmacSHA256",
                "Content-Type": "application/json"}

    def _parse(self, r):
        d = r.json()
        if "rc" in d:
            if d["rc"] != 0: raise Exception(f"API {d['rc']}: {d.get('mc')}")
            return d.get("result")
        if "code" in d:
            if d["code"] != 200: raise Exception(f"API {d['code']}: {d.get('info')}")
            return d.get("data", d.get("result"))
        return d

    def get(self, path, params=None, auth=False):
        qs = urllib.parse.urlencode(params or {})
        url = BASE_URL + path + (f"?{qs}" if qs else "")
        hdrs = self._hdrs(path, qs) if auth else {"Content-Type": "application/json"}
        r = self.http.get(url, headers=hdrs)
        r.raise_for_status()
        return self._parse(r)

    def post(self, path, body=None):
        bs = json.dumps(body or {}, separators=(",", ":"))
        r = self.http.post(BASE_URL + path, content=bs, headers=self._hdrs(path, "", bs))
        r.raise_for_status()
        return self._parse(r)

    def delete(self, path, params=None):
        qs = urllib.parse.urlencode(params or {})
        url = BASE_URL + path + (f"?{qs}" if qs else "")
        r = self.http.delete(url, headers=self._hdrs(path, qs))
        r.raise_for_status()
        return self._parse(r)

    def tickers(self, retries=3):
        for i in range(retries):
            try:
                raw = self.get("/v4/public/ticker/book")
                return raw if isinstance(raw, list) else raw.get("tickers", []) if isinstance(raw, dict) else []
            except Exception as e:
                if i == retries - 1: raise
                time.sleep(2 ** i)  # 1s, 2s, 4s
        return []

    def orderbook(self, sym, limit=10):
        return self.get("/v4/public/depth", {"symbol": sym, "limit": limit})

    def balances(self):
        return self.get("/v4/balances", auth=True)

    def place_order(self, symbol, side, qty, price=None):
        body = {"symbol": symbol, "side": side, "type": "MARKET" if not price else "LIMIT",
                "quantity": str(qty)}
        if price: body["price"] = str(price)
        return self.post("/v4/order", body)

    def close(self): self.http.close()

# ══════════════════════════════════════════════════════════════
# اسکنر آربیتراژ مثلثی
# ══════════════════════════════════════════════════════════════
@dataclass
class Leg:
    symbol: str; side: str; price: float; base: str; quote: str

@dataclass
class Opp:
    legs: list
    net_pct: float
    start: float
    end: float

    def __str__(self):
        path = " → ".join(f"{l.symbol}({l.side})" for l in self.legs)
        return f"[{self.net_pct:+.4f}%] {path} | {self.start:.2f}→{self.end:.4f} USDT"

def _convert(amount, from_c, edge, fee):
    sym = edge["symbol"]
    base, quote = sym.split("_")
    if from_c == base:
        out = amount * edge["bid"] * (1 - fee)
        return out, Leg(sym, "SELL", edge["bid"], base, quote)
    else:
        out = (amount / edge["ask"]) * (1 - fee)
        return out, Leg(sym, "BUY", edge["ask"], base, quote)

def find_opps(tickers, fee=TRADING_FEE, min_pct=MIN_PROFIT_PCT, amount=TRADE_USDT):
    # ساخت گراف
    G = {}
    for t in tickers:
        sym = (t.get("s") or t.get("symbol") or "").lower()
        bid = float(t.get("bp") or t.get("bidPrice") or t.get("bid") or 0)
        ask = float(t.get("ap") or t.get("askPrice") or t.get("ask") or 0)
        if not sym or "_" not in sym or bid <= 0 or ask <= 0: continue
        base, quote = sym.split("_", 1)
        edge = {"symbol": sym, "bid": bid, "ask": ask}
        G.setdefault(base, {})[quote] = edge
        G.setdefault(quote, {})[base] = edge

    results = []
    base_curr = "usdt"
    for mid1, e1 in G.get(base_curr, {}).items():
        a1, l1 = _convert(amount, base_curr, e1, fee)
        if a1 <= 0: continue
        for mid2, e2 in G.get(mid1, {}).items():
            if mid2 == base_curr: continue
            a2, l2 = _convert(a1, mid1, e2, fee)
            if a2 <= 0: continue
            if base_curr not in G.get(mid2, {}): continue
            a3, l3 = _convert(a2, mid2, G[mid2][base_curr], fee)
            if a3 <= 0: continue
            pct = (a3 - amount) / amount * 100
            if pct >= min_pct:
                results.append(Opp([l1, l2, l3], round(pct, 6), amount, round(a3, 6)))

    seen, unique = set(), []
    for o in sorted(results, key=lambda x: x.net_pct, reverse=True):
        k = "|".join(l.symbol for l in o.legs)
        if k not in seen:
            seen.add(k)
            unique.append(o)
    return unique

# ══════════════════════════════════════════════════════════════
# اجراکننده سفارشات
# ══════════════════════════════════════════════════════════════
_trades_ts = deque(maxlen=100)

def execute(client, opp, dry_run=True):
    now = time.time()
    recent = [t for t in _trades_ts if now - t < 60]
    if len(recent) >= MAX_TRADES_MIN:
        return False, "rate limit"

    prefix = "[DRY] " if dry_run else ""
    amount = opp.start

    for i, leg in enumerate(opp.legs, 1):
        qty = amount / leg.price if leg.side == "BUY" else amount
        log.info(f"{prefix}Leg {i}: {leg.symbol} {leg.side} qty={qty:.6f} @ {leg.price}")

        if not dry_run:
            try:
                client.place_order(leg.symbol, leg.side, round(qty, 6))
            except Exception as e:
                return False, f"Leg {i} failed: {e}"

        amount = qty * (1 - TRADING_FEE) if leg.side == "SELL" else (qty * leg.price) * (1 - TRADING_FEE) if False else qty * (1 - TRADING_FEE)

    _trades_ts.append(time.time())
    profit = opp.end - opp.start
    log.info(f"{prefix}✓ profit={profit:+.4f} USDT ({opp.net_pct:+.4f}%)")
    return True, profit

# ══════════════════════════════════════════════════════════════
# حلقه اصلی بات
# ══════════════════════════════════════════════════════════════
log = logging.getLogger("xt_arb")

def run_bot(dry_run=True, min_pct=MIN_PROFIT_PCT, amount=TRADE_USDT, interval=SCAN_INTERVAL):
    client = XTClient(API_KEY, API_SECRET)
    scans = 0; total_profit = 0.0; total_loss = 0.0; fails = 0
    start_time = time.time()

    log.info("═" * 55)
    log.info(f"  XT.com آربیتراژ مثلثی — {'DRY-RUN' if dry_run else '⚡ LIVE'}")
    log.info(f"  حداقل سود : {min_pct:.2f}%  |  حجم : {amount:.0f} USDT")
    log.info(f"  کارمزد    : {TRADING_FEE*100:.2f}%  |  سر‌به‌سر : {(1-(1-TRADING_FEE)**3)*100:.3f}%")
    log.info("═" * 55)

    try:
        while True:
            t0 = time.time()
            try:
                tks = client.tickers()
                if not tks:
                    log.warning("هیچ تیکری دریافت نشد")
                    time.sleep(interval); continue

                scans += 1
                opps = find_opps(tks, min_pct=min_pct, amount=amount)

                if opps:
                    best = opps[0]
                    log.info(f"فرصت: {best}")
                    ok, result = execute(client, best, dry_run)
                    if ok:
                        if isinstance(result, float):
                            if result >= 0: total_profit += result
                            else:           total_loss   += abs(result)
                        fails = 0
                    else:
                        fails += 1
                        log.warning(f"شکست: {result}")
                        if fails >= MAX_FAIL:
                            log.error(f"⛔ {MAX_FAIL} شکست متوالی — توقف")
                            break
                    daily_loss = total_loss - total_profit
                    if daily_loss >= MAX_DAILY_LOSS:
                        log.error(f"⛔ حد ضرر روزانه: {daily_loss:.2f} USDT — توقف")
                        break
                else:
                    if scans % 30 == 0:
                        up = int(time.time() - start_time)
                        h, r = divmod(up, 3600); m, s = divmod(r, 60)
                        log.info(f"اسکن #{scans} | آپتایم {h:02d}:{m:02d}:{s:02d} | سود={total_profit:.4f} ضرر={total_loss:.4f}")

            except Exception as e:
                log.error(f"خطای اسکن: {e}")

            elapsed = time.time() - t0
            sleep = max(0, interval - elapsed)
            if sleep: time.sleep(sleep)

    except KeyboardInterrupt:
        log.info("بات متوقف شد (Ctrl+C)")
    finally:
        log.info(f"خلاصه: اسکن={scans} | سود={total_profit:.4f} | ضرر={total_loss:.4f} | P&L={total_profit-total_loss:+.4f} USDT")
        client.close()

# ══════════════════════════════════════════════════════════════
# حالت چک — تشخیص فیلدهای API
# ══════════════════════════════════════════════════════════════
def run_check():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log2 = logging.getLogger("check")
    client = XTClient(API_KEY, API_SECRET)

    log2.info("══ تست اتصال به XT.com ══")
    try:
        tks = client.tickers()
        log2.info(f"✓ {len(tks)} تیکر دریافت شد")
        if tks:
            s = tks[0]
            log2.info(f"  نمونه خام: {s}")
            sym = s.get("s") or s.get("symbol") or "❌"
            bid = s.get("bp") or s.get("bidPrice") or s.get("bid") or "❌"
            ask = s.get("ap") or s.get("askPrice") or s.get("ask") or "❌"
            log2.info(f"  symbol={sym}  bid={bid}  ask={ask}")
            ok = "❌" not in (str(sym), str(bid), str(ask))
            log2.info(f"  {'✓ فیلدها OK' if ok else '❌ فیلد اشتباه! کلیدهای موجود: ' + str(list(s.keys()))}")
    except Exception as e:
        log2.error(f"❌ خطا: {e}")
        client.close(); return

    log2.info("")
    log2.info("══ بهترین مسیرها (بدون آستانه سود) ══")
    opps = find_opps(tks, min_pct=-99.0, amount=100.0)
    log2.info(f"  {len(opps)} مسیر پیدا شد. بهترین ۵ تا:")
    for o in opps[:5]:
        log2.info(f"  {o}")
    if opps:
        be = (1-(1-TRADING_FEE)**3)*100
        best = opps[0]
        log2.info(f"  سر‌به‌سر: {be:.3f}%  |  بهترین الان: {best.net_pct:+.4f}%")
        if best.net_pct > 0:
            log2.info("  ✓ فرصت سودآور همین الان وجود دارد!")
        else:
            log2.info("  بازار الان کارآمد است. فرصت در نوسانات ظاهر می‌شود.")

    if API_KEY and API_SECRET:
        log2.info("")
        log2.info("══ تست احراز هویت ══")
        try:
            bals = client.balances() or []
            usdt = next((b for b in bals if str(b.get("currency","")).lower()=="usdt"), None)
            val = usdt.get("availableAmount") or usdt.get("free") or "?" if usdt else f"{len(bals)} ارز"
            log2.info(f"  ✓ احراز هویت OK  |  موجودی USDT: {val}")
        except Exception as e:
            log2.error(f"  ❌ خطای احراز هویت: {e}")

    client.close()
    log2.info("══ چک کامل شد ══")

# ══════════════════════════════════════════════════════════════
# ورودی
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--check",      action="store_true", help="تست اتصال و فیلدهای API")
    p.add_argument("--live",       action="store_true", help="معامله واقعی (پیش‌فرض: dry-run)")
    p.add_argument("--min-profit", type=float, default=MIN_PROFIT_PCT, help="حداقل سود ٪")
    p.add_argument("--amount",     type=float, default=TRADE_USDT,     help="حجم USDT")
    p.add_argument("--interval",   type=float, default=SCAN_INTERVAL,  help="ثانیه بین اسکن‌ها")
    args = p.parse_args()

    # خاموش کردن لاگ‌های اضافی httpx و httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if args.check:
        run_check()
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        run_bot(dry_run=not args.live, min_pct=args.min_profit,
                amount=args.amount, interval=args.interval)
