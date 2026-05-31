import anthropic
import base64
import json
import re
from io import BytesIO


EXTRACTION_PROMPT = """تصویر زیر شامل سوالات تستی چندگزینه‌ای است (احتمالاً از کنکور یا آزمون‌های تستی ایران).

تمام سوالات را از این تصویر استخراج کن. برای هر سوال یک آبجکت JSON بساز:

{
  "text": "متن کامل سوال",
  "options": ["گزینه الف", "گزینه ب", "گزینه ج", "گزینه د"],
  "correct_answer": 0,
  "subject": "نام درس (مثلاً: فیزیک، شیمی، ریاضی، زیست، ادبیات، عربی، دینی)",
  "topic": "فصل یا موضوع اصلی",
  "subtopic": "زیرموضوع",
  "difficulty": "easy یا medium یا hard",
  "year": null
}

قوانین:
- اگر پاسخ صحیح مشخص نیست، correct_answer را null بگذار
- اگر سال مشخص است، آن را وارد کن
- options باید دقیقاً ۴ عنصر داشته باشد
- اگر تصویر سوال ندارد، آرایه خالی [] برگردان

فقط یک آرایه JSON خروجی بده. هیچ توضیح اضافه‌ای نده."""


def _call_claude_vision(client: anthropic.Anthropic, image_b64: str, media_type: str) -> list[dict]:
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )
    text = response.content[0].text.strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    raw = match.group() if match else text
    return json.loads(raw)


def extract_from_image_bytes(
    client: anthropic.Anthropic,
    image_bytes: bytes,
    media_type: str,
    source_name: str = "",
) -> list[dict]:
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    questions = _call_claude_vision(client, b64, media_type)
    for q in questions:
        q["source_file"] = source_name
    return questions


def extract_from_pdf_bytes(
    client: anthropic.Anthropic,
    pdf_bytes: bytes,
    source_name: str = "",
    progress_callback=None,
) -> list[dict]:
    import fitz  # PyMuPDF — imported lazily so the module loads without it

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    all_questions: list[dict] = []

    for page_num in range(total_pages):
        if progress_callback:
            progress_callback(page_num, total_pages)

        page = doc.load_page(page_num)
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

        try:
            questions = _call_claude_vision(client, b64, "image/png")
            for q in questions:
                q["source_file"] = f"{source_name} | صفحه {page_num + 1}"
            all_questions.extend(questions)
        except Exception as e:
            print(f"[extractor] خطا در صفحه {page_num + 1}: {e}")

    if progress_callback:
        progress_callback(total_pages, total_pages)

    doc.close()
    return all_questions
