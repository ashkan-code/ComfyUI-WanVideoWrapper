/* ==============================
   SYNTIQ — AI Agency Dashboard
   app.js
   ============================== */

// ---- State ----
const state = {
  apiKey: localStorage.getItem('syntiq_api_key') || '',
  provider: localStorage.getItem('syntiq_provider') || 'groq',
  currentAgent: 'nova',
  history: {
    nova: JSON.parse(localStorage.getItem('syntiq_history_nova') || '[]'),
    rex: JSON.parse(localStorage.getItem('syntiq_history_rex') || '[]'),
    pixel: JSON.parse(localStorage.getItem('syntiq_history_pixel') || '[]'),
    atlas: JSON.parse(localStorage.getItem('syntiq_history_atlas') || '[]'),
    aria: JSON.parse(localStorage.getItem('syntiq_history_aria') || '[]'),
    tube: JSON.parse(localStorage.getItem('syntiq_history_tube') || '[]'),
  },
  selectedTypes: { nova: 'instagram-caption', rex: 'cold-email', pixel: 'modern-dark', atlas: 'hashtag-strategy', tube: 'long-form' },
  lastOutputs: { nova: '', rex: '', pixel: '', atlas: '', aria: '', tube: '' },
  tracker: JSON.parse(localStorage.getItem('syntiq_tracker') || '[]'),
  aria: {
    mode: 'image',
    endpoint: localStorage.getItem('syntiq_aria_endpoint') || 'http://localhost:8188',
    comfyOnline: false,
    enhanceEnabled: true,
    lastImageUrl: null,
    lastFilename: null,
    generatedFrames: [],
    promptId: null,
  },
};

// ---- DOM refs ----
const $ = (id) => document.getElementById(id);

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
  spawnParticles();
  setupNav();
  setupApiPanel();
  setupProviderTabs();
  setupTypeBtns();
  setupGenerateBtns();
  setupCopyBtns();
  setupClearBtns();
  setupPixelDownload();
  setupTracker();
  setupNovaPreview();
  setupAria();
  setupMission();
  setupTube();
  renderAllHistories();
  renderTracker();
  if (state.apiKey) updateApiStatus(true);
});

// ---- Background Particles ----
function spawnParticles() {
  const container = $('bgParticles');
  const colors = ['#f472b6', '#a855f7', '#f59e0b', '#06b6d4', '#3b82f6', '#8b5cf6'];
  for (let i = 0; i < 30; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    const size = Math.random() * 3 + 1;
    p.style.cssText = `
      width: ${size}px; height: ${size}px;
      left: ${Math.random() * 100}%;
      background: ${colors[Math.floor(Math.random() * colors.length)]};
      animation-duration: ${Math.random() * 20 + 15}s;
      animation-delay: ${Math.random() * 20}s;
      filter: blur(${size > 2 ? 1 : 0}px);
    `;
    container.appendChild(p);
  }
}

// ---- Nav ----
function setupNav() {
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const agent = btn.dataset.agent;
      switchAgent(agent);
    });
  });
}

function switchAgent(agent) {
  state.currentAgent = agent;
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.toggle('active', b.dataset.agent === agent));
  document.querySelectorAll('.agent-section').forEach(s => s.classList.toggle('active', s.id === `section-${agent}`));
}

// ---- Provider notes ----
const providerNotes = {
  groq: '🆓 <strong>Groq رایگانه!</strong> برو <strong>console.groq.com</strong> — ثبت‌نام کن، API Key بگیر، اینجا بذار. بدون کارت بانکی.',
  gemini: '🆓 <strong>Gemini رایگانه!</strong> برو <strong>aistudio.google.com</strong> — با گوگل لاگین کن، Get API Key بزن، کپی کن بیار.',
  anthropic: '💳 <strong>Anthropic پولیه.</strong> برو <strong>console.anthropic.com</strong> — ثبت‌نام کن، کارت بزن، API Key بگیر.',
};
const providerPlaceholders = {
  groq: 'gsk_...',
  gemini: 'AIzaSy...',
  anthropic: 'sk-ant-api03-...',
};

// ---- API Panel ----
function setupApiPanel() {
  const panel = $('apiPanel');
  const toggleBtn = $('apiToggleBtn');
  const input = $('apiKeyInput');
  const saveBtn = $('saveApiBtn');

  if (state.apiKey) input.value = state.apiKey;
  input.placeholder = providerPlaceholders[state.provider];

  toggleBtn.addEventListener('click', () => panel.classList.toggle('open'));

  saveBtn.addEventListener('click', () => {
    const key = input.value.trim();
    if (key) {
      state.apiKey = key;
      localStorage.setItem('syntiq_api_key', key);
      updateApiStatus(true);
      panel.classList.remove('open');
      showToast('API key ذخیره شد!');
    } else {
      showToast('لطفاً API Key وارد کن', 'error');
    }
  });

  input.addEventListener('keydown', e => { if (e.key === 'Enter') saveBtn.click(); });
}

// ---- Provider Tabs ----
function setupProviderTabs() {
  document.querySelectorAll('.provider-tab').forEach(btn => {
    if (btn.dataset.provider === state.provider) btn.classList.add('active');
    else btn.classList.remove('active');

    btn.addEventListener('click', () => {
      document.querySelectorAll('.provider-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.provider = btn.dataset.provider;
      localStorage.setItem('syntiq_provider', state.provider);
      $('apiNote').innerHTML = providerNotes[state.provider];
      $('apiKeyInput').placeholder = providerPlaceholders[state.provider];
      $('apiKeyInput').value = '';
      state.apiKey = '';
      updateApiStatus(false);
    });
  });
  $('apiNote').innerHTML = providerNotes[state.provider];
}

function updateApiStatus(active) {
  const indicator = $('apiStatus');
  indicator.classList.toggle('active', active);
  indicator.querySelector('.status-text').textContent = active ? 'Connected' : 'No API Key';
}

// ---- Type Buttons ----
function setupTypeBtns() {
  ['nova', 'rex', 'pixel', 'atlas', 'tube'].forEach(agent => {
    const section = $(`section-${agent}`);
    section.querySelectorAll('.type-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        section.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.selectedTypes[agent] = btn.dataset.type;
        updateOutputTypeLabel(agent, btn.textContent.trim());
      });
    });
  });
}

function updateOutputTypeLabel(agent, label) {
  const el = $(`${agent}-output-type`);
  if (el) el.textContent = label;
}

// ---- Generate Buttons ----
function setupGenerateBtns() {
  $('nova-generate').addEventListener('click', () => runAgent('nova'));
  $('rex-generate').addEventListener('click', () => runAgent('rex'));
  $('pixel-generate').addEventListener('click', () => runAgent('pixel'));
  $('atlas-generate').addEventListener('click', () => runAgent('atlas'));
  $('tube-generate').addEventListener('click', () => runAgent('tube'));
  $('aria-generate').addEventListener('click', () => runAriaAgent());
}

async function runAgent(agent) {
  if (!state.apiKey) {
    $('apiPanel').classList.add('open');
    showToast('Please add your Anthropic API key first', 'error');
    return;
  }

  const prompt = buildPrompt(agent);
  if (!prompt) {
    showToast('Please fill in the required fields', 'error');
    return;
  }

  showLoading(agent);

  try {
    const result = await callAnthropic(agent, prompt);
    hideLoading();
    renderOutput(agent, result);
    saveToHistory(agent, result, prompt.label);
    state.lastOutputs[agent] = result;
    if (agent === 'pixel') $('pixel-download').style.display = 'flex';
  } catch (err) {
    hideLoading();
    renderOutput(agent, `❌ Error: ${err.message}\n\nMake sure your API key is correct and you have access to Claude models.`);
  }
}

// ---- Prompt Builders ----
function buildPrompt(agent) {
  if (agent === 'nova') return buildNovaPrompt();
  if (agent === 'rex') return buildRexPrompt();
  if (agent === 'pixel') return buildPixelPrompt();
  if (agent === 'atlas') return buildAtlasPrompt();
  if (agent === 'tube') return buildTubePrompt();
}

function buildNovaPrompt() {
  const business = $('nova-business').value.trim();
  const industry = $('nova-industry').value.trim();
  const audience = $('nova-audience').value.trim();
  const topic = $('nova-topic').value.trim();
  const tone = $('nova-tone').value;
  const type = state.selectedTypes.nova;

  if (!business || !topic) return null;

  const typeMap = {
    'instagram-caption': `Write a WORLD-CLASS Instagram caption for "${business}" in the ${industry} industry. Topic: "${topic}". Target audience: ${audience || 'general'}. Tone: ${tone}.

Return EXACTLY this structure (use the section headers as shown):

## 📸 INSTAGRAM CAPTION

[Write 3-5 sentence caption with a POWERFUL hook in the first line, storytelling in the middle, and a clear CTA at the end. Make it feel authentic, not corporate. Use line breaks for readability.]

## 🏷️ HASHTAGS

[30 hashtags grouped as: 5 mega (1M+ posts), 10 large (100K-1M), 10 medium (10K-100K), 5 niche (under 10K). Include a branded hashtag.]

## ⏰ BEST TIME TO POST

[Day and time with timezone. Explain WHY this time works for this audience.]

## 💡 CONTENT TIPS

[4 bullet points: visual direction, story angle, engagement tactic, A/B test idea]

## 🎯 HOOK ALTERNATIVES

[3 alternative opening lines to test]`,

    'youtube-script': `Write a COMPLETE, PROFESSIONAL YouTube video script for "${business}" in the ${industry} industry. Topic/video idea: "${topic}". Target audience: ${audience || 'general'}. Tone: ${tone}.

Return EXACTLY this structure:

## 🎬 VIDEO TITLE (5 options)

[5 clickable titles with power words and numbers where relevant]

## ⚡ HOOK (First 30 seconds — non-negotiable)

[The EXACT words to say in the first 30 seconds. Must create pattern interrupt, promise value, and tease the ending.]

## 🎯 INTRO (30–90 seconds)

[Introduce yourself/brand, establish credibility, preview what they'll learn]

## 📋 MAIN CONTENT (timestamps)

[00:00 – Intro
01:30 – [Section 1 title]
[Write out the key talking points for each section with transition phrases]
Each section should have 3-5 bullet points of what to say]

## 🔥 CALL TO ACTION

[Exact CTA script for subscribe, like, comment, and any lead magnet]

## 📌 DESCRIPTION (YouTube SEO)

[Full YouTube description with keywords, timestamps, and links placeholder]

## 🏷️ TAGS

[30 SEO tags for maximum reach]`,

    'reel-script': `Write a VIRAL Instagram Reel script for "${business}" in the ${industry} industry. Topic: "${topic}". Audience: ${audience || 'general'}. Tone: ${tone}.

Return EXACTLY this structure:

## 🎬 REEL CONCEPT

[One-line concept. Hook type. Target emotion.]

## ⚡ SCRIPT (15–30 second version)

[Second-by-second breakdown:
0-3s: [Hook text + visual action]
3-8s: [Main point 1 + visual]
8-15s: [Main point 2 + visual]
15-25s: [Payoff/twist + visual]
25-30s: [CTA + text overlay]

Include: exact words to say, caption for text overlay, visual direction]

## 🎵 AUDIO SUGGESTION

[Trending audio style or song type. Why it works.]

## 📱 TEXT OVERLAYS

[All the on-screen text, font style suggestion, animation]

## 💬 CAPTION + HASHTAGS

[Short punchy caption + 15 hashtags]`,

    'content-strategy': `Create a COMPLETE 30-day content strategy for "${business}" in the ${industry} industry. Target audience: ${audience || 'general'}. Tone: ${tone}.

## 📅 CONTENT CALENDAR (4 weeks)

[Week 1–4 plan with daily post types: Mon-Sun]

## 🎯 CONTENT PILLARS (5 pillars)

[Define 5 content categories with rationale and 3 post ideas each]

## 📈 GROWTH STRATEGY

[Algorithm tips, engagement tactics, collaboration ideas, viral content framework]

## 🔥 VIRAL POST IDEAS (10 ideas)

[10 ready-to-execute post concepts with format, hook, and expected outcome]

## 📊 KPIs TO TRACK

[What to measure weekly and monthly]`,

    'ruth-reel': `Write a VIRAL Instagram Reel script for Ruth — a warm, charismatic young American woman who teaches web development and AI tools. She works for Syntiq AI Agency (@syntiq.ai). Topic: "${topic}". Audience: ${audience || 'American beginners 20-35 who want to learn web dev and AI'}.

Ruth's voice: natural American English, energetic, relatable, occasionally funny, never corporate. She makes tech feel exciting and accessible.

## 🎬 REEL CONCEPT
[One-sentence hook concept. Target emotion. Why it will stop the scroll.]

## ⚡ RUTH'S SCRIPT (30-60 seconds)
[Write second-by-second:
0-3s: [RUTH ON CAMERA — attention-grabbing opening line, spoken naturally]
3-10s: [Setup the value — what they're about to learn]
10-30s: [The actual quick tip or insight — simple, visual, actionable]
30-50s: [The payoff — the "aha" moment]
50-60s: [CTA — "Follow @syntiq.ai for more" + subscribe plug]
Include exact words Ruth says, text overlay, and visual direction for each segment.]

## 🎵 AUDIO & VIBE
[Trending audio style. Energy level. Background setting for Ruth.]

## 📱 TEXT OVERLAYS
[All on-screen text with timing and style suggestion]

## 💬 CAPTION + HASHTAGS
[Punchy caption in Ruth's voice + 20 hashtags targeting US tech/web dev audience]`,

    'ruth-story': `Write a set of 5 connected Instagram Story slides for Ruth from Syntiq AI Agency (@syntiq.ai). Topic: "${topic}". Audience: ${audience || 'American beginners interested in web dev and AI'}.

Ruth is warm, funny, relatable — like a smart friend teaching you something cool. Stories should feel casual and human, not like an ad.

## 📱 STORY SLIDE 1 — Hook
[What Ruth says/shows in the first 3 seconds to stop swipes. Text overlay + visual direction.]

## 📱 STORY SLIDE 2 — Setup
[Introduce the problem or situation. Relatable pain point. Ruth on camera or screen recording.]

## 📱 STORY SLIDE 3 — Tip/Reveal
[The actual value. Keep it simple and visual. One clear insight per slide.]

## 📱 STORY SLIDE 4 — Deeper Insight
[The "bonus" detail most people don't know. Creates authority and trust.]

## 📱 STORY SLIDE 5 — CTA
[Soft, friendly call to action: follow, DM for questions, swipe up to link, or poll/quiz for engagement.]

## 🎨 VISUAL DIRECTION
[Overall vibe: color palette, font style, Ruth's on-camera style, background setting]`,

    'ruth-bio': `Write a COMPLETE, HIGH-CONVERTING Instagram bio for Ruth's account at Syntiq AI Agency. The account handle is @syntiq.ai.

Ruth is a warm, charismatic American woman who teaches web development and AI tools to beginners. She represents the human face of Syntiq AI Agency.

## 👤 PROFILE NAME
[Display name — max 30 chars. Should include keywords.]

## 📝 BIO (150 chars max)
[5 lines maximum. Each line punchy and purposeful:
Line 1: Who Ruth is — identity + niche
Line 2: What she teaches — the transformation
Line 3: Who it's for — target audience
Line 4: Social proof or credibility hook
Line 5: CTA with emoji → link]

## 🔗 LINK IN BIO
[What the link should lead to and suggested URL text]

## 🌟 STORY HIGHLIGHT COVERS (5)
[Names and icon/theme for 5 permanent highlight categories Ruth should have]

## 🖼️ PROFILE PHOTO DIRECTION
[What Ruth's profile photo should look like: background, expression, clothing, framing]

## 📌 PINNED POST IDEAS (3)
[3 posts Ruth should pin at the top of her grid and why]`
  };

  return { label: `${business} — ${type}`, content: typeMap[type] };
}

function buildRexPrompt() {
  const business = $('rex-business').value.trim();
  const service = $('rex-service').value.trim();
  const prospect = $('rex-prospect').value.trim();
  const pain = $('rex-pain').value.trim();
  const usp = $('rex-usp').value.trim();
  const type = state.selectedTypes.rex;

  if (!business || !service || !prospect) return null;

  const typeMap = {
    'cold-email': `You are Rex, a world-class sales copywriter. Write the PERFECT cold email to sell "${service}" from "${business}" to a "${prospect}".
Pain point: "${pain || 'outdated online presence'}". Unique offer: "${usp || 'professional results at competitive price'}".

Return EXACTLY this structure:

## 📧 SUBJECT LINE (5 options)

[5 subject lines. Mix curiosity, personalization, and benefit-driven angles. Keep under 50 chars each.]

## ✉️ EMAIL BODY

[Write the full email. Rules:
- First line = no "I hope this finds you" garbage. Go straight for the pain or compliment.
- Max 150 words
- 1 personalization hook in opening
- 1 specific result/proof point
- 1 clear, low-friction CTA
- No attachments or pressure
- Sound like a real person, not a salesperson]

## 🔑 SEND STRATEGY

[Best day/time to send, follow-up timing, A/B test recommendations]

## 📊 PSYCHOLOGY BREAKDOWN

[Explain which persuasion principles this email uses and why they work]`,

    'followup-sequence': `You are Rex, a world-class sales email copywriter. Write a COMPLETE 5-email follow-up sequence for selling "${service}" from "${business}" to a "${prospect}". Unique offer: "${usp}".

Return EXACTLY this structure for ALL 5 emails:

## EMAIL 1 — Day 1 (Initial)
**Subject:**
**Body:**
**CTA:**

## EMAIL 2 — Day 3 (Value add)
**Subject:**
**Body:**
**CTA:**

## EMAIL 3 — Day 7 (Social proof)
**Subject:**
**Body:**
**CTA:**

## EMAIL 4 — Day 14 (Urgency/Scarcity)
**Subject:**
**Body:**
**CTA:**

## EMAIL 5 — Day 21 (The Breakup)
**Subject:**
**Body:**
**CTA:**

## 📋 SEQUENCE STRATEGY NOTES
[When to stop, how to handle replies, objection handling tips]`,

    'linkedin-outreach': `You are Rex. Write the PERFECT LinkedIn DM to sell "${service}" from "${business}" to a "${prospect}". USP: "${usp}".

Return EXACTLY this structure:

## 💼 CONNECTION REQUEST NOTE (under 300 chars)

[The personalized connection note. Mention something specific to their industry.]

## 📨 FIRST MESSAGE (after connection accepted)

[The actual DM. Max 100 words. No pitch yet. Build rapport. Ask 1 smart question.]

## 💬 FOLLOW-UP MESSAGE (if no reply in 5 days)

[Short, casual bump. Show you did research. Restate value in 1 sentence.]

## 🎯 PITCH MESSAGE (if they engage)

[Now pitch. Full value prop in under 120 words. Specific ROI claim. Clear next step.]

## 📌 TIPS FOR THIS PROSPECT

[Platform behavior tips, best time to DM, profile optimization suggestion]`
  };

  return { label: `${business} → ${prospect}`, content: typeMap[type] };
}

function buildPixelPrompt() {
  const business = $('pixel-business').value.trim();
  const industry = $('pixel-industry').value.trim();
  const location = $('pixel-location').value.trim();
  const goal = $('pixel-goal').value;
  const services = $('pixel-services').value.trim();
  const style = state.selectedTypes.pixel;

  if (!business || !industry) return null;

  const styleGuides = {
    'modern-dark': 'dark background (#0a0a0f), electric accent colors (blue/purple), glassmorphism cards, subtle gradients',
    'clean-minimal': 'white background, clean typography, lots of whitespace, subtle shadows, one accent color',
    'bold-colorful': 'bold typography, vibrant gradients, high contrast, energetic layout',
    'luxury-premium': 'black and gold palette, elegant serif typography, premium spacing, refined micro-interactions'
  };

  const goalText = {
    'lead-gen': 'generate phone calls and contact form submissions',
    'ecommerce': 'sell products and drive purchases',
    'portfolio': 'showcase work and attract clients',
    'booking': 'drive appointment bookings',
    'brand': 'build brand recognition and trust'
  };

  return {
    label: `${business} — ${style} website`,
    content: `You are Pixel, a world-class web designer. Create a COMPLETE, STUNNING, PRODUCTION-READY HTML website for:

Business: "${business}"
Industry: ${industry}
Location: ${location || 'USA'}
Goal: ${goalText[goal]}
Services: ${services || industry + ' services'}
Design Style: ${style} — ${styleGuides[style]}

REQUIREMENTS — READ EVERY WORD:
1. Single HTML file with ALL CSS embedded in <style> and ALL JS in <script>
2. Must look like it cost $10,000 minimum — world-class design
3. Mobile-first, fully responsive
4. Smooth animations and transitions throughout
5. Sections: Hero (with CTA), Services, About, Social Proof/Testimonials, FAQ, Contact Form, Footer
6. Hero must have a compelling headline + subheadline tailored to the business
7. Use CSS custom properties, flexbox/grid
8. Add CSS animations: fade-in on scroll (Intersection Observer), hover effects on cards and buttons
9. Contact form with validation (no backend needed — just show success message)
10. Phone click-to-call button prominently displayed
11. Google Maps embed placeholder
12. Professional micro-interactions on all interactive elements
13. SEO meta tags (title, description, OG tags)
14. Favicon using SVG in <head>
15. Loading screen animation

Return ONLY the complete HTML code. No explanation before or after. Start with <!DOCTYPE html> and end with </html>. Make it breathtaking.`
  };
}

// ============================================================
// NOVA PREVIEW PANEL
// ============================================================

const igTypeConfig = {
  post:      { icon: '📸', name: 'Post',      sub: 'پست فید اینستاگرام',   hint: 'تصویر / کاروسل', mediaClass: '',        reel: false, story: false },
  reel:      { icon: '🎬', name: 'Reel',      sub: 'ویدیو کوتاه ۹:۱۶',     hint: 'ویدیو کوتاه ۳۰-۹۰ ثانیه', mediaClass: 'story-mode', reel: true,  story: false },
  story:     { icon: '📱', name: 'Story',     sub: 'استوری ۲۴ ساعته',      hint: 'تصویر یا ویدیو ۱۵ ثانیه', mediaClass: 'story-mode', reel: false, story: true  },
  video:     { icon: '🎥', name: 'Video',     sub: 'ویدیو بلند (IGTV)',     hint: 'ویدیو بالای ۱ دقیقه', mediaClass: '',        reel: true,  story: false },
  highlight: { icon: '⭐', name: 'Highlight', sub: 'استوری دائمی (Highlight)', hint: 'استوری‌های ذخیره شده', mediaClass: 'story-mode', reel: false, story: true  },
};

let novaPreviewState = {
  igType: 'post',
  caption: '',
  hashtags: '',
  approved: false,
};

function setupNovaPreview() {
  // IG type pills
  document.querySelectorAll('.ig-type-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.ig-type-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      novaPreviewState.igType = btn.dataset.igType;
      updateIgTypeUI();
    });
  });

  // Sync preview button
  $('btnSyncPreview').addEventListener('click', () => {
    novaPreviewState.caption = $('novaEditCaption').value;
    novaPreviewState.hashtags = $('novaEditHashtags').value;
    updatePreviewContent();
    showToast('پیش‌نمایش آپدیت شد');
  });

  // Approve button
  $('nova-approve-btn').addEventListener('click', () => {
    novaPreviewState.approved = true;
    const cfg = igTypeConfig[novaPreviewState.igType];
    $('nova-approved-banner').classList.add('visible');
    $('approved-type-final').textContent = `${cfg.name} (${cfg.sub})`;
    $('approveRow').style.opacity = '0.4';
    $('approveRow').style.pointerEvents = 'none';
    showToast('محتوا تأیید شد ✅');
  });

  // Revoke button
  $('nova-revoke-btn').addEventListener('click', () => {
    novaPreviewState.approved = false;
    $('nova-approved-banner').classList.remove('visible');
    $('approveRow').style.opacity = '';
    $('approveRow').style.pointerEvents = '';
    showToast('تأیید لغو شد');
  });

  // Regenerate button
  $('nova-regenerate-btn').addEventListener('click', () => {
    resetNovaPreview();
    runAgent('nova');
  });

  // Live sync: typing in edit areas syncs to preview after short pause
  let syncTimer;
  ['novaEditCaption', 'novaEditHashtags'].forEach(id => {
    $(id).addEventListener('input', () => {
      clearTimeout(syncTimer);
      syncTimer = setTimeout(() => {
        novaPreviewState.caption = $('novaEditCaption').value;
        novaPreviewState.hashtags = $('novaEditHashtags').value;
        updatePreviewContent();
      }, 600);
    });
  });
}

function updateIgTypeUI() {
  const cfg = igTypeConfig[novaPreviewState.igType];

  // badge
  $('igTypeBadgeBig').textContent = `${cfg.icon} ${cfg.name} — ${cfg.sub}`;

  // media area class
  const mediaArea = $('igMediaArea');
  mediaArea.className = 'ig-media-area ' + cfg.mediaClass;

  // media hint
  $('igMediaHint').textContent = cfg.hint;

  // story bars
  $('igStoryFrame').style.display = cfg.story ? 'flex' : 'none';

  // reel icon
  const reelIcon = $('igReelIcon');
  if (cfg.reel) reelIcon.classList.add('visible');
  else reelIcon.classList.remove('visible');

  // hide post actions for story
  $('igPostActions').style.display = cfg.story ? 'none' : 'flex';

  // approve info
  $('approveTypeIcon').textContent = cfg.icon;
  $('approveTypeName').textContent = cfg.name;
  $('approveTypeSub').textContent = cfg.sub;
}

function showNovaPreview(rawOutput) {
  // Extract caption (first big text block) and hashtags
  const hashtagMatch = rawOutput.match(/(#\w+[\s#\w]*)/g);
  const hashtags = hashtagMatch ? hashtagMatch.join(' ').substring(0, 300) : '';

  // Strip markdown headers and get main text
  let caption = rawOutput
    .replace(/^##.+$/gm, '')
    .replace(/\*\*/g, '')
    .replace(/#\w+/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
    .substring(0, 400);

  novaPreviewState.caption = caption;
  novaPreviewState.hashtags = hashtags;
  novaPreviewState.approved = false;

  // Sync business name to username fields
  const biz = $('nova-business').value.trim();
  if (biz) {
    const slug = biz.toLowerCase().replace(/\s+/g, '.').replace(/[^a-z0-9.]/g, '');
    ['ig-preview-username', 'ig-cap-username'].forEach(id => {
      $(id).textContent = slug || 'yourbrand';
    });
  }

  // Fill edit areas
  $('novaEditCaption').value = caption;
  $('novaEditHashtags').value = hashtags;

  updatePreviewContent();
  updateIgTypeUI();

  // Reset approve state
  $('nova-approved-banner').classList.remove('visible');
  $('approveRow').style.opacity = '';
  $('approveRow').style.pointerEvents = '';

  // Show panel
  $('nova-preview-panel').classList.add('visible');
}

function updatePreviewContent() {
  const cap = novaPreviewState.caption;
  const tags = novaPreviewState.hashtags;

  const previewCap = cap.length > 120 ? cap.substring(0, 120) + '...' : cap;
  $('igCaptionPreview').textContent = previewCap || 'کپشن اینجا نمایش داده می‌شه...';

  // Show first 5 hashtags in preview
  const tagList = (tags.match(/#\w+/g) || []).slice(0, 6);
  $('igHashtagsPreview').textContent = tagList.join(' ');
}

function resetNovaPreview() {
  $('nova-preview-panel').classList.remove('visible');
  novaPreviewState = { igType: novaPreviewState.igType, caption: '', hashtags: '', approved: false };
}

// ============================================================

function buildAtlasPrompt() {
  const niche = $('atlas-niche').value.trim();
  const target = $('atlas-target').value.trim();
  const location = $('atlas-location').value.trim();
  const style = $('atlas-style').value;
  const type = state.selectedTypes.atlas;

  if (!niche) return null;

  const loc = location || 'USA (general)';
  const aud = target || 'American general audience';

  const typeMap = {
    'hashtag-strategy': `Create a COMPLETE American Instagram hashtag strategy for a ${niche} account targeting ${aud} in ${loc}. Content style: ${style}.

## 🇺🇸 AMERICAN HASHTAG MASTER LIST

### Mega Hashtags (1M+ posts) — use 3 max
[10 hashtags popular in the US for this niche]

### Large US Hashtags (100K–1M posts)
[15 hashtags trending with American audiences]

### Medium Niche Hashtags (10K–100K)
[15 targeted hashtags for this specific niche in America]

### Location-Based Hashtags
[10 city/state/region hashtags for ${loc}]

### Community Hashtags (under 10K — high engagement)
[10 tight-knit community tags Americans use]

## ⏰ BEST TIMES TO POST FOR US AUDIENCE

[Breakdown by timezone: EST, CST, PST — best days and hours for maximum reach with Americans]

## 📈 HASHTAG ROTATION STRATEGY

[How to rotate hashtags across posts to avoid shadowban. Give 3 sets of 30 hashtags to rotate weekly.]

## 🚫 HASHTAGS TO AVOID

[10 banned or shadowbanned hashtags in this niche that Americans use but hurt reach]`,

    'follow-targets': `You are Atlas. Build a PRECISE manual follow targeting guide for a ${niche} Instagram account wanting to reach ${aud} in ${loc}. Style: ${style}.

## 🎯 ACCOUNT TYPES TO FOLLOW MANUALLY

### Category 1: Direct Competitors (small, engaged)
[What to look for: follower range, engagement rate, bio keywords. Give 5 example search terms to find them.]

### Category 2: Complementary Accounts
[Non-competing accounts whose followers are your ideal US audience. Give 5 account types with example search terms.]

### Category 3: US Micro-Influencers
[Influencers with 5K–50K followers in this niche. How to find them. What engagement rate means they're real.]

### Category 4: Active American Commenters
[How to find highly engaged Americans in this niche by going through competitor comment sections. Step-by-step process.]

## 🔍 HOW TO FIND THEM (Step-by-Step)

[Exact Instagram search strategy: hashtags to browse, explore page technique, competitor follower lists]

## 📊 FOLLOW/UNFOLLOW STRATEGY (Manual, Safe)

[Daily limits to stay safe: how many to follow per day, when to unfollow, what ratios to maintain. Be specific with numbers.]

## 🇺🇸 AMERICAN TIMEZONE ACTIVITY WINDOWS

[Best hours to do manual following for each US timezone to catch people when they're active]`,

    'engagement-templates': `Create 20 GENUINE, HIGH-CONVERTING comment templates for a ${niche} account to engage with American ${aud} audience. Style: ${style}.

## 💬 COMMENT TEMPLATES BY TYPE

### Appreciation Comments (leave on target accounts)
[5 genuine comments that feel human, specific, and invite a reply. NOT generic. Must feel personal.]

### Question Comments (spark conversation)
[5 questions that open dialogue and make the account owner want to reply AND follow back]

### Value-Add Comments (show expertise)
[5 comments that add real value to the post and establish authority in ${niche}]

### Story Reply Templates
[5 templates to reply to stories that feel casual and start a DM conversation]

### DM Opener Templates (after they follow back)
[5 short, warm DM openers that DON'T pitch anything — just build rapport]

## ⚠️ WHAT NOT TO SAY

[10 comment styles Americans hate — emojis spam, "nice post!", generic compliments — what kills engagement]

## 📅 ENGAGEMENT SCHEDULE

[How many comments/stories to respond to per day, what time, to stay under Instagram's radar while building real connections]`,

    'growth-schedule': `Build a COMPLETE 30-day Instagram growth schedule for a ${niche} account targeting ${aud} in ${loc}. Content style: ${style}.

## 📅 WEEK 1 — Foundation (Days 1–7)

[Daily actions: what to post, what hashtags, how many accounts to follow manually, what to comment on. Be SPECIFIC with numbers.]

## 📅 WEEK 2 — Momentum (Days 8–14)

[Daily actions with slight scaling. Include story frequency, engagement target, follow count.]

## 📅 WEEK 3 — Acceleration (Days 15–21)

[Increased activity. Introduce collaborations, US-targeted content formats, Reels push.]

## 📅 WEEK 4 — Optimization (Days 22–30)

[Analyze, double down on what worked. Unfollow non-followers. Refine targeting.]

## 📊 DAILY LIMITS (Stay Safe from Instagram)

[Exact safe limits per day for: follows, unfollows, likes, comments, story views, DMs]

## 🎯 30-DAY TARGETS

[Realistic follower growth, engagement rate, and reach targets for a US audience in this niche]

## 🇺🇸 US CULTURAL CONTENT CALENDAR

[Key American dates, holidays, and events in the next 30 days to tie content to for maximum relevance]`,

    'us-trends': `You are Atlas. Research and report the HOTTEST current web development and AI tools trends in the United States for Instagram and YouTube content. Niche: ${niche}. Target: ${aud}.

## 🔥 TOP 10 US TRENDING TOPICS RIGHT NOW
### Web Dev & Programming
[5 specific topics blowing up on American Instagram/YouTube: React, AI coding tools, no-code, etc. For each: topic name, why it's trending with Americans, content angle that works, estimated monthly searches, example viral hook]

### AI Tools
[5 AI tools or concepts Americans are obsessed with right now. For each: tool/concept, what's driving US interest, best content angle, viral potential score 1-10]

## 📱 TRENDING CONTENT FORMATS FOR US TECH AUDIENCE
[What content FORMAT is getting the most views: tutorials, before/after, reactions, listicles, day-in-the-life coding vlogs, etc. Include specific metrics or observations.]

## 🏆 VIRAL CONTENT EXAMPLES TO STUDY
[5 types of viral tech/web dev posts that consistently crush it with American audiences — describe the pattern, not specific accounts]

## 📅 TREND FORECAST (next 30 days)
[What tech topics are about to explode for US audiences based on upcoming releases, events, or cultural moments]

## 🎯 CONTENT GAPS (Opportunities)
[3 underserved angles in the US web dev/AI niche where competition is low but interest is high — goldmine opportunities]`,

    'hook-formulas': `You are Atlas. Reveal the EXACT hook formulas that generate maximum views for web development and AI content targeting American audiences on Instagram Reels and YouTube. Niche: ${niche}. Audience: ${aud}.

## ⚡ TOP 15 HOOK FORMULAS FOR US TECH AUDIENCE

[For each formula:
- Formula name
- Template with blanks
- 3 fill-in examples for web dev / AI topics
- Why it works psychologically for Americans
- Best format: Reel / YouTube Short / Long-form]

Include these categories:
1. Curiosity gap hooks ("Nobody talks about...")
2. Transformation hooks ("I went from X to Y in Z time")
3. Counter-intuitive hooks ("Stop doing X — do this instead")
4. Proof hooks ("I built [thing] using only [tool]")
5. Fear/FOMO hooks ("If you're not using X yet, you're behind")
6. Simplification hooks ("X explained in 60 seconds")
7. List hooks ("5 things every developer wishes they knew sooner")

## 🧠 PSYCHOLOGY BREAKDOWN
[Why each hook category works specifically for American tech learners. What emotional trigger it activates.]

## 📊 HOOK PERFORMANCE BY PLATFORM
[Which hook types work best on Instagram Reels vs YouTube Shorts vs YouTube long-form — and why]

## 🎤 RUTH'S VOICE ADAPTATIONS
[How to deliver these hooks in Ruth's warm, relatable American woman voice — specific language patterns, energy level, opening body language]

## 🧪 A/B TESTING GUIDE
[How to test two hooks against each other. What metrics to watch. How long to run the test.]`
  };

  return { label: `${niche} — ${type}`, content: typeMap[type] };
}

function buildTubePrompt() {
  const topic = $('tube-topic').value.trim();
  const audience = $('tube-audience').value.trim();
  const value = $('tube-value').value.trim();
  const type = state.selectedTypes.tube;

  if (!topic) return null;

  const aud = audience || 'American beginners aged 20–35 who want to learn web development and AI tools';
  const val = value || 'you can build a professional website or use AI tools without any prior experience';

  const typeMap = {
    'long-form': `Write a COMPLETE YouTube video script for Ruth at Syntiq AI Agency. Ruth is a warm, charismatic, highly relatable young American woman teaching web development and AI tools to beginners. Her voice is natural, energetic, encouraging, occasionally funny — never corporate.

Topic: "${topic}"
Target audience: ${aud}
Core value proposition: ${val}

SCRIPT STRUCTURE (write all sections completely — this is a full production script):

## 🎬 VIDEO TITLES (5 options)
[5 scroll-stopping titles. Use numbers, power words, curiosity gaps. 60 chars max each.]

## ⚡ HOOK (0:00–0:30) — THE MOST IMPORTANT 30 SECONDS
[Exact words Ruth says. Must: create a pattern interrupt, make a bold promise, tease the ending. Start with something surprising or counter-intuitive. Ruth speaks directly to camera, high energy, feels spontaneous.]

## 👋 INTRO (0:30–2:00)
[Ruth introduces herself naturally: "Hey guys, I'm Ruth with Syntiq..." Builds quick credibility. Previews exactly what they'll learn. Teases the biggest "aha" moment coming later. Include a "subscribe if you're new" that doesn't feel forced.]

## 📚 MAIN CONTENT (2:00–12:00) — with timestamps
[Write detailed talking points for 4–5 sections:
[2:00] Section 1 — [title]
[Key point 1] [Key point 2] [Key point 3]
Transition line to next section

[4:30] Section 2 — [title]
...etc.
Each section has a clear teaching moment, an example, and a visual direction note.]

## 💥 BREAK STORY (mid-video, ~8:00 mark)
[This is the BREAK segment — a short 60–90 second story to refresh viewer attention.
Ruth transitions naturally: "Okay real quick before we keep going — I have to tell you this story..."
The story must be: relatable to Americans, slightly funny or surprising, emotionally resonant, tied loosely to the video topic.
End with a smooth return: "Anyway, back to what we were doing..." — and jump back in with energy.]

## 🔑 THE BIG PAYOFF (12:00–14:00)
[The main "aha" moment or final technique. The thing viewers came for. Deliver it clearly and confidently.]

## 📣 CALL TO ACTION (14:00–15:00)
[Ruth's exact words. Not corporate. Warm, grateful, genuine:
- Subscribe with reason ("I post every week and it's literally free education")
- Instagram follow: @syntiq.ai
- Comment prompt to boost algorithm
- Like the video]

## 📋 YOUTUBE DESCRIPTION (SEO)
[Full description: 150-word intro with keywords, timestamp chapter markers, about Ruth/Syntiq, links placeholder, 5 keyword tags]

## 🏷️ VIDEO TAGS
[30 tags for US YouTube SEO in web dev / AI tools niche]`,

    'shorts-script': `Write a VIRAL YouTube Shorts script for Ruth from Syntiq AI Agency. Ruth is warm, energetic, relatable — teaching web dev and AI to American beginners in under 60 seconds.

Topic: "${topic}"
Audience: ${aud}
Value: ${val}

## 🎬 SHORT CONCEPT
[One-line concept. Hook type. Why it'll get watch-through on Shorts.]

## ⚡ FULL SCRIPT (60 seconds max)
[Second-by-second — write EXACTLY what Ruth says and does:
0-3s: [RUTH ON CAMERA — explosive opening line. No hello, no intro.]
3-15s: [Setup — the problem or question]
15-40s: [The tip, trick, or insight — fast, visual, clear]
40-55s: [The "wow" payoff — the result or twist]
55-60s: [Quick CTA: "Follow for more!" or "Comment if this helped!"]

For each: exact words, visual direction, text overlay]

## 📱 TEXT OVERLAYS
[All on-screen text with timing — bold, minimal, impactful]

## 🎵 AUDIO DIRECTION
[Audio style: upbeat, trending, energetic. Suggested mood. No copyrighted songs.]

## 🔁 HOOK VARIATIONS (3)
[3 alternative opening lines to test for higher CTR]

## 📌 SHORTS TITLE + DESCRIPTION
[Clickable title (50 chars max) + 3-line description with hashtags]`,

    'channel-seo': `Create a COMPLETE YouTube SEO strategy for Ruth's channel at Syntiq AI Agency. Niche: web development + AI tools for American beginners.

Topic focus for this SEO audit: "${topic}"
Target audience: ${aud}

## 🔍 CHANNEL KEYWORD STRATEGY
[Primary keywords, secondary keywords, and long-tail keywords Ruth's channel should dominate. Include US monthly search volume estimates and competition level.]

## 🏆 TOP 20 VIDEO IDEAS (SEO-optimized)
[20 video titles Ruth should make — each with:
- Title (keyword-rich, under 60 chars)
- Target keyword
- Estimated US monthly searches
- Competition level: low/medium/high
- Why it will rank for beginners]

## 📋 VIDEO DESCRIPTION TEMPLATE
[A reusable SEO-optimized description template Ruth can fill in for every video. Include: first 150 chars hook, chapter markers placeholder, about section, links section, tags line]

## 🏷️ CHANNEL TAGS
[30 channel-level tags for maximum discoverability in the US web dev / AI niche]

## 📌 PLAYLISTS TO CREATE
[5 playlist names with descriptions — designed to increase session time and help YouTube understand the channel]

## 📈 GROWTH TACTICS
[5 specific actions Ruth can take RIGHT NOW to improve her YouTube SEO and get more US viewers — actionable, not generic]`,

    'channel-bio': `Write a COMPLETE YouTube channel About section for Ruth at Syntiq AI Agency. Ruth teaches web development and AI tools to American beginners.

Channel focus: "${topic}"
Audience: ${aud}

## 📺 CHANNEL NAME
[Best channel name options — should include Ruth's name + niche keywords for discoverability]

## 📝 CHANNEL DESCRIPTION (About section — 5000 chars max)
[Write the full About page:
Section 1: Who Ruth is (warm, human, relatable — not corporate)
Section 2: What the channel is about — the transformation you get
Section 3: Who it's for — describe the exact viewer
Section 4: What Ruth posts and how often
Section 5: Ruth's story / credibility — why trust her
Section 6: Syntiq AI Agency mention — what it is, what they offer
Section 7: Where to find Ruth on Instagram (@syntiq.ai)
Section 8: Contact / business inquiries
Keep the whole thing warm, conversational, and American in tone.]

## 🔗 CHANNEL LINKS (for the handle section)
[List of links Ruth should add: Instagram, website, email, etc. — with what label to use for each]

## 🎨 CHANNEL ART DIRECTION
[What the channel banner should show: colors, layout, text, Ruth's image direction, Syntiq logo placement]

## 📌 CHANNEL TRAILER SCRIPT (60 seconds)
[The channel trailer — first video a new visitor sees. Ruth introduces herself and the channel. Make it compelling enough that they hit subscribe before it ends.]`
  };

  return { label: `TUBE — ${topic.slice(0, 40)}`, content: typeMap[type] };
}

function setupTube() {
  // Type buttons are wired globally by setupTypeBtns() — nothing extra needed here
}

// ---- Tracker ----
function setupTracker() {
  $('btnTrackFollow').addEventListener('click', () => addTrackerEntry('follow'));
  $('btnTrackUnfollow').addEventListener('click', () => addTrackerEntry('unfollow'));
  $('btnClearTracker').addEventListener('click', () => {
    if (confirm('همه رو پاک کنم؟')) {
      state.tracker = [];
      saveTracker();
      renderTracker();
      showToast('تراکر پاک شد');
    }
  });
  $('btnExportTracker').addEventListener('click', exportTrackerCSV);
}

function addTrackerEntry(type) {
  const input = $('trackerUsername');
  const username = input.value.trim().replace(/^@/, '');
  if (!username) { showToast('یه یوزرنیم وارد کن', 'error'); return; }
  const entry = {
    username,
    type,
    time: new Date().toLocaleString('fa-IR', { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' }),
    id: Date.now(),
  };
  state.tracker.unshift(entry);
  saveTracker();
  renderTracker();
  input.value = '';
  showToast(type === 'follow' ? `@${username} فالو ثبت شد` : `@${username} انفالو ثبت شد`);
}

function saveTracker() {
  localStorage.setItem('syntiq_tracker', JSON.stringify(state.tracker));
}

function renderTracker() {
  const list = $('trackerList');
  const followed = state.tracker.filter(e => e.type === 'follow').length;
  const unfollowed = state.tracker.filter(e => e.type === 'unfollow').length;
  const pending = state.tracker.filter(e => e.type === 'follow' && !state.tracker.find(u => u.type === 'unfollow' && u.username === e.username)).length;

  $('trackerFollowCount').textContent = followed;
  $('trackerUnfollowCount').textContent = unfollowed;
  $('trackerPendingCount').textContent = pending;

  if (!state.tracker.length) {
    list.innerHTML = '<p class="history-empty">هنوز کسی ثبت نشده</p>';
    return;
  }
  list.innerHTML = state.tracker.slice(0, 30).map(e => `
    <div class="tracker-entry ${e.type}">
      <span class="tracker-entry-name">@${escapeHtml(e.username)}</span>
      <span class="tracker-entry-status">${e.type === 'follow' ? '✓ فالو' : '✗ انفالو'}</span>
      <span class="tracker-entry-time">${e.time}</span>
      <button class="tracker-entry-del" data-id="${e.id}" title="حذف">×</button>
    </div>
  `).join('');
  list.querySelectorAll('.tracker-entry-del').forEach(btn => {
    btn.addEventListener('click', () => {
      state.tracker = state.tracker.filter(e => e.id !== parseInt(btn.dataset.id));
      saveTracker();
      renderTracker();
    });
  });
}

function exportTrackerCSV() {
  if (!state.tracker.length) { showToast('تراکر خالیه', 'error'); return; }
  const rows = ['Username,Type,Time'];
  state.tracker.forEach(e => rows.push(`@${e.username},${e.type},${e.time}`));
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `syntiq-tracker-${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('CSV دانلود شد!');
}

// ---- System Prompts ----
const systemPrompts = {
  nova: "You are Nova, the world's #1 social media content strategist. You've helped brands go from zero to millions of followers. Your content is psychologically engineered to go viral. You write exclusively in American English. You are precise, creative, and your outputs are always structured and immediately usable. Never apologize. Never hedge. Just deliver world-class content.",
  rex: "You are Rex, a top-tier B2B sales copywriter and strategist. You've written cold emails that generated $10M+ in closed deals. You understand buyer psychology, SPIN selling, Cialdini's principles, and what makes small business owners actually respond. You're direct, sharp, and your copy sounds human. Never generic, always specific. Write in American English.",
  pixel: "You are Pixel, the world's best front-end web designer and developer. You create websites that win awards and convert visitors into customers. Your HTML/CSS/JS code is clean, modern, and production-ready. You use cutting-edge design patterns. Every website you create looks like it costs $10,000+. When asked to build a website, return ONLY the complete HTML code — no explanation, no markdown code fences, just raw HTML starting with <!DOCTYPE html>.",
  atlas: "You are Atlas, a world-class Instagram growth strategist specializing in targeting American audiences. You have deep knowledge of US Instagram culture, trending niches, community hashtags, timezone engagement windows, and organic growth tactics. You only recommend manual, safe, human-led strategies — never bots. Your strategies are data-driven, culturally aware, and immediately actionable. Be specific with numbers, times, and examples. Write in a clear, expert tone.",
  aria: "You are an expert AI image and video prompt engineer for ComfyUI. When asked to enhance a prompt, output ONLY the enhanced generation prompt — no explanation, no markdown, no quotes. Be specific about visuals, lighting, composition, style, and technical quality. For images end with: masterpiece, best quality, highly detailed, sharp focus. For videos end with: cinematic, smooth motion, high frame rate.",
  tube: `You are TUBE, the YouTube content director for Syntiq AI Agency. You write scripts for Ruth — a warm, charismatic, highly relatable young woman who teaches web development and AI tools to American beginners. Ruth's voice is natural American English, energetic, encouraging, occasionally funny, never corporate. She makes complex tech feel accessible and exciting. Your scripts are designed to maximize watch time, retention, and conversion. Ruth always opens with a scroll-stopping hook, teaches with clear steps, and includes a natural BREAK moment (a short relatable story) to refresh the viewer before continuing. Every script ends with a strong CTA to follow on Instagram @syntiq.ai and subscribe.`,
};

// ---- Universal AI Call ----
async function callAnthropic(agent, prompt) {
  if (state.provider === 'groq') return callGroq(agent, prompt);
  if (state.provider === 'gemini') return callGemini(agent, prompt);
  return callAnthropicDirect(agent, prompt);
}

// Call with a custom system prompt (used by ZEUS orchestrator)
async function callAnthropicWithSystem(system, userContent) {
  const prompt = { label: 'zeus', content: userContent };
  const fakeAgent = '_zeus_';
  const savedPrompts = systemPrompts;
  systemPrompts[fakeAgent] = system;
  try {
    return await callAnthropic(fakeAgent, prompt);
  } finally {
    delete systemPrompts[fakeAgent];
  }
}

async function callGroq(agent, prompt) {
  const response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${state.apiKey}`,
    },
    body: JSON.stringify({
      model: 'llama-3.3-70b-versatile',
      max_tokens: 8192,
      messages: [
        { role: 'system', content: systemPrompts[agent] },
        { role: 'user', content: prompt.content }
      ]
    })
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error?.message || `Groq error ${response.status}`);
  }
  const data = await response.json();
  return data.choices[0].message.content;
}

async function callGemini(agent, prompt) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${state.apiKey}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{
        parts: [{ text: `${systemPrompts[agent]}\n\n${prompt.content}` }]
      }],
      generationConfig: { maxOutputTokens: 8192 }
    })
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error?.message || `Gemini error ${response.status}`);
  }
  const data = await response.json();
  return data.candidates[0].content.parts[0].text;
}

async function callAnthropicDirect(agent, prompt) {
  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': state.apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-calls': 'true',
    },
    body: JSON.stringify({
      model: 'claude-opus-4-5',
      max_tokens: 8192,
      system: systemPrompts[agent],
      messages: [{ role: 'user', content: prompt.content }]
    })
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error?.message || `Anthropic error ${response.status}`);
  }
  const data = await response.json();
  return data.content[0].text;
}

// ---- Render Output ----
function renderOutput(agent, text) {
  if (agent === 'aria') {
    $('aria-result-body').innerHTML = `<div style="padding:16px;font-size:12px;color:var(--text-secondary);font-family:'JetBrains Mono',monospace;white-space:pre-wrap;line-height:1.6;">${escapeHtml(text)}</div>`;
    return;
  }
  const outputEl = $(`${agent}-output`);
  const isPixel = agent === 'pixel';

  // Nova: show preview panel after render
  if (agent === 'nova') {
    showNovaPreview(text);
  }

  if (isPixel && text.includes('<!DOCTYPE html>')) {
    // Clean: remove any markdown code fences if present
    let html = text.replace(/^```html\s*/i, '').replace(/^```\s*/i, '').replace(/```\s*$/i, '').trim();
    outputEl.innerHTML = `<div class="output-rendered pixel-output">
      <div style="margin-bottom:16px; padding:12px; background:rgba(6,182,212,0.06); border:1px solid rgba(6,182,212,0.2); border-radius:8px; font-family:'Inter',sans-serif; font-size:13px; color:#06b6d4;">
        ✅ Complete website generated! Click <strong>Download HTML</strong> to save and open in your browser.
      </div>
      <pre style="background:#050508;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:16px;overflow-x:auto;font-size:11px;line-height:1.6;color:#7dd3fc;white-space:pre-wrap;">${escapeHtml(html)}</pre>
    </div>`;
    state.lastOutputs[agent] = html;
    $('pixel-download').style.display = 'flex';
  } else {
    outputEl.innerHTML = `<div class="output-rendered ${agent}-output">${markdownToHtml(text)}</div>`;
    state.lastOutputs[agent] = text;
  }
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function markdownToHtml(md) {
  return md
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
    .replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>')
    .replace(/(#\w+)/g, '<span class="tag">$1</span>')
    .replace(/\n\n+/g, '</p><p>')
    .replace(/^(?!<[hul]|<\/[hul])(.+)$/gm, (m) => m.startsWith('<') ? m : m)
    .replace(/<p><\/p>/g, '');
}

// ---- History ----
function saveToHistory(agent, content, label) {
  const history = state.history[agent];
  history.unshift({ label: label || `Output ${Date.now()}`, content, time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) });
  if (history.length > 10) history.pop();
  localStorage.setItem(`syntiq_history_${agent}`, JSON.stringify(history));
  renderHistory(agent);
}

function renderAllHistories() {
  ['nova', 'rex', 'pixel', 'atlas', 'aria', 'tube'].forEach(renderHistory);
}

function renderHistory(agent) {
  const list = $(`${agent}-history-list`);
  const history = state.history[agent];
  if (!history.length) {
    list.innerHTML = '<p class="history-empty">No outputs yet</p>';
    return;
  }
  list.innerHTML = history.map((item, i) => `
    <div class="history-item" data-agent="${agent}" data-index="${i}">
      <span class="history-item-label">${escapeHtml(item.label)}</span>
      <span class="history-item-time">${item.time}</span>
    </div>
  `).join('');
  list.querySelectorAll('.history-item').forEach(el => {
    el.addEventListener('click', () => {
      const idx = parseInt(el.dataset.index);
      const item = state.history[agent][idx];
      renderOutput(agent, item.content);
      state.lastOutputs[agent] = item.content;
    });
  });
}

// ---- Copy Buttons ----
function setupCopyBtns() {
  ['nova', 'rex', 'pixel', 'atlas', 'tube'].forEach(agent => {
    $(`${agent}-copy`).addEventListener('click', () => {
      const text = state.lastOutputs[agent];
      if (!text) { showToast('Nothing to copy yet', 'error'); return; }
      navigator.clipboard.writeText(text).then(() => showToast('Copied to clipboard!')).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('Copied!');
      });
    });
  });
}

// ---- Clear Buttons ----
function setupClearBtns() {
  ['nova', 'rex', 'pixel', 'atlas', 'tube'].forEach(agent => {
    $(`${agent}-clear`).addEventListener('click', () => {
      $(`${agent}-output`).innerHTML = `<div class="output-placeholder">
        <div class="placeholder-icon ${agent}-placeholder-icon"></div>
        <p class="placeholder-text">Output cleared. Ready for the next generation.</p>
      </div>`;
      state.lastOutputs[agent] = '';
      if (agent === 'pixel') $('pixel-download').style.display = 'none';
      if (agent === 'nova') resetNovaPreview();
    });
  });
}

// ---- Pixel Download ----
function setupPixelDownload() {
  $('pixel-download').addEventListener('click', () => {
    const html = state.lastOutputs.pixel;
    if (!html) return;
    const business = $('pixel-business').value.trim().replace(/\s+/g, '-').toLowerCase() || 'website';
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${business}-website.html`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Website downloaded!');
  });
}

// ---- Loading ----
const thinkingMessages = {
  atlas: [
    'Mapping the American Instagram landscape...',
    'Analyzing US niche communities...',
    'Finding your ideal American targets...',
    'Calculating timezone engagement windows...',
    'Building your growth roadmap...',
    'Almost ready — this strategy is 🇺🇸 gold...',
  ],
  nova: [
    'Analyzing viral content patterns...',
    'Studying the Instagram algorithm...',
    'Crafting your perfect hook...',
    'Adding psychological triggers...',
    'Optimizing hashtag reach...',
    'Almost done — this one will stop thumbs...',
  ],
  rex: [
    'Researching prospect psychology...',
    'Loading persuasion principles...',
    'Crafting the perfect opening line...',
    'Engineering your CTA...',
    'Adding the human touch...',
    'Almost ready — this will get replies...',
  ],
  pixel: [
    'Analyzing design trends...',
    'Architecting the layout...',
    'Writing clean, fast CSS...',
    'Adding smooth animations...',
    'Optimizing for conversions...',
    'Building something breathtaking...',
  ],
  aria: [
    'Enhancing your creative brief...',
    'Building ComfyUI workflow...',
    'Sending to GPU...',
    'Rendering in progress...',
    'Almost there...',
  ],
  tube: [
    'Studying the YouTube algorithm...',
    "Crafting Ruth's opening hook...",
    'Writing the BREAK story moment...',
    'Building watch-time retention structure...',
    'Adding SEO and CTA layers...',
    'Almost ready — this one will go viral...',
  ],
};

const agentEmojis = { nova: '⭐', rex: '⚡', pixel: '🎨', atlas: '🌎', aria: '🔮', tube: '📺' };

let thinkingInterval = null;

function showLoading(agent) {
  $('loadingOverlay').classList.add('active');
  $('loadingAgentName').textContent = agent.toUpperCase();
  $('loadingAgentIcon').textContent = agentEmojis[agent];

  // Apply agent color to rings
  const rings = document.querySelectorAll('.spinner-ring');
  const colors = { nova: '#f472b6', rex: '#f59e0b', pixel: '#06b6d4', atlas: '#10b981', aria: '#818cf8', tube: '#f43f5e' };
  rings[1].style.borderTopColor = colors[agent];
  rings[2].style.borderTopColor = `${colors[agent]}80`;

  const msgs = thinkingMessages[agent];
  let i = 0;
  $('thinkingMsg').textContent = msgs[0];

  thinkingInterval = setInterval(() => {
    i = (i + 1) % msgs.length;
    $('thinkingMsg').textContent = msgs[i];
  }, 2500);
}

function hideLoading() {
  $('loadingOverlay').classList.remove('active');
  if (thinkingInterval) { clearInterval(thinkingInterval); thinkingInterval = null; }
}

// ================================================================
//  ZEUS — Mission Orchestrator
// ================================================================

const zeusState = {
  queue: [],    // { id, agent, label, type, content, status:'loading'|'pending'|'approved'|'rejected' }
  running: false,
  nextId: 1,
};

function setupMission() {
  $('btnLaunchMission').addEventListener('click', launchMission);
  $('missionInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) launchMission();
  });
  $('btnApproveAll').addEventListener('click', approveAll);
  $('btnClearMission').addEventListener('click', clearMission);

  // Example chips
  document.querySelectorAll('.mission-example-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      $('missionInput').value = chip.dataset.example;
      $('missionInput').focus();
    });
  });

  // Quick Pack buttons
  $('btnLaunchRuthPack').addEventListener('click', () => {
    const topic = $('ruthPackTopic').value.trim();
    if (!topic) { $('ruthPackTopic').focus(); showToast('Enter a topic first', 'error'); return; }
    launchQuickPack('ruth', { topic });
  });
  $('ruthPackTopic').addEventListener('keydown', e => { if (e.key === 'Enter') $('btnLaunchRuthPack').click(); });

  $('btnLaunchSalesPack').addEventListener('click', () => {
    const brand = $('salesPackBrand').value.trim() || 'Syntiq';
    const service = $('salesPackService').value.trim();
    if (!service) { $('salesPackService').focus(); showToast('Enter what you are selling', 'error'); return; }
    launchQuickPack('sales', { brand, service });
  });

  $('btnLaunchGrowthPack').addEventListener('click', () => {
    const niche = $('growthPackNiche').value.trim() || 'Web Dev & AI Tools';
    launchQuickPack('growth', { niche });
  });
  $('growthPackNiche').addEventListener('keydown', e => { if (e.key === 'Enter') $('btnLaunchGrowthPack').click(); });
}

// ================================================================
//  QUICK PACKS — deterministic task builders (no AI parsing needed)
// ================================================================

async function launchQuickPack(packType, params) {
  if (!state.apiKey) { $('apiPanel').classList.add('open'); showToast('Add API key first', 'error'); return; }
  if (zeusState.running) { showToast('A mission is already running', 'error'); return; }

  const tasks = packType === 'ruth'
    ? buildRuthPackTasks(params.topic)
    : packType === 'sales'
    ? buildSalesPackTasks(params.brand, params.service)
    : buildGrowthPackTasks(params.niche);

  // Switch to mission tab for visibility
  switchAgent('mission');

  zeusState.running = true;
  zeusState.queue = [];
  zeusState.nextId = 1;

  const packNames = { ruth: '🎬 Ruth Content Pack', sales: '🚀 Full Sales Launch', growth: '📈 Growth Sprint' };
  missionSetProgress(5, `${packNames[packType]} — launching ${tasks.length} agents...`);
  $('missionProgressCard').style.display = 'block';
  $('missionQueueZone').style.display = 'block';
  $('missionDoneZone').style.display = 'none';

  // Disable all pack launch buttons during run
  ['btnLaunchRuthPack', 'btnLaunchSalesPack', 'btnLaunchGrowthPack', 'btnLaunchMission'].forEach(id => {
    const el = $(id); if (el) { el.disabled = true; }
  });

  try {
    // Add all as loading cards
    tasks.forEach(task => {
      const id = zeusState.nextId++;
      zeusState.queue.push({ id, ...task, content: '', status: 'loading' });
    });
    renderMissionQueue();
    updateMissionStats();

    // Execute each task
    for (let i = 0; i < zeusState.queue.length; i++) {
      const item = zeusState.queue[i];
      const pct = 10 + Math.round(((i + 1) / zeusState.queue.length) * 85);
      missionSetProgress(pct, `${agentEmojis[item.agent] || '⚡'} ${item.agent.toUpperCase()} — ${item.label}...`);

      try {
        item.content = await executeTask(item);
        item.status = 'pending';
      } catch (e) {
        item.content = `Error: ${e.message}`;
        item.status = 'pending';
      }
      renderMissionQueue();
      updateMissionStats();
      await new Promise(r => setTimeout(r, 250));
    }

    missionSetProgress(100, `${packNames[packType]} complete ✅ — review and approve below`);
    showToast(`${packNames[packType]} done! Review the queue.`);
    setTimeout(() => { $('missionProgressCard').style.display = 'none'; }, 3000);

  } catch (err) {
    missionSetProgress(0, 'Pack failed: ' + err.message);
    showToast(err.message, 'error');
  } finally {
    zeusState.running = false;
    ['btnLaunchRuthPack', 'btnLaunchSalesPack', 'btnLaunchGrowthPack', 'btnLaunchMission'].forEach(id => {
      const el = $(id); if (el) el.disabled = false;
    });
    updateMissionStats();
  }
}

function buildRuthPackTasks(topic) {
  return [
    { agent: 'atlas', label: '🇺🇸 US Trends — ' + topic.slice(0, 35), type: 'us-trends',       params: { niche: 'Web Dev & AI Tools', audience: 'US beginners 20–35', location: 'United States', style: 'educational' } },
    { agent: 'atlas', label: '🎣 Hook Formulas for Ruth',               type: 'hook-formulas',   params: { niche: 'Web Dev & AI Tools', audience: 'American beginners', location: 'United States', style: 'relatable, warm' } },
    { agent: 'nova',  label: '📱 Ruth Reel — ' + topic.slice(0, 35),   type: 'ruth-reel',       params: { business: 'Syntiq AI Agency', industry: 'AI & Web Dev Education', audience: 'American beginners 20–35', topic, tone: 'educational' } },
    { agent: 'nova',  label: '📲 Ruth Story — ' + topic.slice(0, 35),  type: 'ruth-story',      params: { business: 'Syntiq AI Agency', industry: 'AI & Web Dev Education', audience: 'American beginners 20–35', topic, tone: 'casual-fun' } },
    { agent: 'tube',  label: '🎬 YouTube Script — ' + topic.slice(0, 35), type: 'long-form',    params: { topic, audience: 'American beginners who want to learn web dev and AI', value: 'you can build a professional site or automate tasks without coding experience' } },
    { agent: 'tube',  label: '⚡ YouTube Shorts — ' + topic.slice(0, 35), type: 'shorts-script', params: { topic, audience: 'American beginners 20–35', value: 'quick actionable tip' } },
    { agent: 'atlas', label: '🏷️ Hashtag Strategy — ' + topic.slice(0, 35), type: 'hashtag-strategy', params: { niche: 'Web Dev & AI Tools', audience: 'US beginners', location: 'United States', style: 'educational, tech' } },
  ];
}

function buildSalesPackTasks(brand, service) {
  return [
    { agent: 'nova',  label: `📸 Instagram Caption — ${brand}`,    type: 'instagram-caption', params: { business: brand, industry: 'Business', audience: 'US professionals', topic: service, tone: 'bold-edgy' } },
    { agent: 'nova',  label: `🎬 Reel Script — ${brand}`,          type: 'reel-script',       params: { business: brand, industry: 'Business', audience: 'US professionals', topic: service, tone: 'bold-edgy' } },
    { agent: 'rex',   label: `📧 Cold Email — ${brand}`,           type: 'cold-email',        params: { business: brand, service, prospect: 'Small business owners', painpoint: 'Wasting time on tasks that could be automated', offer: 'Free 30-min strategy call' } },
    { agent: 'atlas', label: `🏷️ Hashtag Strategy — ${brand}`,    type: 'hashtag-strategy',  params: { niche: service, audience: 'US business owners', location: 'United States', style: 'professional' } },
    { agent: 'pixel', label: `🌐 Landing Page — ${brand}`,         type: 'website',           params: { business: brand, industry: service, style: 'modern-dark', services: service } },
  ];
}

function buildGrowthPackTasks(niche) {
  return [
    { agent: 'atlas', label: `🇺🇸 US Trends — ${niche}`,           type: 'us-trends',         params: { niche, audience: 'US audience', location: 'United States', style: 'professional' } },
    { agent: 'atlas', label: `🎣 Hook Formulas — ${niche}`,         type: 'hook-formulas',     params: { niche, audience: 'US audience', location: 'United States', style: 'professional' } },
    { agent: 'atlas', label: `🏷️ Hashtag Strategy — ${niche}`,    type: 'hashtag-strategy',  params: { niche, audience: 'US audience', location: 'United States', style: 'professional' } },
    { agent: 'atlas', label: `📅 30-Day Growth Schedule — ${niche}`, type: 'growth-schedule', params: { niche, audience: 'US audience', location: 'United States', style: 'professional' } },
  ];
}

async function launchMission() {
  const mission = $('missionInput').value.trim();
  if (!mission) { showToast('Write your mission first', 'error'); return; }
  if (!state.apiKey) { $('apiPanel').classList.add('open'); showToast('Add API key first', 'error'); return; }
  if (zeusState.running) return;

  zeusState.running = true;
  zeusState.queue = [];
  zeusState.nextId = 1;
  renderMissionQueue();

  const btn = $('btnLaunchMission');
  btn.disabled = true;
  btn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="animation:spin .7s linear infinite"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Planning...`;

  missionSetProgress(5, 'ZEUS is planning your mission...');
  $('missionProgressCard').style.display = 'block';
  $('missionQueueZone').style.display = 'block';
  $('missionDoneZone').style.display = 'none';

  try {
    // Step 1: parse mission into tasks
    missionSetProgress(10, 'Analyzing mission...');
    const tasks = await parseMissionToTasks(mission);
    if (!tasks.length) throw new Error('Could not parse mission into tasks');

    missionSetProgress(20, `${tasks.length} tasks planned — agents launching...`);
    updateMissionStats();

    // Step 2: add all as loading cards immediately
    tasks.forEach(task => {
      const id = zeusState.nextId++;
      zeusState.queue.push({ id, ...task, content: '', status: 'loading' });
    });
    renderMissionQueue();

    // Step 3: execute each task sequentially
    for (let i = 0; i < zeusState.queue.length; i++) {
      const item = zeusState.queue[i];
      const pct = 20 + Math.round(((i + 1) / zeusState.queue.length) * 75);
      missionSetProgress(pct, `${agentEmojis[item.agent] || '⚡'} ${item.agent.toUpperCase()} — ${item.label}...`);

      try {
        const result = await executeTask(item);
        item.content = result;
        item.status = 'pending';
      } catch (e) {
        item.content = `Error: ${e.message}`;
        item.status = 'pending';
      }
      renderMissionQueue();
      updateMissionStats();
      await new Promise(r => setTimeout(r, 300));
    }

    missionSetProgress(100, 'All tasks complete — review and approve below ✅');
    showToast('Mission complete! Review the queue below.');
    setTimeout(() => { $('missionProgressCard').style.display = 'none'; }, 3000);

  } catch (err) {
    missionSetProgress(0, 'Mission failed: ' + err.message);
    showToast(err.message, 'error');
  } finally {
    zeusState.running = false;
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Launch Mission`;
    updateMissionStats();
  }
}

// ---- ZEUS: Parse mission into tasks via AI ----
async function parseMissionToTasks(mission) {
  const systemPrompt = `You are ZEUS, mission orchestrator for Syntiq AI Agency.
Parse the user's mission into 3-6 specific tasks for these agents: nova, rex, pixel, atlas, tube.
Return ONLY a valid JSON array. No markdown, no explanation.

Agent capabilities:
- nova: instagram-caption, youtube-script, reel-script, content-strategy, ruth-reel, ruth-story, ruth-bio
- rex: cold-email, email-sequence, linkedin-dm
- pixel: website (landing page HTML)
- atlas: hashtag-strategy, follow-targets, engagement-templates, growth-schedule, us-trends, hook-formulas
- tube: long-form, shorts-script, channel-seo, channel-bio

JSON format per task:
{"agent":"nova","label":"Instagram Caption — Product Launch","type":"instagram-caption","params":{"business":"BrandName","industry":"niche","audience":"target audience","topic":"specific topic","tone":"casual-fun|inspirational|educational|luxury|bold-edgy"}}
{"agent":"rex","label":"Cold Email — SaaS Outreach","type":"cold-email","params":{"business":"BrandName","service":"what you sell","prospect":"prospect type","painpoint":"their pain","offer":"your offer"}}
{"agent":"atlas","label":"Hashtag Strategy","type":"hashtag-strategy","params":{"niche":"industry","audience":"target","location":"city or country","style":"professional"}}
{"agent":"pixel","label":"Landing Page","type":"website","params":{"business":"BrandName","industry":"niche","style":"modern-dark","services":"service1, service2"}}
{"agent":"tube","label":"YouTube Long-form Script","type":"long-form","params":{"topic":"video topic","audience":"target audience","value":"core value prop"}}

Return 3-6 tasks as a JSON array.`;

  const prompt = { label: 'zeus-parse', content: `Mission: "${mission}"` };

  let raw = '';
  try {
    raw = await callAnthropicWithSystem(systemPrompt, prompt.content);
    // Extract JSON array from response
    const match = raw.match(/\[[\s\S]*\]/);
    if (!match) throw new Error('No JSON array found');
    return JSON.parse(match[0]);
  } catch (e) {
    // Fallback: create sensible default tasks from mission
    return buildFallbackTasks(mission);
  }
}

function buildFallbackTasks(mission) {
  const lower = mission.toLowerCase();
  const tasks = [];
  const brand = extractBrandFromMission(mission);

  if (lower.includes('instagram') || lower.includes('social') || lower.includes('caption') || lower.includes('content')) {
    tasks.push({ agent: 'nova', label: 'Instagram Caption #1', type: 'instagram-caption', params: { business: brand, industry: 'Business', audience: 'US professionals', topic: mission.slice(0, 80), tone: 'bold-edgy' } });
    tasks.push({ agent: 'nova', label: 'Instagram Caption #2', type: 'instagram-caption', params: { business: brand, industry: 'Business', audience: 'US professionals', topic: 'Building with AI in 2025', tone: 'inspirational' } });
  }
  if (lower.includes('hashtag') || lower.includes('instagram') || lower.includes('social')) {
    tasks.push({ agent: 'atlas', label: 'Hashtag Strategy', type: 'hashtag-strategy', params: { niche: 'AI & Technology', audience: 'US entrepreneurs', location: 'United States', style: 'professional' } });
  }
  if (lower.includes('email') || lower.includes('outreach') || lower.includes('sales')) {
    tasks.push({ agent: 'rex', label: 'Cold Email Outreach', type: 'cold-email', params: { business: brand, service: 'AI services', prospect: 'Small business owners', painpoint: 'Wasting time on repetitive tasks', offer: 'Free AI strategy call' } });
  }
  if (lower.includes('youtube') || lower.includes('video') || lower.includes('script') || lower.includes('tube')) {
    tasks.push({ agent: 'tube', label: 'YouTube Script — ' + mission.slice(0, 40), type: 'long-form', params: { topic: mission.slice(0, 80), audience: 'American beginners learning web dev and AI', value: 'actionable skills you can use today' } });
  }
  if (lower.includes('trend') || lower.includes('viral') || lower.includes('hook')) {
    tasks.push({ agent: 'atlas', label: 'US Trends Research', type: 'us-trends', params: { niche: 'Web Dev & AI Tools', audience: 'US tech enthusiasts', location: 'United States', style: 'educational' } });
  }
  if (!tasks.length) {
    tasks.push(
      { agent: 'nova', label: 'Instagram Caption', type: 'instagram-caption', params: { business: brand, industry: 'AI Agency', audience: 'US startup founders', topic: mission.slice(0, 80), tone: 'bold-edgy' } },
      { agent: 'atlas', label: 'Hashtag Strategy', type: 'hashtag-strategy', params: { niche: 'AI Agency', audience: 'US entrepreneurs', location: 'United States', style: 'professional' } }
    );
  }
  return tasks;
}

function extractBrandFromMission(mission) {
  const m = mission.match(/for\s+([A-Z][a-zA-Z]+)/);
  return m ? m[1] : 'Syntiq';
}

// ---- Execute a single task ----
async function executeTask(item) {
  const { agent, type, params } = item;
  let promptObj;

  if (agent === 'nova') {
    // Temporarily set nova state
    const saved = state.selectedTypes.nova;
    state.selectedTypes.nova = type;
    promptObj = buildNovaPromptFromParams(params, type);
    state.selectedTypes.nova = saved;
  } else if (agent === 'rex') {
    promptObj = buildRexPromptFromParams(params, type);
  } else if (agent === 'atlas') {
    promptObj = buildAtlasPromptFromParams(params, type);
  } else if (agent === 'pixel') {
    promptObj = buildPixelPromptFromParams(params, type);
  } else if (agent === 'tube') {
    promptObj = buildTubePromptFromParams(params, type);
  } else {
    throw new Error('Unknown agent: ' + agent);
  }

  return await callAnthropic(agent, promptObj);
}

// Prompt builders that take params objects (bypass DOM)
function buildNovaPromptFromParams(p, type) {
  const business = p.business || 'Syntiq';
  const industry = p.industry || 'AI Agency';
  const audience = p.audience || 'US professionals';
  const topic = p.topic || 'Our services';
  const tone = p.tone || 'bold-edgy';

  if (type === 'ruth-reel') {
    return {
      label: `Ruth Reel — ${topic.slice(0, 40)}`,
      content: `Write a VIRAL Instagram Reel script for Ruth from Syntiq AI Agency (@syntiq.ai). Ruth is a warm, charismatic young American woman teaching web dev and AI to beginners.
Topic: "${topic}". Audience: ${audience}.
Include: second-by-second script (0-60s), exact words Ruth says, text overlays, audio direction, caption + 20 hashtags.
Ruth's voice: natural American English, energetic, encouraging, occasionally funny — never corporate.`
    };
  }

  if (type === 'ruth-story') {
    return {
      label: `Ruth Story — ${topic.slice(0, 40)}`,
      content: `Write 5 connected Instagram Story slides for Ruth from Syntiq AI Agency (@syntiq.ai) on the topic: "${topic}". Audience: ${audience}.
Ruth is warm, casual, relatable — like a smart friend teaching something cool. Each slide: what Ruth says/shows, text overlay, visual direction.
Slides: Hook → Setup → Tip → Deeper insight → CTA (follow @syntiq.ai)`
    };
  }

  if (type === 'ruth-bio') {
    return {
      label: 'Ruth Instagram Bio @syntiq.ai',
      content: `Write a complete, high-converting Instagram bio for Ruth at Syntiq AI Agency. Handle: @syntiq.ai.
Ruth teaches web development and AI tools to American beginners. Include: display name (keyword-rich), bio (5 lines max, 150 chars), link strategy, 5 story highlight categories, profile photo direction, 3 pinned post ideas.`
    };
  }

  const content = `Write a world-class Instagram caption for "${business}" in the ${industry} industry.
Topic: "${topic}". Target audience: ${audience}. Tone: ${tone}.

## 📸 INSTAGRAM CAPTION
[3-5 sentences with powerful hook, storytelling, and CTA]

## 🏷️ HASHTAGS
[25 hashtags: mix of mega, large, medium, and niche]

## ⏰ BEST TIME TO POST
[Best day and time for US audience]

## 💡 CONTENT TIPS
[3 bullet points for visual direction and engagement]`;

  return { label: `${business} — ${type}`, content };
}

function buildRexPromptFromParams(p, type) {
  const business = p.business || 'Syntiq';
  const service = p.service || 'AI services';
  const prospect = p.prospect || 'business owners';
  const painpoint = p.painpoint || 'wasting time';
  const offer = p.offer || 'free strategy call';

  const content = type === 'email-sequence'
    ? `Write a 5-email cold outreach sequence for "${business}" selling "${service}" to ${prospect}. Pain point: ${painpoint}. Offer: ${offer}. Each email: subject line + body. Emails: Intro, Value, Social Proof, Urgency, Breakup.`
    : `Write a high-converting cold email for "${business}" selling "${service}" to ${prospect}. Pain: ${painpoint}. Offer: ${offer}.

## 📧 SUBJECT LINE (3 options)
## 📝 EMAIL BODY
[Personalized opening, pain identification, solution, proof, CTA]
## 📨 FOLLOW-UP (3 days later)`;

  return { label: `${business} — ${type}`, content };
}

function buildAtlasPromptFromParams(p, type) {
  const niche = p.niche || 'AI Agency';
  const audience = p.audience || 'US entrepreneurs';
  const location = p.location || 'United States';
  const style = p.style || 'professional';

  if (type === 'us-trends') {
    return {
      label: `US Trends — ${niche}`,
      content: `You are Atlas. Research the HOTTEST current web development and AI tools trends in the United States for content creators. Niche: ${niche}. Audience: ${audience}.
Report: Top 10 trending topics (5 web dev + 5 AI tools) with viral content angles, trending content formats, content gaps/opportunities, and trend forecast for the next 30 days. Be specific and data-aware.`
    };
  }

  if (type === 'hook-formulas') {
    return {
      label: `Hook Formulas — ${niche}`,
      content: `You are Atlas. Reveal the BEST hook formulas for web development and AI content targeting American audiences. Niche: ${niche}. Audience: ${audience}.
Give 15 hook formulas with: name, template, 3 fill-in examples, psychology behind it, best platform (Reel/Shorts/Long-form). Include sections for curiosity gap, transformation, counter-intuitive, proof, FOMO, simplification, and list hooks. Also: Ruth voice adaptation tips.`
    };
  }

  if (type === 'growth-schedule') {
    return {
      label: `30-Day Growth Schedule — ${niche}`,
      content: `You are Atlas. Build a complete 30-day Instagram growth schedule for a ${niche} account targeting ${audience} in ${location}. Style: ${style}.
Include: Week 1-4 daily actions (posts, follows, comments — with specific numbers), safe daily limits, 30-day targets, US cultural content calendar.`
    };
  }

  const content = `You are Atlas. Create a ${type.replace(/-/g, ' ')} for a ${niche} Instagram account targeting ${audience} in ${location}. Style: ${style}.

## 🎯 STRATEGY OVERVIEW
## 📊 HASHTAG SETS (3 rotating sets of 25 hashtags each)
## 📅 POSTING SCHEDULE
## 💡 KEY INSIGHTS FOR US AUDIENCE`;

  return { label: `${niche} — ${type}`, content };
}

function buildTubePromptFromParams(p, type) {
  const topic = p.topic || 'How to build your first website with AI';
  const audience = p.audience || 'American beginners aged 20–35';
  const value = p.value || 'you can build a professional website without any coding experience';

  const contentMap = {
    'long-form': `Write a complete YouTube long-form script for Ruth at Syntiq AI Agency. Ruth is a warm, charismatic American woman teaching web dev and AI to beginners.
Topic: "${topic}". Audience: ${audience}. Value: ${value}.
Include: hook (first 30s), intro, 4-5 main sections with timestamps, BREAK story segment (mid-video relatable story), big payoff, CTA to follow @syntiq.ai and subscribe.`,
    'shorts-script': `Write a 60-second YouTube Shorts script for Ruth from Syntiq AI Agency on the topic: "${topic}". Audience: ${audience}. Ruth is warm, energetic, relatable. Include second-by-second breakdown, text overlays, and a hook + CTA.`,
    'channel-seo': `Create a YouTube SEO strategy for Ruth's Syntiq AI Agency channel focused on "${topic}" for ${audience}. Include: top 20 video ideas with keywords, description template, channel tags, playlist structure.`,
    'channel-bio': `Write a complete YouTube channel About section for Ruth at Syntiq AI Agency. Focus: "${topic}" for ${audience}. Include: channel description, link list, channel art direction, and channel trailer script.`,
  };

  const content = contentMap[type] || contentMap['long-form'];
  return { label: `TUBE — ${topic.slice(0, 40)}`, content };
}

function buildPixelPromptFromParams(p, type) {
  const business = p.business || 'Syntiq';
  const industry = p.industry || 'AI Agency';
  const style = p.style || 'modern-dark';
  const services = p.services || 'AI consulting, Automation, Strategy';

  const content = `Build a complete, stunning one-page landing website for "${business}" — a ${industry} company. Style: ${style}. Services: ${services}. Make it look like a $10,000 website. Return ONLY the complete HTML.`;
  return { label: `${business} — Landing Page`, content };
}

// ---- Queue Rendering ----
function renderMissionQueue() {
  const list = $('missionQueueList');
  const doneList = $('missionDoneList');
  const pending = zeusState.queue.filter(i => i.status !== 'approved' && i.status !== 'rejected');
  const done = zeusState.queue.filter(i => i.status === 'approved');

  list.innerHTML = pending.map(item => renderQueueCard(item)).join('');
  doneList.innerHTML = done.map(item => renderDoneCard(item)).join('');
  $('missionQueueZone').style.display = zeusState.queue.length ? 'block' : 'none';
  $('missionDoneZone').style.display = done.length ? 'block' : 'none';

  // Attach handlers
  pending.forEach(item => {
    const card = document.querySelector(`[data-queue-id="${item.id}"]`);
    if (!card) return;
    card.querySelector('.queue-card-header').addEventListener('click', () => {
      card.querySelector('.queue-card-body').classList.toggle('open');
    });
    if (item.status === 'pending') {
      card.querySelector('.btn-q-approve')?.addEventListener('click', e => { e.stopPropagation(); approveItem(item.id); });
      card.querySelector('.btn-q-reject')?.addEventListener('click', e => { e.stopPropagation(); rejectItem(item.id); });
      card.querySelector('.btn-q-copy')?.addEventListener('click', e => { e.stopPropagation(); navigator.clipboard.writeText(item.content).then(() => showToast('Copied!')); });
    }
  });
  done.forEach(item => {
    document.querySelector(`[data-done-id="${item.id}"]`)?.addEventListener('click', () => {
      navigator.clipboard.writeText(item.content).then(() => showToast('Copied!'));
    });
  });
}

const agentColors = { nova: '#f472b6', rex: '#f59e0b', pixel: '#06b6d4', atlas: '#10b981', aria: '#818cf8', tube: '#f43f5e' };

function renderQueueCard(item) {
  const color = agentColors[item.agent] || '#888';
  const isLoading = item.status === 'loading';
  const preview = item.content ? item.content.slice(0, 120).replace(/\n/g, ' ') + '...' : '';

  const statusHtml = isLoading
    ? `<span class="queue-card-status loading"><span class="queue-loading-spin"></span>Running...</span>`
    : `<span class="queue-card-status ${item.status}">${item.status === 'pending' ? '⏳ Pending' : item.status === 'approved' ? '✅ Approved' : '❌ Rejected'}</span>`;

  const actionsHtml = item.status === 'pending' ? `
    <div class="queue-card-actions">
      <button class="btn-q-approve">✅ Approve</button>
      <button class="btn-q-copy">Copy</button>
      <button class="btn-q-reject">❌ Reject</button>
    </div>` : '';

  return `
    <div class="queue-card ${item.status}" data-queue-id="${item.id}">
      <div class="queue-card-header">
        <div class="queue-card-left">
          <div class="queue-card-agent-dot" style="background:${color}"></div>
          <div>
            <div class="queue-card-label">${escapeHtml(item.label)}</div>
            <div class="queue-card-type">${item.agent.toUpperCase()} · ${item.type}</div>
          </div>
        </div>
        ${statusHtml}
      </div>
      ${!isLoading && item.content ? `
      <div class="queue-card-body">
        <div class="queue-card-preview">${escapeHtml(preview)}<br><br>${escapeHtml(item.content)}</div>
        ${actionsHtml}
      </div>` : ''}
    </div>`;
}

function renderDoneCard(item) {
  const color = agentColors[item.agent] || '#888';
  const preview = item.content.slice(0, 60).replace(/\n/g, ' ');
  return `
    <div class="done-card">
      <div class="done-card-left">
        <div class="queue-card-agent-dot" style="background:${color}"></div>
        <div>
          <div class="done-card-label">${escapeHtml(item.label)}</div>
          <div class="done-card-preview">${escapeHtml(preview)}...</div>
        </div>
      </div>
      <button class="btn-done-copy" data-done-id="${item.id}">Copy</button>
    </div>`;
}

function approveItem(id) {
  const item = zeusState.queue.find(i => i.id === id);
  if (item) item.status = 'approved';
  renderMissionQueue();
  updateMissionStats();
  showToast('Approved ✅');
}

function rejectItem(id) {
  const item = zeusState.queue.find(i => i.id === id);
  if (item) item.status = 'rejected';
  renderMissionQueue();
  updateMissionStats();
}

function approveAll() {
  zeusState.queue.filter(i => i.status === 'pending').forEach(i => i.status = 'approved');
  renderMissionQueue();
  updateMissionStats();
  showToast('All approved ✅');
}

function clearMission() {
  zeusState.queue = [];
  renderMissionQueue();
  updateMissionStats();
  $('missionQueueZone').style.display = 'none';
  $('missionDoneZone').style.display = 'none';
  $('missionProgressCard').style.display = 'none';
}

function updateMissionStats() {
  const pending = zeusState.queue.filter(i => i.status === 'pending').length;
  const approved = zeusState.queue.filter(i => i.status === 'approved').length;
  $('missionStatPending').textContent = pending;
  $('missionStatDone').textContent = approved;
  $('missionStatTotal').textContent = zeusState.queue.length;
}

function missionSetProgress(pct, label) {
  $('missionProgressFill').style.width = pct + '%';
  $('missionProgressPct').textContent = pct + '%';
  $('missionProgressLabel').textContent = label;
}

// ================================================================
//  ARIA — Adaptive Rendering & Imaging Agent (ComfyUI integration)
// ================================================================

function setupAria() {
  // Restore endpoint
  $('ariaEndpoint').value = state.aria.endpoint;

  // Mode tabs
  document.querySelectorAll('.aria-mode-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.aria-mode-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.aria.mode = btn.dataset.ariaMode;
      $('aria-image-settings').style.display = state.aria.mode !== 'video' ? 'flex' : 'none';
      $('aria-video-settings').style.display = state.aria.mode === 'video' ? 'flex' : 'none';
      $('aria-image-settings').style.flexDirection = 'column';
      $('aria-output-type').textContent = state.aria.mode === 'image' ? 'Image' : state.aria.mode === 'video' ? 'WAN Video' : 'Poster';
      $('ariaStatMode').textContent = state.aria.mode.charAt(0).toUpperCase() + state.aria.mode.slice(1);
    });
  });

  // Endpoint change
  $('ariaEndpoint').addEventListener('change', () => {
    state.aria.endpoint = $('ariaEndpoint').value.trim().replace(/\/$/, '');
    localStorage.setItem('syntiq_aria_endpoint', state.aria.endpoint);
    checkComfyUI();
  });

  // Refresh button
  $('ariaRefreshBtn').addEventListener('click', checkComfyUI);

  // Enhance toggle
  $('ariaEnhanceToggle').addEventListener('click', () => {
    state.aria.enhanceEnabled = !state.aria.enhanceEnabled;
    $('ariaEnhanceToggle').classList.toggle('on', state.aria.enhanceEnabled);
  });

  // Clear button
  $('aria-clear').addEventListener('click', () => {
    $('aria-result-body').innerHTML = `
      <div class="aria-placeholder" id="ariaPlaceholder">
        <div class="aria-placeholder-icon">🎨</div>
        <p class="aria-placeholder-text">ARIA connects to your local ComfyUI<br>and generates images & WAN videos on your GPU.</p>
        <span class="aria-placeholder-tip">Make sure ComfyUI is running at localhost:8188</span>
      </div>`;
    $('aria-download').style.display = 'none';
    $('aria-send-nova').style.display = 'none';
    $('ariaLog').classList.remove('visible');
    $('ariaLog').innerHTML = '';
    $('ariaProgressWrap').style.display = 'none';
    $('igPackageCard').style.display = 'none';
    state.aria.lastImageUrl = null;
    state.aria.generatedFrames = [];
    state.aria.igCaption = '';
    state.aria.igHashtags = '';
  });

  // Download button
  $('aria-download').addEventListener('click', () => {
    if (!state.aria.lastImageUrl) return;
    const a = document.createElement('a');
    a.href = state.aria.lastImageUrl;
    a.download = state.aria.lastFilename || 'syntiq_aria.png';
    a.click();
  });

  // Build Instagram Post button
  $('aria-send-nova').addEventListener('click', () => {
    if (!state.aria.lastImageUrl) return;
    buildAriaInstagramPost();
  });

  // Initial connection check
  checkComfyUI();
}

// ---- ComfyUI Connection ----
async function checkComfyUI() {
  const dot = $('ariaComfyDot');
  const status = $('ariaComfyStatus');
  const pill = $('ariaStatusPill');
  dot.className = 'comfy-dot checking';
  status.textContent = 'Checking connection...';

  try {
    const res = await fetch(`${state.aria.endpoint}/system_stats`, { signal: AbortSignal.timeout(4000) });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    state.aria.comfyOnline = true;
    dot.className = 'comfy-dot online';
    const gpu = data.devices?.[0]?.name || 'GPU';
    status.textContent = `Connected — ${gpu}`;
    pill.textContent = '● Online';
    pill.style.color = '#22c55e';
    pill.style.borderColor = 'rgba(34,197,94,0.3)';
    pill.style.background = 'rgba(34,197,94,0.08)';
    await fetchComfyModels();
  } catch {
    state.aria.comfyOnline = false;
    dot.className = 'comfy-dot offline';
    status.textContent = 'ComfyUI not reachable — start it first';
    pill.textContent = '● Offline';
    pill.style.color = '#ef4444';
    pill.style.borderColor = 'rgba(239,68,68,0.3)';
    pill.style.background = 'rgba(239,68,68,0.08)';
  }
}

async function fetchComfyModels() {
  try {
    // Fetch checkpoints for image mode
    const ckptRes = await fetch(`${state.aria.endpoint}/object_info/CheckpointLoaderSimple`);
    if (ckptRes.ok) {
      const data = await ckptRes.json();
      const checkpoints = data?.CheckpointLoaderSimple?.input?.required?.ckpt_name?.[0] || [];
      const sel = $('aria-checkpoint');
      if (checkpoints.length) {
        sel.innerHTML = checkpoints.map(c => `<option value="${c}">${c}</option>`).join('');
      } else {
        sel.innerHTML = '<option value="">No checkpoints found</option>';
      }
    }

    // Fetch WAN models
    const wanRes = await fetch(`${state.aria.endpoint}/object_info/WanVideoModelLoader`);
    if (wanRes.ok) {
      const data = await wanRes.json();
      const wanModels = data?.WanVideoModelLoader?.input?.required?.model?.[0] || [];
      const sel = $('aria-wan-model');
      if (wanModels.length) {
        sel.innerHTML = wanModels.map(m => `<option value="${m}">${m}</option>`).join('');
      } else {
        sel.innerHTML = '<option value="">No WAN models found — download one</option>';
      }
    }

    // Fetch T5 encoders
    const t5Res = await fetch(`${state.aria.endpoint}/object_info/LoadWanVideoT5TextEncoder`);
    if (t5Res.ok) {
      const data = await t5Res.json();
      const t5Models = data?.LoadWanVideoT5TextEncoder?.input?.required?.model_name?.[0] || [];
      const sel = $('aria-t5-model');
      if (t5Models.length) {
        sel.innerHTML = t5Models.map(m => `<option value="${m}">${m}</option>`).join('');
      } else {
        sel.innerHTML = '<option value="">No T5 models found</option>';
      }
    }

    // Update stat
    const ckptCount = $('aria-checkpoint').options.length;
    const wanCount = $('aria-wan-model').options.length;
    $('ariaStatModels').textContent = ckptCount + wanCount;
  } catch (e) {
    ariaLog('Failed to fetch model list: ' + e.message, 'error');
  }
}

// ---- ARIA Log ----
function ariaLog(msg, type = 'info') {
  const log = $('ariaLog');
  log.classList.add('visible');
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const line = document.createElement('div');
  line.className = `aria-log-line ${type}`;
  line.innerHTML = `<span class="aria-log-time">${time}</span><span class="aria-log-msg">${escapeHtml(msg)}</span>`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function ariaSetProgress(pct) {
  $('ariaProgressWrap').style.display = 'block';
  $('ariaProgressFill').style.width = pct + '%';
}

// ---- AI Prompt Enhancer ----
async function enhanceAriaPrompt(brief, style, mode) {
  const modeGuide = mode === 'video'
    ? 'a ComfyUI WAN video generation prompt (cinematic movement description, camera motion, atmosphere, no dialogue)'
    : mode === 'poster'
    ? 'a ComfyUI image generation prompt for a social media poster (bold composition, typographic space, vibrant colors, high impact)'
    : 'a ComfyUI Stable Diffusion image generation prompt (visual details, lighting, style, quality tags)';

  const systemP = { label: 'aria-enhance', content: `You are an expert AI image/video prompt engineer. Convert the user's creative brief into ${modeGuide}. Output ONLY the enhanced prompt — no explanation, no quotes, no markdown. Max 200 words. End with quality boosters like "masterpiece, best quality, highly detailed, sharp focus, 8K" (for images) or "cinematic, smooth motion, high frame rate" (for video).` };

  try {
    const result = await callAnthropic('aria', { label: 'enhance', content: `Brief: "${brief}"\nStyle keywords: "${style || 'none'}"` });
    return result.trim();
  } catch {
    return `${brief}${style ? ', ' + style : ''}, masterpiece, best quality, highly detailed, sharp focus`;
  }
}

// ---- Workflow Builders ----
function buildImageWorkflow(posPrompt, negPrompt, checkpoint, width, height, steps, cfg) {
  const seed = Math.floor(Math.random() * 9999999999);
  return {
    "1": { "class_type": "CheckpointLoaderSimple", "inputs": { "ckpt_name": checkpoint } },
    "2": { "class_type": "EmptyLatentImage", "inputs": { "width": width, "height": height, "batch_size": 1 } },
    "3": { "class_type": "CLIPTextEncode", "inputs": { "text": posPrompt, "clip": ["1", 1] } },
    "4": { "class_type": "CLIPTextEncode", "inputs": { "text": negPrompt || "blurry, low quality, deformed, watermark", "clip": ["1", 1] } },
    "5": { "class_type": "KSampler", "inputs": { "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["2", 0], "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler_ancestral", "scheduler": "karras", "denoise": 1.0 } },
    "6": { "class_type": "VAEDecode", "inputs": { "samples": ["5", 0], "vae": ["1", 2] } },
    "7": { "class_type": "SaveImage", "inputs": { "images": ["6", 0], "filename_prefix": "syntiq_aria" } }
  };
}

function buildWanVideoWorkflow(posPrompt, negPrompt, wanModel, t5Model, width, height, frames, steps, cfg) {
  const seed = Math.floor(Math.random() * 9999999999);
  return {
    "1": { "class_type": "WanVideoModelLoader", "inputs": { "model": wanModel, "base_precision": "bf16", "quantization": "disabled", "load_device": "main_device" } },
    "2": { "class_type": "LoadWanVideoT5TextEncoder", "inputs": { "model_name": t5Model, "precision": "bf16", "load_device": "offload_device" } },
    "3": { "class_type": "WanVideoTextEncode", "inputs": { "positive_prompt": posPrompt, "negative_prompt": negPrompt || "low quality, blurry, watermark", "t5": ["2", 0], "force_offload": true } },
    "4": { "class_type": "WanVideoEmptyEmbeds", "inputs": { "width": width, "height": height, "num_frames": frames } },
    "5": { "class_type": "WanVideoSampler", "inputs": { "model": ["1", 0], "image_embeds": ["4", 0], "text_embeds": ["3", 0], "steps": steps, "cfg": cfg, "shift": 5.0, "seed": seed, "scheduler": "unipc", "riflex_freq_index": 0, "force_offload": true } },
    "6": { "class_type": "WanVideoVAELoader", "inputs": { "model_name": "wan_2.1_vae.safetensors" } },
    "7": { "class_type": "WanVideoDecode", "inputs": { "vae": ["6", 0], "samples": ["5", 0], "enable_vae_tiling": true, "tile_x": 272, "tile_y": 272, "tile_stride_x": 144, "tile_stride_y": 128 } },
    "8": { "class_type": "SaveImage", "inputs": { "images": ["7", 0], "filename_prefix": "syntiq_aria_wan" } }
  };
}

// ---- ComfyUI API ----
async function submitComfyWorkflow(workflow) {
  const clientId = 'syntiq_' + Date.now();
  const res = await fetch(`${state.aria.endpoint}/prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: workflow, client_id: clientId })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `ComfyUI error ${res.status}`);
  }
  const data = await res.json();
  return data.prompt_id;
}

async function pollComfyResult(promptId) {
  ariaLog(`Queued: ${promptId.slice(0, 8)}...`);
  let attempts = 0;
  const maxAttempts = 300;

  while (attempts < maxAttempts) {
    await new Promise(r => setTimeout(r, 2000));
    attempts++;
    ariaSetProgress(Math.min(10 + (attempts / maxAttempts) * 80, 88));

    try {
      const res = await fetch(`${state.aria.endpoint}/history/${promptId}`);
      if (!res.ok) continue;
      const history = await res.json();
      const entry = history[promptId];
      if (!entry) continue;

      if (entry.status?.status_str === 'success' || entry.outputs) {
        ariaLog('Rendering complete!', 'success');
        ariaSetProgress(100);
        return entry.outputs;
      }
      if (entry.status?.status_str === 'error') {
        const msgs = entry.status?.messages?.map(m => m[1]).join(', ') || 'Unknown error';
        throw new Error(msgs);
      }
    } catch (e) {
      if (e.message.includes('ComfyUI')) throw e;
    }
  }
  throw new Error('Generation timed out after 10 minutes');
}

function extractImagesFromOutputs(outputs) {
  const images = [];
  for (const nodeId in outputs) {
    const node = outputs[nodeId];
    if (node.images) {
      images.push(...node.images);
    }
  }
  return images;
}

function comfyImageUrl(img) {
  return `${state.aria.endpoint}/view?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || '')}&type=${img.type || 'output'}`;
}

// ---- Main ARIA Runner ----
async function runAriaAgent() {
  if (!state.aria.comfyOnline) {
    showToast('ComfyUI is offline — start it at localhost:8188 first', 'error');
    return;
  }

  const brief = $('aria-brief').value.trim();
  if (!brief) { showToast('Write a creative brief first', 'error'); return; }

  const mode = state.aria.mode;
  const negative = $('aria-negative').value.trim();

  // Clear previous result
  $('aria-result-body').innerHTML = `
    <div style="text-align:center;color:var(--text-secondary);padding:40px 20px">
      <div style="font-size:40px;margin-bottom:12px">⚙️</div>
      <div style="font-weight:600;margin-bottom:6px">Generating...</div>
      <div style="font-size:12px">This may take a few minutes depending on your GPU</div>
    </div>`;
  $('aria-download').style.display = 'none';
  $('aria-send-nova').style.display = 'none';
  $('ariaLog').classList.add('visible');
  $('ariaLog').innerHTML = '';
  ariaSetProgress(2);

  const generateBtn = $('aria-generate');
  generateBtn.disabled = true;
  generateBtn.querySelector('.btn-text').textContent = 'Generating...';

  try {
    let posPrompt = brief;

    // AI Prompt Enhancement
    if (state.aria.enhanceEnabled && state.apiKey) {
      ariaLog('Enhancing prompt with AI...');
      ariaSetProgress(5);
      posPrompt = await enhanceAriaPrompt(brief, $('aria-style').value.trim(), mode);
      ariaLog('Prompt enhanced: ' + posPrompt.slice(0, 80) + '...');
      $('ariaEnhancedPromptText').textContent = posPrompt;
      $('ariaEnhancedPromptPreview').classList.add('visible');
    } else {
      const style = $('aria-style').value.trim();
      if (style) posPrompt = `${brief}, ${style}`;
    }

    // Build workflow
    let workflow;
    ariaSetProgress(8);

    if (mode === 'video') {
      const wanModel = $('aria-wan-model').value;
      const t5Model = $('aria-t5-model').value;
      if (!wanModel) throw new Error('Select a WAN model first');
      if (!t5Model) throw new Error('Select a T5 encoder first');
      const [width, height] = $('aria-vid-res').value.split('x').map(Number);
      const frames = parseInt($('aria-frames').value);
      const steps = parseInt($('aria-wan-steps').value);
      const cfg = parseFloat($('aria-wan-cfg').value);
      workflow = buildWanVideoWorkflow(posPrompt, negative, wanModel, t5Model, width, height, frames, steps, cfg);
      ariaLog(`WAN Video: ${width}×${height}, ${frames} frames, ${steps} steps`);
    } else {
      const checkpoint = $('aria-checkpoint').value;
      if (!checkpoint) throw new Error('Select a checkpoint model first');
      const [width, height] = $('aria-resolution').value.split('x').map(Number);
      const steps = parseInt($('aria-steps').value);
      const cfg = parseFloat($('aria-cfg').value);
      workflow = buildImageWorkflow(posPrompt, negative, checkpoint, width, height, steps, cfg);
      ariaLog(`Image: ${width}×${height}, ${steps} steps, CFG ${cfg}, ${checkpoint}`);
    }

    // Submit
    ariaLog('Submitting to ComfyUI...');
    const promptId = await submitComfyWorkflow(workflow);
    state.aria.promptId = promptId;

    // Poll
    ariaLog('Waiting for GPU...');
    const outputs = await pollComfyResult(promptId);

    // Display result
    const images = extractImagesFromOutputs(outputs);
    if (!images.length) throw new Error('No images in output — check ComfyUI console');

    state.aria.generatedFrames = images;
    const firstUrl = comfyImageUrl(images[0]);
    state.aria.lastImageUrl = firstUrl;
    state.aria.lastFilename = images[0].filename;

    // Build result HTML
    let resultHtml = `<img src="${firstUrl}" class="aria-generated-img" alt="Generated" onerror="this.src='';this.alt='Image failed to load — check ComfyUI'"/>`;
    if (images.length > 1) {
      const thumbs = images.map((img, i) =>
        `<img src="${comfyImageUrl(img)}" class="aria-frame-thumb${i === 0 ? ' active' : ''}" data-url="${comfyImageUrl(img)}" alt="Frame ${i+1}"/>`
      ).join('');
      resultHtml += `<div class="aria-frames-strip">${thumbs}</div>`;
    }
    $('aria-result-body').innerHTML = resultHtml;

    // Frame thumb clicks
    $('aria-result-body').querySelectorAll('.aria-frame-thumb').forEach(thumb => {
      thumb.addEventListener('click', () => {
        $('aria-result-body').querySelectorAll('.aria-frame-thumb').forEach(t => t.classList.remove('active'));
        thumb.classList.add('active');
        $('aria-result-body').querySelector('.aria-generated-img').src = thumb.dataset.url;
        state.aria.lastImageUrl = thumb.dataset.url;
      });
    });

    $('aria-download').style.display = 'flex';
    $('aria-send-nova').style.display = 'flex';

    // Save to history
    const label = `${mode === 'video' ? '🎬' : '🖼'} ${brief.slice(0, 40)}...`;
    saveToHistory('aria', `[${mode}] ${posPrompt}`, label);

    ariaLog(`Done! ${images.length} frame(s) generated.`, 'success');
    showToast('ARIA generated successfully!');

  } catch (err) {
    ariaLog('Error: ' + err.message, 'error');
    $('aria-result-body').innerHTML = `
      <div class="aria-placeholder">
        <div class="aria-placeholder-icon">❌</div>
        <p class="aria-placeholder-text">${escapeHtml(err.message)}</p>
        <span class="aria-placeholder-tip">Check the log below and ensure ComfyUI is running</span>
      </div>`;
    showToast(err.message, 'error');
  } finally {
    generateBtn.disabled = false;
    generateBtn.querySelector('.btn-text').textContent = 'Generate with ARIA';
    ariaSetProgress(0);
    setTimeout(() => { $('ariaProgressWrap').style.display = 'none'; }, 1000);
  }
}

// ---- ARIA × Nova: Build Instagram Post Package ----
async function buildAriaInstagramPost() {
  const brief = $('aria-brief').value.trim() || 'AI agency visual content';
  const imageUrl = state.aria.lastImageUrl;

  // Show the package card
  const card = $('igPackageCard');
  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Put the ARIA image in the phone mock
  $('igPkgImage').innerHTML = `<img src="${imageUrl}" alt="Generated" style="width:100%;height:100%;object-fit:cover;" />`;

  // Reset text areas to loading state
  $('igCaptionBody').innerHTML = '<div class="ig-generating"><div class="ig-gen-spinner"></div>Nova is writing your caption...</div>';
  $('igHashtagsBody').innerHTML = '';
  $('igTimeBody').textContent = '—';
  $('igPkgCaptionPreview').textContent = 'Generating...';

  if (!state.apiKey) {
    $('igCaptionBody').textContent = 'Add an API key to generate captions.';
    return;
  }

  try {
    const novaPrompt = {
      label: 'aria-ig-post',
      content: `Write a world-class Instagram caption package for this visual content.

The image/visual is about: "${brief}"
Brand: Syntiq AI Agency (premium AI services for businesses)
Audience: American business owners and entrepreneurs
Tone: Bold, confident, modern

Return EXACTLY this format:

## CAPTION
[3-4 sentences. Hook + value + CTA. Use 2-3 emojis max. Sound human, not corporate.]

## HASHTAGS
[20 hashtags — mix of niche and broad. One per line, start with #]

## BEST TIME
[Best day + time to post for US audience in one sentence]`
    };

    const result = await callAnthropic('nova', novaPrompt);

    // Parse sections
    const captionMatch = result.match(/##\s*CAPTION\s*([\s\S]*?)(?=##|$)/i);
    const hashMatch = result.match(/##\s*HASHTAGS\s*([\s\S]*?)(?=##|$)/i);
    const timeMatch = result.match(/##\s*BEST TIME\s*([\s\S]*?)(?=##|$)/i);

    const caption = captionMatch ? captionMatch[1].trim() : result.slice(0, 300);
    const hashtags = hashMatch ? hashMatch[1].trim() : '';
    const time = timeMatch ? timeMatch[1].trim() : 'Tuesday–Thursday, 10am–12pm EST';

    // Display caption
    $('igCaptionBody').textContent = caption;
    $('igPkgCaptionPreview').textContent = caption.slice(0, 80) + '...';

    // Display hashtags as clickable tags
    const tags = hashtags.match(/#\w+/g) || [];
    $('igHashtagsBody').innerHTML = tags.map(t =>
      `<span class="tag" style="cursor:default">${t}</span>`
    ).join(' ');

    // Display time
    $('igTimeBody').textContent = time;

    // Store for copy buttons
    state.aria.igCaption = caption;
    state.aria.igHashtags = tags.join(' ');

    showToast('Instagram post package ready!');

  } catch (err) {
    $('igCaptionBody').textContent = 'Error: ' + err.message;
  }
}

// Copy buttons for ig package
document.addEventListener('DOMContentLoaded', () => {
  // These run after setupAria — safe to attach here
  setTimeout(() => {
    const btnCap = $('igCopyCaption');
    const btnHash = $('igCopyHashtags');
    if (btnCap) btnCap.addEventListener('click', () => {
      const text = state.aria?.igCaption || '';
      navigator.clipboard.writeText(text).then(() => showToast('Caption copied!'));
    });
    if (btnHash) btnHash.addEventListener('click', () => {
      const text = state.aria?.igHashtags || '';
      navigator.clipboard.writeText(text).then(() => showToast('Hashtags copied!'));
    });
  }, 500);
});

// Add aria systemPrompt for prompt enhancement
const ariaSystemPrompt = 'You are an expert AI image and video prompt engineer. When asked to enhance a prompt, output ONLY the enhanced generation prompt — no explanation, no markdown, no quotes. Be specific about visuals, lighting, composition, style, and quality. End with quality tags appropriate for the medium.';

// ================================================================

// ---- Toast ----
function showToast(msg, type = 'success') {
  const toast = $('toast');
  $('toastMsg').textContent = msg;
  toast.style.borderColor = type === 'error' ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)';
  toast.style.color = type === 'error' ? '#ef4444' : '#22c55e';
  toast.querySelector('svg').style.display = type === 'error' ? 'none' : 'inline';
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 3000);
}
