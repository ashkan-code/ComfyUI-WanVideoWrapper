"""
سیستم پیش‌بینی آزمون دکتری سازه
تحلیل ۱۰ دوره گذشته → پیش‌بینی سوالات آزمون بعدی
"""

import time, os, json, random
import anthropic
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import database as db
import extractor
import analyzer as anal
import predictor as pred

# ─── تنظیمات ───────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="پیش‌بین دکتری سازه",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700&display=swap');
*, html, body, [class*="css"] { font-family: 'Vazirmatn', sans-serif !important; direction: rtl; }
.stButton>button { width:100%; border-radius:8px; font-family:'Vazirmatn',sans-serif !important; }
.prob-badge {
    display:inline-block; padding:4px 12px; border-radius:20px;
    font-weight:700; font-size:14px; margin:2px;
}
.prob-high   { background:#d4edda; color:#155724; }
.prob-med    { background:#fff3cd; color:#856404; }
.prob-low    { background:#f8d7da; color:#721c24; }
.gap-badge   { background:#cce5ff; color:#004085; }
.card {
    background:#f8f9fa; border-right:4px solid #0066cc;
    border-radius:8px; padding:16px; margin:8px 0;
}
.exam-header {
    background:linear-gradient(135deg,#0066cc,#004499);
    color:white; border-radius:12px; padding:20px; text-align:center; margin:10px 0;
}
.correct-opt { color:#155724; font-weight:700; }
.wrong-opt   { color:#721c24; text-decoration:line-through; }
</style>
""", unsafe_allow_html=True)

db.init_db()

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏗️ پیش‌بین دکتری سازه")
    st.markdown("---")

    api_key = st.text_input(
        "کلید API آنتروپیک",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    st.markdown("---")
    page = st.radio(
        "بخش",
        [
            "📥 آپلود دفترچه‌ها",
            "📊 ماتریس سال × موضوع",
            "🔢 امتیاز احتمال",
            "🔮 شبیه‌ساز کنکور",
            "🏋️ تمرین هوشمند",
        ],
        label_visibility="collapsed",
    )

    st.markdown("---")
    years = db.get_years()
    q_count = db.get_question_count()
    st.metric("دوره‌های بارگذاری‌شده", len(years))
    st.metric("کل سوالات", f"{q_count:,}")
    if years:
        st.caption(f"سال‌ها: {min(years)}–{max(years)}")

    if st.button("🗑️ پاک کردن همه", type="secondary"):
        if st.session_state.get("confirm_del"):
            db.clear_all()
            st.success("پاک شد")
            st.session_state.confirm_del = False
            st.rerun()
        else:
            st.session_state.confirm_del = True
            st.warning("دوباره کلیک کن")


def get_client():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        st.error("کلید API آنتروپیک را در sidebar وارد کنید.")
        return None
    return anthropic.Anthropic(api_key=key)


# ══════════════════════════════════════════════════════════════════════════════
# ۱. آپلود دفترچه‌ها
# ══════════════════════════════════════════════════════════════════════════════
if page == "📥 آپلود دفترچه‌ها":
    st.title("📥 آپلود دفترچه‌های آزمون دکتری سازه")
    st.markdown("برای هر دوره، فایل PDF دفترچه را آپلود و سال آزمون را مشخص کنید.")

    col1, col2 = st.columns([3, 1])
    with col1:
        uploaded_files = st.file_uploader(
            "دفترچه‌های آزمون (PDF یا تصویر)",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
        )
    with col2:
        st.markdown("### ساختار آزمون")
        for subj, info in pred.EXAM_STRUCTURE.items():
            st.caption(f"• {subj}: {info['count']} سوال")

    if uploaded_files:
        st.markdown("### برچسب‌گذاری سال برای هر فایل")
        year_map: dict[str, int] = {}
        cols = st.columns(min(len(uploaded_files), 3))
        for i, f in enumerate(uploaded_files):
            with cols[i % 3]:
                y = st.number_input(
                    f.name[:30],
                    min_value=1390, max_value=1410,
                    value=1400 + i,
                    step=1,
                    key=f"year_{f.name}",
                )
                year_map[f.name] = int(y)

        if st.button("🚀 شروع استخراج و تحلیل", type="primary"):
            client = get_client()
            if client:
                total_new = []
                prog = st.progress(0)
                status = st.empty()

                for fi, f in enumerate(uploaded_files):
                    year = year_map[f.name]
                    status.info(f"📖 پردازش دوره **{year}** — {f.name}")
                    raw = f.read()

                    try:
                        if f.name.lower().endswith(".pdf"):
                            p_prog = st.progress(0)
                            p_txt  = st.empty()

                            def cb(cur, tot, _pp=p_prog, _pt=p_txt, _y=year):
                                _pp.progress(cur / max(tot, 1))
                                _pt.caption(f"صفحه {cur}/{tot} — دوره {_y}")

                            qs = extractor.extract_from_pdf(client, raw, f.name, year, cb)
                            p_prog.empty(); p_txt.empty()
                        else:
                            ext = f.name.rsplit(".", 1)[-1].lower()
                            mt = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext, "image/jpeg")
                            qs = extractor.extract_from_image(client, raw, mt, f.name, year)

                        db.add_questions(qs)
                        total_new.extend(qs)
                        st.success(f"✅ دوره {year}: {len(qs)} سوال استخراج شد")

                    except Exception as e:
                        st.error(f"❌ خطا در {f.name}: {e}")

                    prog.progress((fi + 1) / len(uploaded_files))

                db.rebuild_topic_matrix()
                status.success(f"🎉 **{len(total_new)}** سوال از {len(uploaded_files)} دوره ذخیره شد!")
                st.balloons()
                st.rerun()

    # وضعیت فعلی
    if db.get_question_count() > 0:
        st.markdown("---")
        st.subheader("📈 وضعیت بانک")
        years_loaded = db.get_years()
        qs = db.get_all_questions()
        year_counts = {}
        for q in qs:
            y = q.get("year") or "نامشخص"
            year_counts[y] = year_counts.get(y, 0) + 1
        df = pd.DataFrame(list(year_counts.items()), columns=["سال", "تعداد"]).sort_values("سال")
        fig = px.bar(df, x="سال", y="تعداد", title="تعداد سوالات هر دوره",
                     color="تعداد", color_continuous_scale="blues")
        fig.update_layout(font_family="Vazirmatn")
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# ۲. ماتریس سال × موضوع
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📊 ماتریس سال × موضوع":
    st.title("📊 ماتریس پوشش موضوعی — سال‌به‌سال")

    matrix = db.get_topic_year_matrix()
    years = sorted(db.get_years())

    if not matrix or not years:
        st.info("ابتدا دفترچه‌های آزمون را آپلود کنید.")
        st.stop()

    # ساخت DataFrame برای heatmap
    topics_list = sorted(matrix.keys())
    data = []
    for topic in topics_list:
        row = {"موضوع": topic, "درس": matrix[topic].get("subject", "")}
        for y in years:
            row[str(y)] = matrix[topic]["years"].get(y, 0)
        data.append(row)

    df = pd.DataFrame(data)

    # فیلتر درس
    subjects = sorted(df["درس"].unique())
    sel_subj = st.selectbox("فیلتر بر اساس درس", ["همه"] + subjects)
    if sel_subj != "همه":
        df_filtered = df[df["درس"] == sel_subj]
    else:
        df_filtered = df

    # Heatmap
    year_cols = [str(y) for y in years]
    heat_data = df_filtered[year_cols].values.tolist()
    y_labels  = df_filtered["موضوع"].tolist()

    fig_heat = go.Figure(data=go.Heatmap(
        z=heat_data,
        x=year_cols,
        y=y_labels,
        colorscale="Blues",
        text=[[str(v) if v > 0 else "" for v in row] for row in heat_data],
        texttemplate="%{text}",
        hovertemplate="موضوع: %{y}<br>سال: %{x}<br>تعداد: %{z}<extra></extra>",
    ))
    fig_heat.update_layout(
        title="تعداد سوالات هر موضوع در هر سال (آبی = بیشتر)",
        font_family="Vazirmatn",
        height=max(400, len(y_labels) * 22),
        yaxis={"tickfont": {"size": 11}},
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown("---")

    # تحلیل گپ — موضوعاتی که مدت‌هاست نیامده
    st.subheader("⚠️ تحلیل شکاف (Gap Analysis)")
    max_year = max(years)
    gap_data = []
    for topic, info in matrix.items():
        last = max(info["years"].keys()) if info["years"] else 0
        gap = max_year - last
        if gap >= 2:
            gap_data.append({
                "موضوع": topic,
                "درس": info.get("subject", ""),
                "آخرین حضور": last,
                "سال‌های غیبت": gap,
                "کل سوالات": sum(info["years"].values()),
            })

    if gap_data:
        gap_df = pd.DataFrame(gap_data).sort_values("سال‌های غیبت", ascending=False)
        st.markdown("موضوعاتی که ۲+ سال غایب بوده‌اند — **احتمال بالای برگشت:**")
        st.dataframe(gap_df, use_container_width=True, hide_index=True)

        fig_gap = px.bar(
            gap_df.head(15), x="موضوع", y="سال‌های غیبت",
            color="درس", title="موضوعات با بیشترین غیبت",
        )
        fig_gap.update_layout(font_family="Vazirmatn")
        st.plotly_chart(fig_gap, use_container_width=True)
    else:
        st.info("همه موضوعات در سال‌های اخیر پوشش داده شده‌اند.")

    # جدول DataFrame کامل
    with st.expander("🗂️ جدول کامل ماتریس"):
        st.dataframe(df_filtered, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ۳. امتیاز احتمال
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔢 امتیاز احتمال":
    st.title("🔢 امتیاز احتمال موضوعات — آزمون بعدی")

    matrix = db.get_topic_year_matrix()
    years  = db.get_years()

    if not matrix or not years:
        st.info("ابتدا دفترچه‌ها را آپلود کنید.")
        st.stop()

    # محاسبه احتمال آماری
    topic_probs = anal.compute_topic_probabilities(matrix, years)

    col_a, col_b = st.columns([3, 1])
    with col_b:
        run_ai = st.button("🤖 تحلیل عمیق با AI", type="primary",
                           help="Claude الگوهای پنهان را تحلیل می‌کند")
    with col_a:
        st.markdown(f"**{len(topic_probs)}** موضوع | **{len(years)}** دوره تحلیل‌شده")

    ai_analysis = db.get_latest_analysis("deep")

    if run_ai:
        client = get_client()
        if client:
            qs = db.get_all_questions()
            with st.spinner("در حال تحلیل ذهن طراح آزمون..."):
                ai_analysis = anal.deep_analysis(client, qs, topic_probs)
                db.save_analysis("deep", ai_analysis)
            db.save_analysis("topic_probs", topic_probs)
            st.success("تحلیل انجام شد!")
            st.rerun()

    # ذخیره topic_probs
    db.save_analysis("topic_probs", topic_probs)

    # نمودار احتمال
    df_prob = pd.DataFrame([
        {
            "موضوع": t,
            "درس": d["subject"],
            "احتمال (%)": d["probability"],
            "غیبت (سال)": d["gap_years"],
            "روند": "صعودی↑" if d["trend"] > 0.1 else ("نزولی↓" if d["trend"] < -0.1 else "ثابت→"),
            "آخرین حضور": max(d["years_present"]) if d["years_present"] else "—",
        }
        for t, d in topic_probs.items()
    ]).sort_values("احتمال (%)", ascending=False)

    # Top 20
    top20 = df_prob.head(20)
    fig_prob = px.bar(
        top20, x="احتمال (%)", y="موضوع", orientation="h",
        color="احتمال (%)", color_continuous_scale="RdYlGn",
        hover_data=["درس", "غیبت (سال)", "روند"],
        title="۲۰ موضوع با بالاترین احتمال در آزمون بعدی",
    )
    fig_prob.update_layout(font_family="Vazirmatn", height=500)
    st.plotly_chart(fig_prob, use_container_width=True)

    # دسته‌بندی بر اساس احتمال
    high  = df_prob[df_prob["احتمال (%)"] >= 70]
    med   = df_prob[(df_prob["احتمال (%)"] >= 40) & (df_prob["احتمال (%)"] < 70)]
    low   = df_prob[df_prob["احتمال (%)"] < 40]

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🔴 قطعی — بالای ۷۰٪")
        for _, r in high.iterrows():
            st.markdown(
                f"<span class='prob-badge prob-high'>%{r['احتمال (%)']}</span> **{r['موضوع']}** — {r['درس']}",
                unsafe_allow_html=True,
            )
    with c2:
        st.markdown("### 🟡 محتمل — ۴۰–۷۰٪")
        for _, r in med.iterrows():
            st.markdown(
                f"<span class='prob-badge prob-med'>%{r['احتمال (%)']}</span> {r['موضوع']} — {r['درس']}",
                unsafe_allow_html=True,
            )
    with c3:
        st.markdown("### ⚠️ موضوعات غایب (Gap)")
        gap_df = df_prob[df_prob["غیبت (سال)"] >= 2].sort_values("غیبت (سال)", ascending=False)
        for _, r in gap_df.head(10).iterrows():
            st.markdown(
                f"<span class='prob-badge gap-badge'>{r['غیبت (سال)']} سال غیبت</span> {r['موضوع']}",
                unsafe_allow_html=True,
            )

    # تحلیل AI
    if ai_analysis:
        st.markdown("---")
        st.subheader("🧠 تحلیل ذهن طراح آزمون (AI)")
        st.info(ai_analysis.get("designer_mindset", ""))

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**📌 موضوعات ثابت (همیشه می‌آیند)**")
            for t in ai_analysis.get("fixed_topics", []):
                st.markdown(f"- ✅ {t}")

            st.markdown("**📈 موضوعات در حال رشد**")
            for t in ai_analysis.get("rising_topics", []):
                st.markdown(f"- 🔼 {t}")

        with col2:
            st.markdown("**🔄 موضوعات چرخه‌ای**")
            for ct in ai_analysis.get("cyclic_topics", []):
                if isinstance(ct, dict):
                    st.markdown(f"- {ct.get('topic','')} — هر {ct.get('cycle_years',2)} سال (آخرین: {ct.get('last_seen','')})")
                else:
                    st.markdown(f"- {ct}")

            st.markdown("**📚 اولویت مطالعه**")
            for p in ai_analysis.get("study_priority", []):
                st.markdown(f"- 📖 {p}")

        # پیش‌بینی نهایی
        nep = ai_analysis.get("next_exam_prediction", {})
        if nep:
            st.markdown("---")
            st.subheader("🎯 پیش‌بینی آزمون بعدی")
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**قطعی ۹۰٪+**")
                for t in nep.get("certain", []):
                    st.markdown(f"<span class='prob-badge prob-high'>{t}</span>", unsafe_allow_html=True)
            with c2:
                st.markdown("**محتمل ۶۰–۹۰٪**")
                for t in nep.get("likely", []):
                    st.markdown(f"<span class='prob-badge prob-med'>{t}</span>", unsafe_allow_html=True)
            with c3:
                st.markdown("**ممکن ۳۰–۶۰٪**")
                for t in nep.get("possible", []):
                    st.markdown(f"<span class='prob-badge prob-low'>{t}</span>", unsafe_allow_html=True)

    # جدول کامل
    with st.expander("🗂️ جدول کامل احتمالات"):
        st.dataframe(df_prob, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# ۴. شبیه‌ساز کنکور
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔮 شبیه‌ساز کنکور":
    st.title("🔮 شبیه‌ساز آزمون دکتری سازه")
    st.markdown("یک آزمون ۶۰ سوالی کامل بر اساس الگوهای ۱۰ دوره گذشته — مثل آزمون واقعی")

    topic_probs_raw = db.get_latest_analysis("topic_probs") or {}
    ai_analysis     = db.get_latest_analysis("deep") or {}
    questions_db    = db.get_all_questions()

    if not topic_probs_raw:
        st.warning("ابتدا در بخش «امتیاز احتمال» تحلیل را اجرا کنید.")
        st.stop()

    col1, col2, col3 = st.columns(3)
    with col1:
        target_year = st.number_input("سال هدف آزمون", 1400, 1415, max(db.get_years(), default=1403) + 1)
    with col2:
        num_q = st.selectbox("تعداد سوالات", [30, 45, 60], index=2)
    with col3:
        build_btn = st.button("🔮 ساخت آزمون شبیه‌ساز", type="primary")

    if build_btn:
        client = get_client()
        if client:
            with st.spinner("در حال طراحی آزمون شبیه‌ساز — لطفاً صبر کنید..."):
                mock_qs, reasoning = pred.build_mock_exam(
                    client, topic_probs_raw, ai_analysis, questions_db, target_year
                )
                db.save_prediction(mock_qs, reasoning, topic_probs_raw)
            st.success(f"✅ آزمون شبیه‌ساز با {len(mock_qs)} سوال آماده شد!")
            st.rerun()

    # نمایش آزمون
    pred_qs, reasoning, _ = db.get_latest_prediction()

    if pred_qs:
        st.markdown(f"""
<div class='exam-header'>
<h2>آزمون دکتری سازه — شبیه‌ساز</h2>
<p>بر اساس تحلیل {len(db.get_years())} دوره گذشته | {len(pred_qs)} سوال</p>
</div>
""", unsafe_allow_html=True)

        if reasoning:
            with st.expander("🧠 منطق طراحی این آزمون"):
                st.write(reasoning)

        # نمودار توزیع
        subj_dist = {}
        for q in pred_qs:
            s = q.get("subject", "نامشخص")
            subj_dist[s] = subj_dist.get(s, 0) + 1
        df_dist = pd.DataFrame(list(subj_dist.items()), columns=["درس", "تعداد"])
        fig_dist = px.pie(df_dist, names="درس", values="تعداد", title="توزیع سوالات")
        fig_dist.update_layout(font_family="Vazirmatn", height=300)
        st.plotly_chart(fig_dist, use_container_width=True)

        # نمایش سوالات
        diff_icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}
        labels = ["الف", "ب", "ج", "د"]

        # فیلتر درس
        subjects_in_exam = ["همه"] + sorted(set(q.get("subject", "") for q in pred_qs))
        sel_s = st.selectbox("فیلتر درس", subjects_in_exam)
        view_qs = pred_qs if sel_s == "همه" else [q for q in pred_qs if q.get("subject") == sel_s]

        show_answers = st.checkbox("نمایش پاسخ‌ها", value=False)

        for i, q in enumerate(view_qs):
            prob = q.get("probability_score", "—")
            prob_class = "prob-high" if isinstance(prob, (int,float)) and prob>=70 else "prob-med"
            with st.expander(
                f"سوال {i+1} | {q.get('subject','')} | {q.get('topic','')} {diff_icon.get(q.get('difficulty',''),'')}"
            ):
                st.markdown(f"**{q['text']}**")

                opts = q.get("options", [])
                correct = q.get("correct_answer", 0)
                for j, opt in enumerate(opts):
                    if show_answers:
                        if j == correct:
                            st.markdown(f"✅ **{labels[j]}) {opt}**")
                        else:
                            st.markdown(f"   {labels[j]}) {opt}")
                    else:
                        st.markdown(f"   {labels[j]}) {opt}")

                col_a, col_b = st.columns(2)
                with col_a:
                    if show_answers and q.get("explanation"):
                        st.info(f"💡 {q['explanation']}")
                with col_b:
                    if q.get("why_predicted"):
                        st.caption(f"🔮 دلیل پیش‌بینی: {q['why_predicted']}")

        # دانلود
        st.markdown("---")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.download_button(
                "📥 دانلود آزمون (JSON)",
                data=json.dumps(pred_qs, ensure_ascii=False, indent=2),
                file_name=f"mock_exam_phd_sazeh.json",
                mime="application/json",
            )
        with col_d2:
            # ساخت متن ساده
            txt = f"آزمون شبیه‌ساز دکتری سازه — {len(pred_qs)} سوال\n{'='*50}\n\n"
            for i, q in enumerate(pred_qs):
                txt += f"سوال {i+1}: {q['text']}\n"
                for j, opt in enumerate(q.get("options", [])):
                    txt += f"  {labels[j]}) {opt}\n"
                txt += "\n"
            txt += "\nپاسخ‌نامه:\n"
            for i, q in enumerate(pred_qs):
                ca = q.get("correct_answer")
                if ca is not None and ca < len(labels):
                    txt += f"س{i+1}: {labels[ca]}   "
            st.download_button(
                "📄 دانلود آزمون (متن)",
                data=txt,
                file_name=f"mock_exam_phd_sazeh.txt",
                mime="text/plain",
            )
    else:
        st.info("روی «ساخت آزمون شبیه‌ساز» کلیک کنید.")


# ══════════════════════════════════════════════════════════════════════════════
# ۵. تمرین هوشمند
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🏋️ تمرین هوشمند":
    st.title("🏋️ تمرین هوشمند")

    tab1, tab2, tab3 = st.tabs(["📝 تمرین از آزمون شبیه‌ساز", "🎯 تمرین موضوعی با AI", "📊 آمار من"])

    # ─── تب ۱: تمرین از آزمون شبیه‌ساز ──────────────────────────────────────
    with tab1:
        pred_qs, _, _ = db.get_latest_prediction()
        pool = [q for q in pred_qs if q.get("options") and q.get("correct_answer") is not None]

        if not pool:
            st.info("ابتدا در بخش «شبیه‌ساز کنکور» آزمون بسازید.")
        else:
            if "tp_pool" not in st.session_state or st.session_state.get("tp_reset"):
                shuffled = pool.copy()
                random.shuffle(shuffled)
                st.session_state.tp_pool     = shuffled
                st.session_state.tp_idx      = 0
                st.session_state.tp_answered = False
                st.session_state.tp_score    = {"c": 0, "w": 0}
                st.session_state.tp_reset    = False
                st.session_state.tp_start    = None

            pool_s = st.session_state.tp_pool
            idx    = st.session_state.tp_idx

            if idx < len(pool_s):
                q       = pool_s[idx]
                opts    = q.get("options", [])
                correct = q.get("correct_answer", 0)
                labels  = ["الف", "ب", "ج", "د"]
                score   = st.session_state.tp_score

                # نوار پیشرفت
                st.progress(idx / len(pool_s))
                col_i, col_j, col_k = st.columns(3)
                col_i.metric("سوال", f"{idx+1}/{len(pool_s)}")
                col_j.metric("✅ صحیح", score["c"])
                col_k.metric(
                    "درصد",
                    f"{round(score['c']/(score['c']+score['w'])*100)}%" if score['c']+score['w'] > 0 else "—"
                )

                diff_icon = {"easy": "🟢 آسان", "medium": "🟡 متوسط", "hard": "🔴 سخت"}
                st.caption(f"{q.get('subject','')} | {q.get('topic','')} | {diff_icon.get(q.get('difficulty',''),'')}")
                st.subheader(q["text"])

                if not st.session_state.tp_answered:
                    if not st.session_state.tp_start:
                        st.session_state.tp_start = time.time()

                    chosen = st.radio(
                        "پاسخ:",
                        range(len(opts)),
                        format_func=lambda j: f"{labels[j]}) {opts[j]}",
                        key=f"tp_ans_{idx}",
                    )
                    if st.button("✅ ثبت پاسخ", type="primary", key=f"tp_submit_{idx}"):
                        elapsed = time.time() - st.session_state.tp_start
                        is_c = chosen == correct
                        db.save_practice_result(idx, "mock_exam", chosen, is_c, elapsed)
                        if is_c:
                            st.session_state.tp_score["c"] += 1
                        else:
                            st.session_state.tp_score["w"] += 1
                        st.session_state.tp_answered = True
                        st.session_state.tp_start    = None
                        st.rerun()
                else:
                    for j, opt in enumerate(opts):
                        if j == correct:
                            st.success(f"✅ {labels[j]}) {opt}")
                        else:
                            st.write(f"   {labels[j]}) {opt}")

                    if q.get("explanation"):
                        with st.expander("💡 توضیح پاسخ"):
                            st.write(q["explanation"])
                    if q.get("why_predicted"):
                        st.caption(f"🔮 {q['why_predicted']}")

                    if st.button("سوال بعدی ➡️", type="primary", key=f"tp_next_{idx}"):
                        st.session_state.tp_idx += 1
                        st.session_state.tp_answered = False
                        st.rerun()

            else:
                score = st.session_state.tp_score
                total = score["c"] + score["w"]
                pct   = round(score["c"] / total * 100) if total else 0
                st.markdown(f"""
<div class='exam-header'>
<h2>🎉 آزمون تمام شد!</h2>
<h3>{score['c']}/{total} — {pct}%</h3>
<p>{'عالی! 🏆' if pct >= 80 else 'خوب بود! 💪' if pct >= 60 else 'بیشتر تمرین کن 📚'}</p>
</div>
""", unsafe_allow_html=True)
                if st.button("🔄 شروع مجدد"):
                    st.session_state.tp_reset = True
                    st.rerun()

    # ─── تب ۲: تمرین موضوعی با AI ────────────────────────────────────────────
    with tab2:
        st.markdown("سوال جدید برای هر موضوع توسط AI تولید کن.")

        col_s, col_t, col_d = st.columns(3)
        with col_s:
            subj_opts = list(pred.EXAM_STRUCTURE.keys())
            sel_subj = st.selectbox("درس", subj_opts, key="ai_subj")
        with col_t:
            topic_suggestions = db.get_topics(sel_subj) or ["—"]
            sel_topic = st.selectbox("موضوع", topic_suggestions, key="ai_topic")
        with col_d:
            sel_diff = st.selectbox("سختی", ["easy", "medium", "hard"], index=1, key="ai_diff")

        if st.button("🤖 تولید سوال", type="primary", key="ai_gen"):
            client = get_client()
            if client:
                with st.spinner("در حال ساخت سوال..."):
                    aq = pred.generate_topic_question(client, sel_subj, sel_topic, sel_diff)
                st.session_state.ai_q        = aq
                st.session_state.ai_answered = False
                st.session_state.ai_start    = time.time()
                st.rerun()

        if "ai_q" in st.session_state:
            aq      = st.session_state.ai_q
            opts    = aq.get("options", [])
            correct = aq.get("correct_answer", 0)
            labels  = ["الف", "ب", "ج", "د"]

            st.markdown("---")
            st.subheader(aq.get("text", ""))

            if not st.session_state.get("ai_answered"):
                ai_chosen = st.radio("پاسخ:", range(len(opts)),
                                     format_func=lambda j: f"{labels[j]}) {opts[j]}",
                                     key="ai_radio")
                if st.button("✅ ثبت", type="primary", key="ai_submit"):
                    elapsed = time.time() - st.session_state.get("ai_start", time.time())
                    is_c = ai_chosen == correct
                    db.save_practice_result(-1, "ai_generated", ai_chosen, is_c, elapsed)
                    st.session_state.ai_user_ans = ai_chosen
                    st.session_state.ai_answered = True
                    st.rerun()
            else:
                user_ans = st.session_state.get("ai_user_ans", 0)
                for j, opt in enumerate(opts):
                    if j == correct:
                        st.success(f"✅ {labels[j]}) {opt}")
                    elif j == user_ans:
                        st.error(f"❌ {labels[j]}) {opt} ← پاسخ شما")
                    else:
                        st.write(f"   {labels[j]}) {opt}")
                if aq.get("explanation"):
                    with st.expander("💡 توضیح حل"):
                        st.write(aq["explanation"])

    # ─── تب ۳: آمار ────────────────────────────────────────────────────────
    with tab3:
        stats = db.get_practice_stats()
        if stats["total"] == 0:
            st.info("هنوز سوالی حل نشده‌ای.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("کل حل‌شده", stats["total"])
            c2.metric("✅ صحیح", stats["correct"])
            c3.metric("❌ غلط", stats["wrong"])
            c4.metric("درصد موفقیت", f"{stats['accuracy']}%")

            fig_g = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=stats["accuracy"],
                delta={"reference": 60},
                domain={"x": [0, 1], "y": [0, 1]},
                title={"text": "درصد موفقیت"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#0066cc"},
                    "steps": [
                        {"range": [0, 50],  "color": "#f8d7da"},
                        {"range": [50, 75], "color": "#fff3cd"},
                        {"range": [75, 100],"color": "#d4edda"},
                    ],
                    "threshold": {"line": {"color": "red", "width": 4}, "thickness": 0.75, "value": 60},
                },
            ))
            fig_g.update_layout(font_family="Vazirmatn", height=300)
            st.plotly_chart(fig_g, use_container_width=True)

            weak = db.get_weak_topics()
            if weak:
                st.subheader("⚠️ موضوعات ضعیف شما")
                df_weak = pd.DataFrame(weak)
                df_weak["درصد موفقیت"] = df_weak["accuracy"].astype(str) + "%"
                st.dataframe(df_weak[["topic", "subject", "total", "correct", "درصد موفقیت"]],
                             use_container_width=True, hide_index=True)
                st.markdown("💡 این موضوعات را با بخش «تمرین موضوعی با AI» تقویت کن.")
