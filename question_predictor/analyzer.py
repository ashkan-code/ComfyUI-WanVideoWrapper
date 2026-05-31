"""موتور تحلیل الگو و محاسبه احتمال موضوعات — دکتری سازه"""

import anthropic
import json
import re
import math
from collections import defaultdict


# ─── محاسبه احتمال آماری ──────────────────────────────────────────────────────

def compute_topic_probabilities(matrix: dict, all_years: list[int]) -> dict[str, dict]:
    """
    برای هر موضوع یک امتیاز احتمال محاسبه می‌کند:
      base_freq  = تعداد کل / تعداد سال‌ها
      recency    = وزن‌دهی نمایی به سال‌های اخیر
      gap_bonus  = هر سالی که نیامده +۱۵٪ احتمال
      trend      = روند صعودی/نزولی
    """
    if not all_years:
        return {}

    max_year = max(all_years)
    n_years  = len(all_years)
    results  = {}

    for topic, info in matrix.items():
        year_counts = info["years"]
        subject     = info.get("subject", "")

        # تعداد کل و سال‌های حضور
        total_count   = sum(year_counts.values())
        years_present = sorted(year_counts.keys())
        n_present     = len(years_present)

        # فراوانی پایه
        base_freq = n_present / n_years

        # وزن‌دهی نمایی به سال‌های اخیر (سال‌های جدیدتر وزن بیشتر)
        recency_score = 0.0
        for y, cnt in year_counts.items():
            age = max_year - y            # 0 = امسال، 1 = پارسال
            weight = math.exp(-0.3 * age) # نمایی با نرخ افت ۰.۳
            recency_score += weight * cnt
        recency_norm = recency_score / max(total_count, 1)

        # گپ: چند سال است نیامده؟
        last_seen = max(year_counts.keys()) if year_counts else 0
        gap_years = max_year - last_seen
        gap_bonus = min(gap_years * 0.12, 0.40)  # حداکثر ۴۰٪ بونوس

        # روند: مقایسه نیمه اول و دوم سال‌ها
        half = n_years // 2
        early_years = set(all_years[:half])
        late_years  = set(all_years[half:])
        early_cnt = sum(c for y, c in year_counts.items() if y in early_years)
        late_cnt  = sum(c for y, c in year_counts.items() if y in late_years)
        if early_cnt + late_cnt > 0:
            trend = (late_cnt - early_cnt) / (early_cnt + late_cnt)
        else:
            trend = 0.0

        # امتیاز نهایی (0–1 نرمال‌شده بعداً)
        score = (
            base_freq * 0.35
            + recency_norm * 0.35
            + gap_bonus * 0.20
            + max(trend, 0) * 0.10
        )

        results[topic] = {
            "subject":       subject,
            "score":         round(score, 4),
            "base_freq":     round(base_freq, 3),
            "recency":       round(recency_norm, 3),
            "gap_years":     gap_years,
            "gap_bonus":     round(gap_bonus, 3),
            "trend":         round(trend, 3),
            "total_count":   total_count,
            "years_present": years_present,
            "year_counts":   year_counts,
        }

    # نرمال‌سازی score به 0–100 (درصد احتمال)
    max_score = max((v["score"] for v in results.values()), default=1) or 1
    for t in results:
        results[t]["probability"] = round(results[t]["score"] / max_score * 100, 1)

    return results


# ─── تحلیل عمیق با Claude ──────────────────────────────────────────────────────

def deep_analysis(client: anthropic.Anthropic, questions: list[dict], topic_probs: dict) -> dict:
    """تحلیل عمیق الگوها با Claude — ذهن طراح آزمون دکتری سازه"""

    all_years = sorted({q.get("year") for q in questions if q.get("year")})
    year_summary: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    for q in questions:
        y = q.get("year")
        s = q.get("subject") or "نامشخص"
        t = q.get("topic") or "نامشخص"
        if y:
            year_summary[y][s] += 1

    top_topics = sorted(topic_probs.items(), key=lambda x: -x[1]["probability"])[:20]
    top_topics_summary = [
        {"topic": t, "probability": d["probability"], "gap_years": d["gap_years"],
         "trend": d["trend"], "subject": d["subject"]}
        for t, d in top_topics
    ]

    prompt = f"""تو یک متخصص آزمون دکتری رشته سازه (مهندسی عمران) در ایران هستی.

سال‌های موجود: {all_years}
توزیع سوالات هر سال: {dict(dict(year_summary))}
برترین موضوعات از نظر احتمال:
{json.dumps(top_topics_summary, ensure_ascii=False, indent=2)}

با توجه به الگوهای ۱۰ سال گذشته:
۱. ذهن طراح آزمون دکتری سازه چگونه کار می‌کند؟
۲. کدام موضوعات هرگز حذف نمی‌شوند؟
۳. کدام موضوعات چرخه ۲-۳ ساله دارند؟
۴. چه تغییراتی در رویکرد طراحی سوال طی این سال‌ها بوده؟
۵. کدام موضوعات برای آزمون بعدی قطعی، محتمل، یا کم‌احتمال هستند؟

خروجی JSON:
{{
  "designer_mindset": "تحلیل ذهن طراح",
  "fixed_topics":     ["موضوعات همیشگی"],
  "cyclic_topics":    [{{"topic": "نام", "cycle_years": 2, "last_seen": 2022}}],
  "rising_topics":    ["موضوعات در حال رشد"],
  "declining_topics": ["موضوعات در حال افول"],
  "next_exam_prediction": {{
    "certain":    ["قطعی ۹۰٪+"],
    "likely":     ["محتمل ۶۰–۹۰٪"],
    "possible":   ["ممکن ۳۰–۶۰٪"],
    "unlikely":   ["کم‌احتمال"]
  }},
  "key_insights": ["بینش مهم ۱", "بینش ۲"],
  "study_priority": ["اولویت ۱", "اولویت ۲"]
}}

فقط JSON خروجی بده."""

    resp = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group() if m else text)
