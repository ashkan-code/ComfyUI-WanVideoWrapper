"""ساخت آزمون شبیه‌ساز دکتری سازه بر اساس الگوهای پیش‌بینی‌شده"""

import anthropic
import json
import re

# ساختار استاندارد آزمون دکتری سازه
EXAM_STRUCTURE = {
    "مکانیک جامدات":  {"count": 10, "weight": "high"},
    "مقاومت مصالح":   {"count": 10, "weight": "high"},
    "تحلیل سازه":     {"count": 12, "weight": "high"},
    "دینامیک سازه":   {"count": 10, "weight": "high"},
    "طراحی بتن":      {"count":  7, "weight": "medium"},
    "طراحی فولاد":    {"count":  5, "weight": "medium"},
    "خاک و پی":       {"count":  4, "weight": "medium"},
    "ریاضی مهندسی":   {"count":  2, "weight": "low"},
}
TOTAL_QUESTIONS = sum(v["count"] for v in EXAM_STRUCTURE.values())  # 60


def build_mock_exam(
    client: anthropic.Anthropic,
    topic_probs: dict,
    analysis: dict,
    existing_questions: list[dict],
    target_year: int = None,
) -> tuple[list[dict], str]:
    """
    یک آزمون ۶۰ سوالی شبیه دکتری سازه می‌سازد.
    سوالات از موضوعات با احتمال بالا انتخاب می‌شوند.
    """

    # برترین موضوعات بر اساس احتمال
    top_by_subject: dict[str, list] = {}
    for topic, data in sorted(topic_probs.items(), key=lambda x: -x[1]["probability"]):
        subj = data["subject"]
        if subj not in top_by_subject:
            top_by_subject[subj] = []
        top_by_subject[subj].append({
            "topic": topic,
            "probability": data["probability"],
            "gap_years": data["gap_years"],
        })

    # خلاصه پیش‌بینی برای Claude
    prediction_ctx = analysis.get("next_exam_prediction", {})
    certain_topics  = prediction_ctx.get("certain", [])[:5]
    likely_topics   = prediction_ctx.get("likely", [])[:8]

    prompt = f"""تو طراح آزمون دکتری رشته سازه هستی. یک آزمون شبیه‌ساز کامل ۶۰ سوالی بساز.

ساختار آزمون:
{json.dumps(EXAM_STRUCTURE, ensure_ascii=False, indent=2)}

موضوعات پیش‌بینی‌شده (قطعی): {certain_topics}
موضوعات پیش‌بینی‌شده (محتمل): {likely_topics}

برترین موضوعات هر درس:
{json.dumps(top_by_subject, ensure_ascii=False, indent=2)}

قوانین:
- هر سوال باید دقیقاً ۴ گزینه داشته باشد
- سوالات باید سطح دکتری باشند (محاسباتی و تحلیلی)
- از موضوعات با احتمال بالا بیشتر استفاده کن
- توزیع سختی: ۲۰٪ آسان، ۵۵٪ متوسط، ۲۵٪ سخت
- برای هر سوال دلیل پیش‌بینی بنویس

خروجی JSON:
{{
  "questions": [
    {{
      "number": 1,
      "text": "متن کامل سوال",
      "options": ["الف) ...", "ب) ...", "ج) ...", "د) ..."],
      "correct_answer": 0,
      "subject": "نام درس",
      "topic": "موضوع",
      "subtopic": "زیرموضوع",
      "difficulty": "easy/medium/hard",
      "explanation": "توضیح کامل حل سوال",
      "why_predicted": "دلیل پیش‌بینی این سوال برای آزمون بعدی",
      "probability_score": 85
    }}
  ],
  "exam_summary": {{
    "total": 60,
    "by_subject": {{}},
    "predicted_year": {target_year or "نامشخص"},
    "confidence": "درصد اطمینان کلی"
  }},
  "overall_reasoning": "توضیح کلی استراتژی طراحی این آزمون"
}}

فقط JSON خروجی بده."""

    resp = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group() if m else text)
    return result.get("questions", []), result.get("overall_reasoning", "")


def generate_topic_question(
    client: anthropic.Anthropic,
    subject: str,
    topic: str,
    difficulty: str = "medium",
    context: str = "",
) -> dict:
    """یک سوال تمرینی برای موضوع مشخص می‌سازد"""

    prompt = f"""یک سوال تستی چهارگزینه‌ای سطح دکتری از درس {subject}، موضوع «{topic}» با سختی {difficulty} طراحی کن.
{f"زمینه: {context}" if context else ""}

خروجی JSON:
{{
  "text": "متن سوال با فرمول‌های لازم",
  "options": ["الف) ...", "ب) ...", "ج) ...", "د) ..."],
  "correct_answer": 0,
  "subject": "{subject}",
  "topic": "{topic}",
  "difficulty": "{difficulty}",
  "explanation": "حل کامل و مرحله‌به‌مرحله"
}}

فقط JSON خروجی بده."""

    resp = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group() if m else text)
