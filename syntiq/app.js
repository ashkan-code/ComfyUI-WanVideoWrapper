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
  },
  selectedTypes: { nova: 'instagram-caption', rex: 'cold-email', pixel: 'modern-dark', atlas: 'hashtag-strategy' },
  lastOutputs: { nova: '', rex: '', pixel: '', atlas: '' },
  tracker: JSON.parse(localStorage.getItem('syntiq_tracker') || '[]'),
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
  ['nova', 'rex', 'pixel'].forEach(agent => {
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

[What to measure weekly and monthly]`
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

[Key American dates, holidays, and events in the next 30 days to tie content to for maximum relevance]`
  };

  return { label: `${niche} — ${type}`, content: typeMap[type] };
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
  atlas: "You are Atlas, a world-class Instagram growth strategist specializing in targeting American audiences. You have deep knowledge of US Instagram culture, trending niches, community hashtags, timezone engagement windows, and organic growth tactics. You only recommend manual, safe, human-led strategies — never bots. Your strategies are data-driven, culturally aware, and immediately actionable. Be specific with numbers, times, and examples. Write in a clear, expert tone."
};

// ---- Universal AI Call ----
async function callAnthropic(agent, prompt) {
  if (state.provider === 'groq') return callGroq(agent, prompt);
  if (state.provider === 'gemini') return callGemini(agent, prompt);
  return callAnthropicDirect(agent, prompt);
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
  ['nova', 'rex', 'pixel', 'atlas'].forEach(renderHistory);
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
  ['nova', 'rex', 'pixel', 'atlas'].forEach(agent => {
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
  ['nova', 'rex', 'pixel', 'atlas'].forEach(agent => {
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
};

const agentEmojis = { nova: '⭐', rex: '⚡', pixel: '🎨', atlas: '🌎' };

let thinkingInterval = null;

function showLoading(agent) {
  $('loadingOverlay').classList.add('active');
  $('loadingAgentName').textContent = agent.toUpperCase();
  $('loadingAgentIcon').textContent = agentEmojis[agent];

  // Apply agent color to rings
  const rings = document.querySelectorAll('.spinner-ring');
  const colors = { nova: '#f472b6', rex: '#f59e0b', pixel: '#06b6d4' };
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
