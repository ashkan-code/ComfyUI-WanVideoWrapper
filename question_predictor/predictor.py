import anthropic
import json
import re


def predict_questions(
    client: anthropic.Anthropic,
    questions: list[dict],
    analysis: dict,
    count: int = 10,
) -> tuple[list[dict], str]:
    recent = questions[-100:] if len(questions) > 100 else questions
    recent_sample = [
        {"text": q.get("text", "")[:150], "subject": q.get("subject", ""), "topic": q.get("topic", "")}
        for q in recent
    ]

    prompt = f"""تو یک متخصص پیش‌بینی سوالات کنکور ایران هستی. بر اساس الگوهای شناسایی‌شده، سوالات آزمون بعدی را پیش‌بینی کن.

تحلیل الگوها:
{json.dumps(analysis, ensure_ascii=False, indent=2)}

نمونه آخرین سوالات:
{json.dumps(recent_sample, ensure_ascii=False, indent=2)}

دقیقاً {count} سوال تستی طراحی کن که:
- با سبک و فرمت واقعی کنکور ایران باشد
- بر اساس الگوهای شناسایی‌شده باشد
- دارای ۴ گزینه و پاسخ صحیح باشد
- توضیح دلیل پیش‌بینی داشته باشد

خروجی JSON:
{{
  "questions": [
    {{
      "text": "متن کامل سوال",
      "options": ["الف) ...", "ب) ...", "ج) ...", "د) ..."],
      "correct_answer": 0,
      "subject": "درس",
      "topic": "موضوع",
      "difficulty": "easy/medium/hard",
      "explanation": "توضیح پاسخ صحیح",
      "why_predicted": "دلیل اینکه این سوال محتمل است"
    }}
  ],
  "overall_reasoning": "توضیح کلی منطق پیش‌بینی و ذهن طراح"
}}

فقط JSON خروجی بده."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(match.group() if match else text)
    return result.get("questions", []), result.get("overall_reasoning", "")


def generate_practice_question(
    client: anthropic.Anthropic,
    subject: str,
    topic: str,
    difficulty: str = "medium",
) -> dict:
    prompt = f"""یک سوال تستی چهارگزینه‌ای از درس {subject} در مورد موضوع "{topic}" با سطح سختی {difficulty} طراحی کن.

خروجی JSON:
{{
  "text": "متن سوال",
  "options": ["الف) ...", "ب) ...", "ج) ...", "د) ..."],
  "correct_answer": 0,
  "subject": "{subject}",
  "topic": "{topic}",
  "difficulty": "{difficulty}",
  "explanation": "توضیح کامل پاسخ صحیح"
}}

فقط JSON خروجی بده."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group() if match else text)
