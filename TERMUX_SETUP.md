# راه‌اندازی بات روی Termux (گوشی Android)

## مرحله ۱ — نصب Termux درست

❌ از Google Play نصب نکن (نسخه قدیمیه)
✅ از **F-Droid** نصب کن:

1. مرورگر گوشی → `f-droid.org`
2. دانلود و نصب F-Droid
3. داخل F-Droid سرچ کن: `Termux`
4. نصب کن

---

## مرحله ۲ — آپدیت Termux

Termux رو باز کن، این دستورات رو یکی یکی بزن:

```bash
pkg update -y
pkg upgrade -y
```

(اگه سوال پرسید Y بزن)

---

## مرحله ۳ — نصب Python و Git

```bash
pkg install python git -y
pip install aiohttp
```

---

## مرحله ۴ — دانلود بات

```bash
git clone https://github.com/ashkan-code/comfyui-wanvideowrapper.git bot
cd bot
```

---

## مرحله ۵ — اجرای بات

```bash
python -m bitunix_scanner.main --live --auto
```

---

## مرحله ۶ — جلوگیری از خاموش شدن (مهم!)

### روش الف — Termux:Tasker (توصیه می‌شه)
در F-Droid نصب کن: `Termux:Boot`
بعد این فایل رو بساز:

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-bot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/bot
python -m bitunix_scanner.main --live --auto >> ~/bot/logs/bitunix_live.log 2>&1 &
EOF
chmod +x ~/.termux/boot/start-bot.sh
```

### روش ب — دستی (ساده‌تر)
- تنظیمات گوشی → برنامه‌ها → Termux
- **باتری**: غیرفعال کردن بهینه‌سازی باتری
- **نمایش**: روشن نگه داشتن صفحه

---

## مرحله ۷ — اجرای پشت‌زمینه

داخل Termux این رو بزن تا بات پس‌زمینه اجرا بشه:

```bash
cd ~/bot
nohup python3 bitunix_watchdog.py > logs/watchdog_stdout.log 2>&1 &
echo "بات راه افتاد!"
```

---

## بررسی وضعیت

```bash
cd ~/bot
tail -10 logs/bitunix_live.log
```

---

## نکات مهم

- گوشی رو به **شارژر** وصل نگه دار
- **بهینه‌سازی باتری** Termux رو خاموش کن
- از **وای‌فای ثابت** استفاده کن
- صفحه می‌تونه خاموش باشه — بات کار می‌کنه
