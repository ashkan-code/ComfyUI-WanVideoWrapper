"""سیستم پیش‌بینی سوالات کنکور — رابط اصلی Streamlit"""

import time
import os
import json
import anthropic
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import database as db
import extractor
import analyzer as anal
import predictor as pred

# ─── تنظیمات صفحه ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="پیش‌بین کنکور",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── استایل فارسی ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Vazirmatn', sans-serif !important;
        direction: rtl;
    }
    .stButton > button { width: 100%; border-radius: 8px; }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white; border-radius: 12px; padding: 20px;
        text-align: center; margin: 5px;
    }
    .question-card {
        background: #f8f9fa; border-right: 4px solid #667eea;
        border-radius: 8px; padding: 16px; margin: 10px 0;
    }
    .correct { border-right-color: #28a745 !important; background: #d4edda !important; }
    .wrong   { border-right-color: #dc3545 !important; background: #f8d7da !important; }
    .predicted-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 12px; padding: 20px; margin: 10px 0;
        border: 1px solid #dee2e6;
    }
</style>
""", unsafe_allow_html=True)

db.init_db()

# ─── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🎯 پیش‌بین کنکور")
    st.markdown("---")

    api_key = st.text_input(
        "کلید API آنتروپیک",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="کلید API خود را از anthropic.com دریافت کنید",
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    st.markdown("---")
    page = st.radio(
        "بخش",
        ["📤 آپلود سوالات", "📚 بانک سوالات", "📊 تحلیل الگو", "🔮 پیش‌بینی", "🏋️ تمرین"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    total = db.get_question_count()
    st.metric("تعداد سوالات", f"{total:,}")

    if st.button("🗑️ پاک کردن همه داده‌ها", type="secondary"):
        if st.session_state.get("confirm_clear"):
            db.clear_all()
            st.success("پاک شد!")
            st.session_state.confirm_clear = False
            st.rerun()
        else:
            st.session_state.confirm_clear = True
            st.warning("دوباره کلیک کن تا تأیید شود")


def get_client() -> anthropic.Anthropic | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        st.error("لطفاً کلید API آنتروپیک را در sidebar وارد کنید.")
        return None
    return anthropic.Anthropic(api_key=key)


# ═══════════════════════════════════════════════════════════════════════════════
# صفحه ۱ — آپلود سوالات
# ═══════════════════════════════════════════════════════════════════════════════
if page == "📤 آپلود سوالات":
    st.title("📤 آپلود و استخراج سوالات")
    st.markdown(
        "فایل‌های PDF یا تصویر (JPG/PNG) حاوی سوالات تستی را آپلود کنید. "
        "هوش مصنوعی سوالات را استخراج و دسته‌بندی می‌کند."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "فایل‌های سوال",
            type=["pdf", "jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="می‌توانید چند فایل به‌طور همزمان آپلود کنید",
        )

    with col2:
        st.markdown("### راهنما")
        st.markdown("""
- **PDF**: کتاب‌های سوال، دفترچه کنکور
- **JPG/PNG**: عکس از سوالات
- هر صفحه جداگانه پردازش می‌شود
- به کلید API نیاز دارد
        """)

    if uploaded:
        client = get_client()
        if client:
            if st.button("🚀 شروع استخراج سوالات", type="primary"):
                all_new: list[dict] = []
                progress = st.progress(0)
                status = st.empty()

                for i, f in enumerate(uploaded):
                    status.info(f"در حال پردازش: **{f.name}** ({i+1}/{len(uploaded)})")
                    raw = f.read()
                    fname = f.name

                    try:
                        if fname.lower().endswith(".pdf"):
                            page_prog = st.progress(0)
                            page_status = st.empty()

                            def pdf_cb(current, total, _ps=page_prog, _ss=page_status, _n=fname):
                                _ps.progress(current / max(total, 1))
                                _ss.caption(f"صفحه {current}/{total} از {_n}")

                            questions = extractor.extract_from_pdf_bytes(client, raw, fname, progress_callback=pdf_cb)
                            page_prog.empty()
                            page_status.empty()
                        else:
                            ext = fname.rsplit(".", 1)[-1].lower()
                            mt = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
                            questions = extractor.extract_from_image_bytes(client, raw, mt, fname)

                        all_new.extend(questions)
                        st.success(f"✅ {fname}: {len(questions)} سوال استخراج شد")
                    except Exception as e:
                        st.error(f"❌ خطا در {fname}: {e}")

                    progress.progress((i + 1) / len(uploaded))

                if all_new:
                    db.add_questions(all_new)
                    status.success(f"🎉 مجموعاً **{len(all_new)}** سوال با موفقیت ذخیره شد!")
                    st.balloons()
                    st.rerun()

    # نمایش آمار فعلی
    total_now = db.get_question_count()
    if total_now > 0:
        st.markdown("---")
        st.subheader("📈 وضعیت بانک سوالات")
        subjects = db.get_subjects()
        c1, c2, c3 = st.columns(3)
        c1.metric("کل سوالات", total_now)
        c2.metric("تعداد دروس", len(subjects))
        c3.metric("تعداد موضوعات", len(db.get_topics()))

        if subjects:
            questions = db.get_all_questions()
            subj_count = {}
            for q in questions:
                s = q.get("subject") or "نامشخص"
                subj_count[s] = subj_count.get(s, 0) + 1
            df = pd.DataFrame(list(subj_count.items()), columns=["درس", "تعداد"]).sort_values("تعداد", ascending=False)
            fig = px.bar(df, x="درس", y="تعداد", title="توزیع سوالات بر اساس درس", color="تعداد", color_continuous_scale="viridis")
            fig.update_layout(font_family="Vazirmatn")
            st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# صفحه ۲ — بانک سوالات
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📚 بانک سوالات":
    st.title("📚 بانک سوالات")

    questions = db.get_all_questions()
    if not questions:
        st.info("هنوز سوالی وارد نشده. ابتدا به بخش «آپلود سوالات» بروید.")
        st.stop()

    # فیلترها
    col1, col2, col3 = st.columns(3)
    with col1:
        subjects = ["همه"] + db.get_subjects()
        sel_subject = st.selectbox("فیلتر درس", subjects)
    with col2:
        topics = ["همه"] + db.get_topics(None if sel_subject == "همه" else sel_subject)
        sel_topic = st.selectbox("فیلتر موضوع", topics)
    with col3:
        difficulties = ["همه", "easy", "medium", "hard"]
        sel_diff = st.selectbox("سطح سختی", difficulties)

    filtered = questions
    if sel_subject != "همه":
        filtered = [q for q in filtered if q.get("subject") == sel_subject]
    if sel_topic != "همه":
        filtered = [q for q in filtered if q.get("topic") == sel_topic]
    if sel_diff != "همه":
        filtered = [q for q in filtered if q.get("difficulty") == sel_diff]

    st.markdown(f"**{len(filtered)}** سوال یافت شد")

    diff_label = {"easy": "آسان 🟢", "medium": "متوسط 🟡", "hard": "سخت 🔴"}

    for i, q in enumerate(filtered[:100]):
        with st.expander(f"سوال {i+1} — {q.get('subject','')} | {q.get('topic','')} | {diff_label.get(q.get('difficulty',''), q.get('difficulty',''))}"):
            st.markdown(f"**{q['text']}**")
            opts = q.get("options", [])
            labels = ["الف", "ب", "ج", "د"]
            correct = q.get("correct_answer")
            for j, opt in enumerate(opts):
                prefix = "✅ " if j == correct else "   "
                st.markdown(f"{prefix}{labels[j]}) {opt}")
            if q.get("source_file"):
                st.caption(f"منبع: {q['source_file']}")

    if len(filtered) > 100:
        st.info(f"نمایش ۱۰۰ سوال اول از {len(filtered)} سوال. از فیلترها برای محدود کردن استفاده کنید.")


# ═══════════════════════════════════════════════════════════════════════════════
# صفحه ۳ — تحلیل الگو
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📊 تحلیل الگو":
    st.title("📊 تحلیل الگوهای طراح سوال")

    questions = db.get_all_questions()
    if not questions:
        st.info("ابتدا سوالات را آپلود کنید.")
        st.stop()

    cached = db.get_latest_analysis("main")

    col1, col2 = st.columns([3, 1])
    with col2:
        run_new = st.button("🔄 تحلیل جدید با AI", type="primary", help="تحلیل عمیق توسط Claude")

    if run_new:
        client = get_client()
        if client:
            with st.spinner("در حال تحلیل الگوهای طراح سوال... "):
                analysis = anal.analyze_patterns(client, questions)
                db.save_analysis("main", analysis)
                cached = analysis
            st.success("تحلیل انجام شد!")

    if cached:
        analysis = cached
        stats = analysis.get("stats_summary", {})

        # نمودارها
        c1, c2 = st.columns(2)
        with c1:
            subj_data = stats.get("subjects", {})
            if subj_data:
                df = pd.DataFrame(list(subj_data.items()), columns=["درس", "تعداد"]).sort_values("تعداد", ascending=True)
                fig = px.bar(df, x="تعداد", y="درس", orientation="h", title="توزیع بر اساس درس", color="تعداد", color_continuous_scale="blues")
                fig.update_layout(font_family="Vazirmatn", height=300)
                st.plotly_chart(fig, use_container_width=True)

        with c2:
            diff_data = stats.get("difficulties", {})
            if diff_data:
                labels = {"easy": "آسان", "medium": "متوسط", "hard": "سخت"}
                df2 = pd.DataFrame(
                    [(labels.get(k, k), v) for k, v in diff_data.items()],
                    columns=["سختی", "تعداد"],
                )
                fig2 = px.pie(df2, names="سختی", values="تعداد", title="توزیع سختی", color_discrete_sequence=px.colors.qualitative.Set2)
                fig2.update_layout(font_family="Vazirmatn")
                st.plotly_chart(fig2, use_container_width=True)

        # موضوعات داغ
        hot = analysis.get("hot_topics", [])
        if hot:
            st.subheader("🔥 موضوعات داغ")
            cols = st.columns(min(len(hot), 4))
            for i, topic in enumerate(hot[:4]):
                cols[i % 4].markdown(f"<div class='metric-card'>{topic}</div>", unsafe_allow_html=True)

        st.markdown("---")

        # ذهن طراح
        st.subheader("🧠 ذهن طراح سوال")
        st.info(analysis.get("designer_mindset", ""))

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("🎯 الگوهای کلیدی")
            for p in analysis.get("key_patterns", []):
                st.markdown(f"- {p}")

            st.subheader("📈 الگوی سختی")
            st.write(analysis.get("difficulty_pattern", ""))

        with col_b:
            st.subheader("📖 توصیه‌های مطالعاتی")
            for r in analysis.get("study_recommendations", []):
                st.markdown(f"- ✅ {r}")

            st.subheader("⚠️ نقاط ضعف احتمالی")
            for w in analysis.get("weak_spots", []):
                st.markdown(f"- ⚠️ {w}")

        st.subheader("🔮 پایه پیش‌بینی")
        st.success(analysis.get("prediction_basis", ""))

        if stats.get("topics"):
            st.subheader("📊 توزیع موضوعات")
            top_topics = dict(list(sorted(stats["topics"].items(), key=lambda x: -x[1]))[:15])
            df3 = pd.DataFrame(list(top_topics.items()), columns=["موضوع", "تعداد"]).sort_values("تعداد", ascending=True)
            fig3 = px.bar(df3, x="تعداد", y="موضوع", orientation="h", title="پرتکرارترین موضوعات", color="تعداد", color_continuous_scale="reds")
            fig3.update_layout(font_family="Vazirmatn", height=400)
            st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("برای تحلیل هوشمند، روی «تحلیل جدید با AI» کلیک کنید.")

        # نمودارهای پایه بدون AI
        subj_data: dict[str, int] = {}
        diff_data: dict[str, int] = {}
        for q in questions:
            s = q.get("subject") or "نامشخص"
            subj_data[s] = subj_data.get(s, 0) + 1
            d = q.get("difficulty") or "نامشخص"
            diff_data[d] = diff_data.get(d, 0) + 1

        if subj_data:
            df = pd.DataFrame(list(subj_data.items()), columns=["درس", "تعداد"]).sort_values("تعداد", ascending=False)
            fig = px.bar(df, x="درس", y="تعداد", title="توزیع سوالات بر اساس درس", color="تعداد", color_continuous_scale="viridis")
            fig.update_layout(font_family="Vazirmatn")
            st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# صفحه ۴ — پیش‌بینی
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔮 پیش‌بینی":
    st.title("🔮 پیش‌بینی سوالات آزمون بعدی")

    questions = db.get_all_questions()
    if not questions:
        st.info("ابتدا سوالات را آپلود کنید.")
        st.stop()

    analysis = db.get_latest_analysis("main")
    if not analysis:
        st.warning("برای پیش‌بینی دقیق‌تر، ابتدا در بخش «تحلیل الگو» تحلیل AI انجام دهید.")
        analysis = {
            "stats_summary": {},
            "key_patterns": [],
            "hot_topics": [],
            "prediction_basis": "",
        }

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.markdown(f"**{len(questions)}** سوال در بانک | تحلیل: {'✅ انجام شده' if db.get_latest_analysis('main') else '❌ انجام نشده'}")
    with col2:
        count = st.slider("تعداد سوالات پیش‌بینی", 5, 20, 10)
    with col3:
        run_pred = st.button("🔮 پیش‌بینی با AI", type="primary")

    if run_pred:
        client = get_client()
        if client:
            with st.spinner(f"در حال پیش‌بینی {count} سوال بر اساس الگوهای طراح..."):
                predicted, reasoning = pred.predict_questions(client, questions, analysis, count)
                db.save_prediction(predicted, reasoning)
            st.success("پیش‌بینی انجام شد!")
            st.rerun()

    predicted, reasoning = db.get_latest_prediction()

    if predicted:
        if reasoning:
            st.subheader("🧠 منطق پیش‌بینی")
            st.info(reasoning)
            st.markdown("---")

        st.subheader(f"📝 {len(predicted)} سوال پیش‌بینی شده")

        diff_label = {"easy": "آسان 🟢", "medium": "متوسط 🟡", "hard": "سخت 🔴"}
        for i, q in enumerate(predicted):
            st.markdown(f"""
<div class='predicted-card'>
<h4>سوال {i+1} — {q.get('subject','')} | {q.get('topic','')} | {diff_label.get(q.get('difficulty',''), q.get('difficulty',''))}</h4>
<p><strong>{q.get('text','')}</strong></p>
</div>
""", unsafe_allow_html=True)

            opts = q.get("options", [])
            labels = ["الف", "ب", "ج", "د"]
            correct = q.get("correct_answer", 0)
            cols = st.columns(2)
            for j, opt in enumerate(opts):
                marker = "✅ " if j == correct else "   "
                cols[j % 2].markdown(f"{marker}{labels[j]}) {opt}")

            with st.expander("💡 توضیح و دلیل پیش‌بینی"):
                if q.get("explanation"):
                    st.markdown(f"**توضیح پاسخ:** {q['explanation']}")
                if q.get("why_predicted"):
                    st.markdown(f"**دلیل پیش‌بینی:** {q['why_predicted']}")

            st.markdown("---")

        # دکمه خروجی JSON
        st.download_button(
            "📥 دانلود سوالات پیش‌بینی (JSON)",
            data=json.dumps(predicted, ensure_ascii=False, indent=2),
            file_name="predicted_questions.json",
            mime="application/json",
        )
    else:
        st.info("روی «پیش‌بینی با AI» کلیک کنید تا سوالات پیش‌بینی شوند.")


# ═══════════════════════════════════════════════════════════════════════════════
# صفحه ۵ — تمرین
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🏋️ تمرین":
    st.title("🏋️ حالت تمرین")

    if "practice_pool" not in st.session_state:
        st.session_state.practice_pool = []
    if "practice_index" not in st.session_state:
        st.session_state.practice_index = 0
    if "practice_answered" not in st.session_state:
        st.session_state.practice_answered = False
    if "practice_start_time" not in st.session_state:
        st.session_state.practice_start_time = None
    if "session_score" not in st.session_state:
        st.session_state.session_score = {"correct": 0, "wrong": 0}

    tab1, tab2, tab3 = st.tabs(["🎯 تمرین از بانک", "🤖 سوال جدید با AI", "📊 نتایج"])

    # ─── تب ۱: تمرین از بانک ────────────────────────────────────────────────
    with tab1:
        bank_qs = db.get_all_questions()
        if not bank_qs:
            st.info("ابتدا سوالات را آپلود کنید.")
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                subjects = ["همه"] + db.get_subjects()
                prac_subj = st.selectbox("درس", subjects, key="prac_subj")
            with col2:
                diffs = ["همه", "easy", "medium", "hard"]
                prac_diff = st.selectbox("سطح سختی", diffs, key="prac_diff")
            with col3:
                pool_size = st.number_input("تعداد سوالات", 5, 100, 20, key="prac_size")

            if st.button("🎲 شروع تمرین", type="primary"):
                import random
                pool = bank_qs
                if prac_subj != "همه":
                    pool = [q for q in pool if q.get("subject") == prac_subj]
                if prac_diff != "همه":
                    pool = [q for q in pool if q.get("difficulty") == prac_diff]
                pool = [q for q in pool if q.get("options") and q.get("correct_answer") is not None]
                random.shuffle(pool)
                st.session_state.practice_pool = pool[:pool_size]
                st.session_state.practice_index = 0
                st.session_state.practice_answered = False
                st.session_state.session_score = {"correct": 0, "wrong": 0}
                st.session_state.practice_start_time = time.time()
                st.rerun()

            pool = st.session_state.practice_pool
            idx = st.session_state.practice_index

            if pool and idx < len(pool):
                q = pool[idx]
                opts = q.get("options", [])
                correct = q.get("correct_answer", 0)

                # نوار پیشرفت
                progress_val = idx / len(pool)
                st.progress(progress_val)
                st.caption(f"سوال {idx+1} از {len(pool)}")

                score = st.session_state.session_score
                c1, c2, c3 = st.columns(3)
                c1.metric("✅ صحیح", score["correct"])
                c2.metric("❌ غلط", score["wrong"])
                c3.metric("📊 درصد", f"{round(score['correct']/(score['correct']+score['wrong'])*100) if score['correct']+score['wrong'] > 0 else 0}%")

                st.markdown("---")
                diff_badge = {"easy": "🟢 آسان", "medium": "🟡 متوسط", "hard": "🔴 سخت"}
                st.caption(f"{q.get('subject','')} | {q.get('topic','')} | {diff_badge.get(q.get('difficulty',''), '')}")
                st.subheader(q["text"])

                labels = ["الف", "ب", "ج", "د"]

                if not st.session_state.practice_answered:
                    if not st.session_state.practice_start_time:
                        st.session_state.practice_start_time = time.time()

                    chosen = st.radio("پاسخ خود را انتخاب کنید:", options=range(len(opts)), format_func=lambda j: f"{labels[j]}) {opts[j]}", key=f"ans_{idx}")

                    if st.button("✅ ثبت پاسخ", type="primary"):
                        elapsed = time.time() - st.session_state.practice_start_time
                        is_correct = chosen == correct
                        db.save_practice_result(q.get("id", 0), chosen, is_correct, elapsed)
                        if is_correct:
                            st.session_state.session_score["correct"] += 1
                        else:
                            st.session_state.session_score["wrong"] += 1
                        st.session_state.practice_answered = True
                        st.session_state.practice_start_time = None
                        st.rerun()
                else:
                    # نمایش نتیجه
                    user_ans = st.session_state.get(f"ans_{idx}", 0)
                    for j, opt in enumerate(opts):
                        if j == correct:
                            st.success(f"✅ {labels[j]}) {opt} ← پاسخ صحیح")
                        else:
                            st.write(f"   {labels[j]}) {opt}")

                    if st.button("سوال بعدی ➡️", type="primary"):
                        st.session_state.practice_index += 1
                        st.session_state.practice_answered = False
                        st.rerun()

            elif pool and idx >= len(pool):
                score = st.session_state.session_score
                total_s = score["correct"] + score["wrong"]
                pct = round(score["correct"] / total_s * 100) if total_s > 0 else 0
                st.markdown(f"""
<div class='metric-card' style='padding:40px'>
<h2>🎉 تمرین تمام شد!</h2>
<h3>نتیجه: {score['correct']}/{total_s} ({pct}%)</h3>
</div>
""", unsafe_allow_html=True)
                if st.button("🔄 تمرین مجدد"):
                    st.session_state.practice_pool = []
                    st.session_state.practice_index = 0
                    st.rerun()

    # ─── تب ۲: سوال جدید با AI ───────────────────────────────────────────────
    with tab2:
        st.markdown("یک سوال سفارشی با AI بساز و حل کن.")

        c1, c2, c3 = st.columns(3)
        with c1:
            subj_input = st.text_input("درس", placeholder="مثلاً: فیزیک")
        with c2:
            topic_input = st.text_input("موضوع", placeholder="مثلاً: دینامیک")
        with c3:
            diff_input = st.selectbox("سختی", ["easy", "medium", "hard"], index=1)

        if st.button("🤖 تولید سوال", type="primary") and subj_input and topic_input:
            client = get_client()
            if client:
                with st.spinner("در حال تولید سوال..."):
                    generated = pred.generate_practice_question(client, subj_input, topic_input, diff_input)
                st.session_state.ai_question = generated
                st.session_state.ai_answered = False
                st.rerun()

        if "ai_question" in st.session_state:
            aq = st.session_state.ai_question
            opts = aq.get("options", [])
            correct = aq.get("correct_answer", 0)
            labels = ["الف", "ب", "ج", "د"]

            st.markdown("---")
            st.subheader(aq.get("text", ""))

            if not st.session_state.get("ai_answered"):
                ai_chosen = st.radio("پاسخ:", range(len(opts)), format_func=lambda j: f"{labels[j]}) {opts[j]}", key="ai_ans")
                if st.button("✅ ثبت پاسخ", type="primary", key="ai_submit"):
                    st.session_state.ai_user_answer = ai_chosen
                    st.session_state.ai_answered = True
                    st.rerun()
            else:
                user_ans = st.session_state.get("ai_user_answer", 0)
                for j, opt in enumerate(opts):
                    if j == correct:
                        st.success(f"✅ {labels[j]}) {opt} ← پاسخ صحیح")
                    elif j == user_ans:
                        st.error(f"❌ {labels[j]}) {opt} ← پاسخ شما")
                    else:
                        st.write(f"   {labels[j]}) {opt}")

                if aq.get("explanation"):
                    with st.expander("💡 توضیح پاسخ"):
                        st.write(aq["explanation"])

    # ─── تب ۳: نتایج ────────────────────────────────────────────────────────
    with tab3:
        stats = db.get_practice_stats()
        if stats["total"] == 0:
            st.info("هنوز سوالی حل نشده.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("کل حل‌شده", stats["total"])
            c2.metric("✅ صحیح", stats["correct"])
            c3.metric("❌ غلط", stats["wrong"])
            c4.metric("درصد موفقیت", f"{stats['accuracy']}%")

            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=stats["accuracy"],
                domain={"x": [0, 1], "y": [0, 1]},
                title={"text": "درصد موفقیت"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#667eea"},
                    "steps": [
                        {"range": [0, 50], "color": "#f8d7da"},
                        {"range": [50, 75], "color": "#fff3cd"},
                        {"range": [75, 100], "color": "#d4edda"},
                    ],
                },
            ))
            fig.update_layout(font_family="Vazirmatn")
            st.plotly_chart(fig, use_container_width=True)
