"""استخراج سوالات از PDF/تصویر با Claude Vision"""

import anthropic
import base64
import json
import re


PROMPT = """این تصویر از دفترچه آزمون دکتری رشته سازه (مهندسی عمران - گرایش سازه) است.

تمام سوالات چهارگزینه‌ای را استخراج کن. برای هر سوال یک آبجکت JSON بساز:

{
  "text": "متن کامل سوال (با فرمول‌ها به صورت متن یا LaTeX اگر ممکن است)",
  "options": ["گزینه ۱", "گزینه ۲", "گزینه ۳", "گزینه ۴"],
  "correct_answer": null,
  "subject": "نام درس از این لیست: مکانیک جامدات | مقاومت مصالح | تحلیل سازه | دینامیک سازه | طراحی بتن | طراحی فولاد | خاک و پی | ریاضی مهندسی | المان محدود | عمومی",
  "topic": "موضوع اصلی (مثلاً: تنش محوری، خمش، ارتعاش آزاد، ظرفیت باربری)",
  "subtopic": "زیرموضوع دقیق‌تر اگر وجود دارد",
  "difficulty": "easy یا medium یا hard",
  "year": null
}

اگر تصویر سوال ندارد یا خوانا نیست، [] برگردان.
فقط آرایه JSON خروجی بده."""


def _extract_from_b64(client: anthropic.Anthropic, b64: str, media_type: str) -> list[dict]:
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    text = response.content[0].text.strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    return json.loads(m.group() if m else text)


def extract_from_image(
    client: anthropic.Anthropic,
    image_bytes: bytes,
    media_type: str,
    source_name: str = "",
    year: int = None,
) -> list[dict]:
    b64 = base64.standard_b64encode(image_bytes).decode()
    questions = _extract_from_b64(client, b64, media_type)
    for q in questions:
        q["source_file"] = source_name
        if year:
            q["year"] = year
    return questions


def extract_from_pdf(
    client: anthropic.Anthropic,
    pdf_bytes: bytes,
    source_name: str = "",
    year: int = None,
    progress_cb=None,
) -> list[dict]:
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = len(doc)
    all_qs: list[dict] = []

    for i in range(total):
        if progress_cb:
            progress_cb(i, total)
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        b64 = base64.standard_b64encode(pix.tobytes("png")).decode()
        try:
            qs = _extract_from_b64(client, b64, "image/png")
            for q in qs:
                q["source_file"] = f"{source_name} | ص{i+1}"
                if year:
                    q["year"] = year
            all_qs.extend(qs)
        except Exception as e:
            print(f"[extractor] خطا ص{i+1}: {e}")

    if progress_cb:
        progress_cb(total, total)
    doc.close()
    return all_qs
