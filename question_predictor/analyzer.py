import anthropic
import json
import re
from collections import Counter


def analyze_patterns(client: anthropic.Anthropic, questions: list[dict]) -> dict:
    subjects = Counter(q.get("subject") or "نامشخص" for q in questions)
    topics = Counter(q.get("topic") or "نامشخص" for q in questions)
    difficulties = Counter(q.get("difficulty") or "نامشخص" for q in questions)
    years = Counter(q.get("year") for q in questions if q.get("year"))

    stats = {
        "total": len(questions),
        "subjects": dict(subjects.most_common(20)),
        "topics": dict(topics.most_common(30)),
        "difficulties": dict(difficulties),
        "years": dict(sorted(years.items())),
    }

    sample = questions[:60] if len(questions) > 60 else questions
    sample_texts = [
        {"text": q.get("text", "")[:120], "subject": q.get("subject", ""), "topic": q.get("topic", ""), "difficulty": q.get("difficulty", "")}
        for q in sample
    ]

    prompt = f"""تو یک متخصص تحلیل سوالات کنکور ایران هستی. بر اساس داده‌های زیر، الگوهای طراح سوال را شناسایی کن.

آمار کلی:
{json.dumps(stats, ensure_ascii=False, indent=2)}

نمونه سوالات:
{json.dumps(sample_texts, ensure_ascii=False, indent=2)}

یک تحلیل جامع بده با این ساختار JSON:
{{
  "key_patterns": ["الگوی مهم ۱", "الگوی مهم ۲", "..."],
  "hot_topics": ["موضوع داغ ۱", "موضوع داغ ۲", "..."],
  "designer_mindset": "توضیح ذهنیت و رویکرد طراح سوال",
  "difficulty_pattern": "توضیح توزیع و الگوی سختی سوالات",
  "question_types": "تحلیل انواع سوالات (مفهومی/محاسباتی/حفظی)",
  "trend_analysis": "روند تغییرات در طول زمان (اگر داده سال وجود دارد)",
  "weak_spots": ["موضوعاتی که کم آمده اما مهم هستند"],
  "study_recommendations": ["توصیه مطالعاتی ۱", "توصیه ۲", "..."],
  "prediction_basis": "چه منطقی پایه پیش‌بینی سوالات بعدی است",
  "stats_summary": {{"subjects": {{}}, "topics": {{}}, "difficulties": {{}}}}
}}

فقط JSON خروجی بده."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(match.group() if match else text)
    result["stats_summary"] = stats
    return result
