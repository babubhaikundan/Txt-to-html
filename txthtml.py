"""
txthtml.py — TXT → HTML Converter  (v3.1 — fixes applied)

Fixes in v3.1:
• Plyr settings menu (speed/quality card) no longer clips inside player —
  forced bottom-anchor with correct z-index and overflow guard
• Mute button and volume slider removed from player controls
• Footer now shows Telegram link @BabuBhaiKundan with text "Babu Bhai Kundan"
"""

import re, html, json, hashlib, textwrap

# ── YouTube URL detector ───────────────────────────────────────────────────
_YT_RE = re.compile(
    r'(?:https?:)?//?'
    r'(?:www\.)?'
    r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|live/|shorts/)'
    r'|youtu\.be/)'
    r'([a-zA-Z0-9_-]{11})',
    re.IGNORECASE,
)

def _get_youtube_id(url: str):
    """Return 11-char YouTube video ID, or None if not a YouTube URL."""
    m = _YT_RE.search(url)
    return m.group(1) if m else None

def _is_youtube_url(url: str) -> bool:
    """Check if URL contains YouTube domain (but maybe not embeddable ID)."""
    return 'youtube.com/' in url or 'youtu.be/' in url

# FIX: Extracting hardcoded URLs into a dynamic configuration dictionary
CDN_MAPPINGS = {
    'https://apps-s3-jw-prod.utkarshapp.com': 'https://d1q5ugnejk3zoi.cloudfront.net/ut-production-jw',
    # Kal ko naye platforms add karne ho toh bas yahan add karte jana, jaise:
    # 'https://old-domain.com': 'https://new-cdn.com'
}

def _transform_url(url: str) -> str:
    """Rewrite specific domain to CDN using dynamic mappings."""
    for old_domain, new_cdn in CDN_MAPPINGS.items():
        if url.startswith(old_domain):
            return url.replace(old_domain, new_cdn, 1)
    return url

    
    
import os

# Allowed video extensions
VIDEO_EXTENSIONS = {'.mp4', '.m3u8', '.mov', '.webm', '.mkv', '.flv', '.avi', '.ts', '.ogg'}

def _sanitize_id(raw: str) -> str:
    """Replace non-alphanumeric characters with underscore for HTML ID."""
    return re.sub(r'[^a-zA-Z0-9]', '_', raw)
    
    
def _is_valid_media_url(url: str) -> bool:
    """
    True if URL looks like something worth showing a Play/PDF button for.
    Accepts:
      • Known video extensions (.mp4, .m3u8, etc.) — even with a query string
      • .pdf
      • YouTube links
      • ANY other http(s) link with no recognizable extension — many real
        streaming/CDN/download endpoints (e.g. Koyeb, Render backends) serve
        video via a plain path like /download/12345 with no file extension.
        We must NOT silently drop these — better to show a Play button that
        might fail than to silently delete the user's line.
    Only rejects: empty strings and obviously non-http garbage.
    """
    if not url:
        return False
    if _is_youtube_url(url) or _get_youtube_id(url):
        return True

    path = url.split('?')[0].split('#')[0].lower()
    ext = os.path.splitext(path)[1]

    if ext == '.pdf':
        return True
    if ext in VIDEO_EXTENSIONS:
        return True
    if ext == '':
        # No extension at all → treat as a streaming/API link, NOT invalid.
        # Only reject if it doesn't even look like a URL.
        return url.startswith("http://") or url.startswith("https://") or url.startswith("//")
    # Has SOME other extension (.jpg, .zip, .exe, etc.) — genuinely not media
    return False

    
    
# ═══════════════════════════════════════════════════════════════════════════
#  DATA EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def extract_names_and_urls(file_content: str) -> list:
    file_content = file_content.strip()
    if file_content.startswith("{") and file_content.endswith("}"):
        try:
            return [("JSON_DATA", json.loads(file_content))]
        except json.JSONDecodeError as e:
            # FIX: CPU Freeze prevention. Agar JSON format hai but corrupt hai, toh usko line-by-line parse mat karo, direct error throw karo.
            raise ValueError(f"Invalid JSON Format: File JSON jaisi lag rahi hai par format galat hai. (Error: {e})")
    pairs = []

    for line in file_content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            name, _, url = line.partition(":")
            name, url = name.strip(), url.strip()
            # Agar name koi URL hai (http se shuru ya //), to poori line ko URL maano
            if name.startswith("http") or name.startswith("//"):
                name = "Video"
                url = line.strip()
            if name and url and _is_valid_media_url(url):
                pairs.append((name, _transform_url(url)))
        else:
            # No colon, treat entire line as URL
            url = line.strip()
            if url and _is_valid_media_url(url):
                pairs.append(("Video", _transform_url(url)))
    return pairs


def extract_topic(title: str) -> str:
    return re.sub(r"\s*#\d+\s*$", "", title).strip()


def parse_line(name: str):
    if name == "JSON_DATA":
        return "JSON_DATA", None, None
    m = re.match(r"^\((.*?)\)\s*(.+)", name)
    if m:
        subj = m.group(1).strip()
        rest = m.group(2).strip().lstrip("||").strip()
        return subj, extract_topic(rest), rest
    m = re.match(r"^(.*?\s+(?:by|By)\s+(?:Sir|Mam))\s*\|\|\s*(.+)", name)
    if m:
        subj  = m.group(1).strip()
        title = m.group(2).strip()
        return subj, extract_topic(title), title
    if "||" in name:
        subj, _, title = name.partition("||")
        return subj.strip(), extract_topic(title.strip()), title.strip()
    return "General", None, name


def _make_lid(subject: str, topic: str, title: str) -> str:
    raw = f"{subject}||{topic or ''}||{title}"
    return "l" + hashlib.md5(raw.encode()).hexdigest()[:12]


def structure_data_in_order(urls: list) -> list:
    structured  = []
    subject_map = {}
    last_video            = {}   # (subject, topic, title) → exact-match lecture
    last_video_in_topic   = {}   # (subject, topic) → most recent lecture in that topic
    last_video_in_subject = {}   # subject → most recently seen video lecture (any topic)

    for idx, (name, url) in enumerate(urls):
        subject, topic, title = parse_line(name)

        if subject == "JSON_DATA" and name == "JSON_DATA":
            json_data = url
            for ch in json_data.get("data", {}).get("chapters", []):
                subj   = ch.get("subject_id", "General")
                ctitle = ch.get("title", "")
                clink  = _transform_url(ch.get("link", ""))
                if not _is_valid_media_url(clink):
                    continue   # skip invalid
                ctopic = extract_topic(ctitle)
                lid    = _make_lid(subj, ctopic, ctitle)
                if subj not in subject_map:
                    obj = {"name": subj, "topics": {}}
                    subject_map[subj] = obj
                    structured.append(obj)
                cur = subject_map[subj]
                if ctopic not in cur["topics"]:
                    cur["topics"][ctopic] = {"name": ctopic, "lectures": []}
                cur["topics"][ctopic]["lectures"].append(
                    {"title": ctitle, "lid": lid, "videos": [clink], "pdfs": []}
                )
            continue

        is_pdf   = ".pdf" in url.lower()
        key      = (subject, topic or "", title or name)
        topickey = (subject, topic or "")
        lid      = _make_lid(subject, topic or "", f"{title or name}__{idx}")

        if is_pdf:
            # 1. Exact title match (PDF line named exactly like its video) — best case
            if key in last_video:
                last_video[key]["pdfs"].append(url)
                continue
            # 2. Same subject+topic → attach to most recent video there.
            if topickey in last_video_in_topic:
                last_video_in_topic[topickey]["pdfs"].append(url)
                continue
            # 3. Same subject, different/looser topic string (very common —
            #    PDF lines often have a slightly different label than their
            #    video, e.g. "Newton #1 notes" vs "Newton #1"). Attach to the
            #    most recently seen video in the SAME subject, since the PDF
            #    almost always appears right after its matching video line.
            if subject in last_video_in_subject:
                last_video_in_subject[subject]["pdfs"].append(url)
                continue
            # 4. No video seen yet anywhere in this subject → falls through,
            #    becomes its own PDF-only entry (rare: PDF is the very first line).

        lecture = {
            "title":  title or name,
            "lid":    lid,
            "videos": [] if is_pdf else [url],
            "pdfs":   [url] if is_pdf else [],
        }
        if not is_pdf:
            last_video[key] = lecture
            last_video_in_topic[topickey] = lecture
            last_video_in_subject[subject] = lecture

        if subject not in subject_map:
            obj = {"name": subject, "topics": {}}
            subject_map[subject] = obj
            structured.append(obj)

        cur = subject_map[subject]
        if topic:
            if topic not in cur["topics"]:
                cur["topics"][topic] = {"name": topic, "lectures": []}
            cur["topics"][topic]["lectures"].append(lecture)
        else:
            cur.setdefault("direct_lectures", []).append(lecture)

    return _maybe_regroup_parts(structured)


_PART_PATTERN = re.compile(
    r'^(part|section|lecture|unit|week|day|chapter|episode|lec|vid)\s*'
    r'[-\u2013:.#]?\s*\d+\s*$',
    re.IGNORECASE,
)

def _maybe_regroup_parts(structured: list) -> list:
    if len(structured) < 3:
        return structured
    part_like = [s for s in structured if _PART_PATTERN.match(s["name"].strip())]
    if len(part_like) < max(3, int(len(structured) * 0.6)):
        return structured
    new_sub = {"name": "All Lectures", "topics": {}}
    for sub in structured:
        all_lecs = list(sub.get("direct_lectures", []))
        for t in sub.get("topics", {}).values():
            all_lecs.extend(t["lectures"])
        if all_lecs:
            new_sub["topics"][sub["name"]] = {"name": sub["name"], "lectures": all_lecs}
    return [new_sub]


def count_total_lectures(structured: list) -> int:
    n = 0
    for sub in structured:
        n += len(sub.get("direct_lectures", []))
        for t in sub.get("topics", {}).values():
            n += len(t.get("lectures", []))
    return n


# ═══════════════════════════════════════════════════════════════════════════
#  HTML CONTENT BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def _lecture_html(lec: dict, global_index: int) -> str:
    title  = lec["title"]
    lid    = lec["lid"]
    videos = lec["videos"]
    pdfs   = lec["pdfs"]
    et     = html.escape(title)
    eta    = html.escape(title, quote=True)
    multi  = len(videos) > 1

    video_links = ""
    for i, vurl in enumerate(videos, 1):
        yt_id    = _get_youtube_id(vurl)
        is_yt    = yt_id is not None
        is_probably_yt = not is_yt and _is_youtube_url(vurl)

        if multi:
            label = f"Part {i} &#9654;"
        elif is_yt or is_probably_yt:
            label = "&#9654;&nbsp;YouTube"
        else:
            label = "&#9654;&nbsp;Play"

        extra_cls = " yt-item" if (is_yt or is_probably_yt) else ""
        if is_yt:
            data_part = f'data-yt="{html.escape(yt_id, quote=True)}"'
            aria_lbl  = f"Watch on YouTube: {eta}"
        elif is_probably_yt:
            data_part = f'data-url="{html.escape(vurl, quote=True)}"'
            aria_lbl  = f"Open YouTube link: {eta}"
        else:
            data_part = f'data-url="{html.escape(vurl, quote=True)}"'
            aria_lbl  = f"Play {eta}{(' part ' + str(i)) if multi else ''}"

        video_links += (
            f'<a href="#" class="list-item video-item{extra_cls}" role="button" tabindex="0"'
            f' {data_part} data-lid="{lid}" data-title="{eta}"'
            f' data-gidx="{global_index}"'
            f' aria-label="{html.escape(aria_lbl, quote=True)}"'
            f' onclick="playVideo(event,this)"'
            f' onkeydown="if(event.key===\'Enter\'||event.key===\' \'){{event.preventDefault();playVideo(event,this);}}">'
            f'{label}</a>'
        )

    pdf_links = ""
    for purl in pdfs:
        eu = html.escape(purl, quote=True)
        pdf_links += (
            f'<a href="{eu}" target="_blank" rel="noopener noreferrer"'
            f' class="list-item pdf-item" aria-label="Open PDF for {eta}">'
            f'<i class="fa-solid fa-file-pdf" aria-hidden="true"></i>&nbsp;PDF</a>'
        )

    watch_btn = (
        f'<button class="watch-btn" data-lid="{lid}"'
        f' onclick="toggleWatched(\'{lid}\')"'
        f' aria-label="Mark as watched" aria-pressed="false"'
        f' title="Mark watched">&#9675;</button>'
    )

    copy_btn = (
        f'<button class="copy-btn" data-lid="{lid}"'
        f' onclick="copyLectureLink(\'{lid}\')"'
        f' aria-label="Copy link" title="Copy link">'
        f'<i class="fa-solid fa-link" aria-hidden="true"></i></button>'
    ) if videos else ""

    return (
        f'<div class="lecture-entry" data-lid="{lid}" data-gidx="{global_index}">'
        f'<div class="lecture-meta">'
        f'{watch_btn}'
        f'<p class="lecture-title" data-title="{eta}">{et}</p>'
        f'{copy_btn}'
        f'</div>'
        f'<div class="lecture-links">{video_links}{pdf_links}</div>'
        f'</div>'
    )


def _build_content_html(structured: list) -> str:
    if not structured:
        return "<p class='empty-msg'>No content found.</p>"
    parts = []
    for sub_idx, sub in enumerate(structured):
        sname = sub["name"]
        direct = sub.get("direct_lectures", [])
        topics = sub.get("topics", {})
        total = len(direct) + sum(len(t["lectures"]) for t in topics.values())

        # direct lectures ka khaali container
        direct_container = f'<div id="direct-{sub_idx}" class="topic-content direct-content"></div>' if direct else ''

        # topic buttons with empty content div
        topic_buttons = []
        for tname, tdata in topics.items():
            tc = len(tdata["lectures"])
            tid = f"topic-{sub_idx}-{_sanitize_id(tname)}"
            topic_buttons.append(
                f'<div class="topic-accordion">'
                f'<button class="topic-header" aria-expanded="false"'
                f' aria-controls="{tid}" data-subidx="{sub_idx}" data-topic="{html.escape(tname, quote=True)}">'
                f'<i class="fa-solid fa-folder" aria-hidden="true"></i>'
                f'<span class="topic-name">{html.escape(tname)}</span>'
                f'<span class="topic-count" aria-label="{tc} lectures">{tc}</span>'
                f'<span class="topic-progress" aria-live="polite"></span>'
                f'</button>'
                f'<div class="topic-content" id="{tid}"></div>'
                f'</div>'
            )

        escaped_sname = html.escape(sname, quote=True)
        parts.append(
            f'<div class="accordion-item">'
            f'<button class="accordion-header" aria-expanded="false"'
            f' aria-controls="ac-{sub_idx}" data-subidx="{sub_idx}">'
            f'<span class="sub-name">{html.escape(sname)}</span>'
            f'<span class="sub-count" aria-label="{total} lectures">{total}</span>'
            f'<span class="sub-progress" aria-live="polite"></span>'
            f'<span class="acc-arrow" aria-hidden="true">&#43;</span>'
            f'</button>'
            f'<div class="accordion-content" id="ac-{sub_idx}">'
            f'{"".join(topic_buttons)}{direct_container}'
            f'</div>'
            f'</div>'
        )
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
#  CSS
# ═══════════════════════════════════════════════════════════════════════════

_CSS = """
/* ── CSS Variables ── */
:root {
  --bg:#f0f4f8; --card:#ffffff; --header-bg:#0f172a;
  --text:#1e293b; --muted:#64748b; --border:#e2e8f0;
  --accent:#2563eb; --accent2:#0ea5e9; --green:#22c55e; --red:#ef4444;
  --plyr-color-main:#0ea5e9;
  --shadow:0 1px 3px rgba(0,0,0,.08),0 4px 12px rgba(0,0,0,.06);
  --shadow-md:0 4px 16px rgba(0,0,0,.12);
  --radius:12px; --radius-sm:8px;
  --header-h:48px;
}
html.dark {
  --bg:#0d1117; --card:#161b22; --header-bg:#010409;
  --text:#e6edf3; --muted:#8b949e; --border:#30363d;
  --accent:#58a6ff; --accent2:#38bdf8; --green:#4ade80; --red:#f87171;
  --shadow:0 1px 3px rgba(0,0,0,.3),0 4px 12px rgba(0,0,0,.25);
  --shadow-md:0 4px 16px rgba(0,0,0,.4);
}

/* ── Reset & Base ── */
*{margin:0;padding:0;box-sizing:border-box;}
html{scroll-behavior:smooth;overflow-x:hidden;}
body{overflow-x:hidden;max-width:100%;
  background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Inter,sans-serif;
  font-size:15px;line-height:1.5;
  transition:background .25s,color .25s;
}

/* ── Header ── */
.header{
  background:var(--header-bg);color:#fff;
  padding:0 12px;height:var(--header-h);
  display:flex;align-items:center;gap:10px;
  position:sticky;top:0;z-index:2000;
  box-shadow:0 2px 8px rgba(0,0,0,.25);
}
.header-title{
  font-size:15px;font-weight:700;flex:1;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  letter-spacing:-.01em;
}
.header-controls{display:flex;gap:5px;align-items:center;flex-shrink:0;}
.ctrl-btn{
  background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.18);
  color:#fff;border-radius:8px;padding:6px 9px;cursor:pointer;
  font-size:12px;line-height:1;transition:background .2s,transform .15s;
  white-space:nowrap;
}
.ctrl-btn:hover{background:rgba(255,255,255,.22);}
.ctrl-btn:focus-visible{outline:2px solid var(--accent2);outline-offset:2px;}

/* ── Progress Bar ── */
.progress-bar-track{
  height:3px;background:var(--border);
  position:sticky;top:var(--header-h);z-index:1999;
}
.progress-bar-fill{
  height:100%;width:0%;
  background:linear-gradient(90deg,var(--accent2),var(--accent));
  transition:width .4s ease;
}

/* ── Toast Notifications ── */
#toast-container{
  position:fixed;bottom:24px;right:20px;z-index:9999;
  display:flex;flex-direction:column;gap:8px;pointer-events:none;
}
.toast{
  background:#1e293b;color:#f1f5f9;border-radius:10px;
  padding:10px 16px;font-size:13px;font-weight:500;
  display:flex;align-items:center;gap:8px;
  box-shadow:0 6px 24px rgba(0,0,0,.35);
  opacity:0;transform:translateY(12px) scale(.96);
  transition:opacity .25s,transform .25s;pointer-events:auto;
  max-width:300px;border-left:4px solid var(--accent2);
}
.toast.show{opacity:1;transform:translateY(0) scale(1);}
.toast.toast-success{border-left-color:var(--green);}
.toast.toast-error{border-left-color:var(--red);}
.toast.toast-warn{border-left-color:#f59e0b;}

/* ── Main Container ── */
.main-container{padding:14px;max-width:900px;margin:0 auto;}

/* ── Player ── */
.player-wrapper{
  background:#000;margin-bottom:12px;border-radius:var(--radius);
  overflow:visible;                        /* FIX: was overflow:hidden — now menus pop out */
  box-shadow:0 8px 32px rgba(0,0,0,.28);
  position:sticky;top:calc(var(--header-h) + 3px);z-index:1000;
}
/* Inner clip so video corners stay rounded but menus escape */
.player-wrapper > video,
.player-wrapper > .plyr {
  border-radius:var(--radius);
  overflow:hidden;
}

/* ── Plyr settings/quality menu — always render ABOVE controls ── */
.plyr__menu {
  z-index:10000 !important;
  position:relative !important;
}


/* ── Hide mute button and volume slider ── */
.plyr__controls .plyr__control[data-plyr="mute"],
.plyr__volume {
  display:none !important;
}

/* Loading spinner overlay */
.player-loading{
  position:absolute;inset:0;background:rgba(0,0,0,.55);
  display:flex;align-items:center;justify-content:center;
  z-index:10;border-radius:var(--radius);opacity:0;pointer-events:none;
  transition:opacity .25s;
}
.player-loading.visible{opacity:1;pointer-events:auto;}
.spinner{
  width:44px;height:44px;border:4px solid rgba(255,255,255,.2);
  border-top-color:#fff;border-radius:50%;
  animation:spin .8s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg);}}
/* Error overlay */
.player-error{
  position:absolute;inset:0;background:rgba(0,0,0,.8);
  display:none;flex-direction:column;align-items:center;justify-content:center;
  z-index:11;border-radius:var(--radius);gap:12px;color:#fff;padding:24px;
  text-align:center;
}
.player-error.visible{display:flex;}
.player-error p{font-size:14px;color:#fca5a5;line-height:1.5;}
.player-error-title{font-size:16px;font-weight:700;}
.retry-btn{
  background:var(--accent2);border:none;color:#fff;
  border-radius:8px;padding:8px 20px;cursor:pointer;font-size:14px;font-weight:600;
  transition:background .2s;
}
.retry-btn:hover{background:var(--accent);}
.open-link-btn{background:rgba(255,255,255,.12);margin-left:8px;text-decoration:none;}
.open-link-btn:hover{background:rgba(255,255,255,.22);}

.plyr{border-radius:var(--radius);}
/* Plyr init se pehle native <video> bhi poori width + 16:9 le */
.player-wrapper{width:100%;max-width:100%;min-width:0;}
.player-wrapper > video{
  display:block;width:100%;max-width:100%;
  aspect-ratio:16/9;background:#000;object-fit:contain;
}

/* Now playing */
.now-playing{
  background:linear-gradient(135deg,#1e293b,#0f172a);
  border:1px solid rgba(14,165,233,.25);
  border-radius:var(--radius-sm);padding:9px 14px;margin-bottom:10px;
  display:none;align-items:center;gap:9px;font-size:13px;color:#e2e8f0;
}
.now-playing-dot{
  width:8px;height:8px;border-radius:50%;background:var(--accent2);
  flex-shrink:0;animation:blink 1.2s ease-in-out infinite;
}
@keyframes blink{0%,100%{opacity:1;}50%{opacity:.3;}}
.now-playing-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500;}
.now-playing-nav{display:flex;gap:6px;flex-shrink:0;}
.nav-btn{
  background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);
  color:#fff;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px;
  transition:background .2s;
}
.nav-btn:hover{background:rgba(255,255,255,.26);}
.nav-btn:disabled{opacity:.3;cursor:not-allowed;}

/* Auto-next banner */
.autonext-banner{
  background:linear-gradient(135deg,#1e3a5f,#0f172a);
  border:1px solid rgba(14,165,233,.3);
  border-radius:var(--radius-sm);padding:10px 14px;margin-bottom:10px;
  display:none;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:#e2e8f0;
}
.autonext-banner.show{display:flex;}
.autonext-count{
  font-size:22px;font-weight:800;color:var(--accent2);
  min-width:28px;text-align:center;line-height:1;
}
.autonext-label{flex:1;min-width:120px;}
.autonext-cancel{
  background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);
  color:#94a3b8;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px;
}
.autonext-play{
  background:var(--accent2);border:none;color:#fff;
  border-radius:6px;padding:5px 12px;cursor:pointer;font-size:12px;font-weight:600;
}

/* ── Resume Banner ── */
.resume-banner{
  background:linear-gradient(135deg,#1e293b,#0f172a);
  border:1px solid rgba(14,165,233,.2);
  border-radius:var(--radius-sm);padding:11px 14px;margin-bottom:10px;
  display:none;align-items:center;gap:10px;flex-wrap:wrap;font-size:13px;color:#e2e8f0;
}
.resume-banner span{flex:1;min-width:140px;}
.resume-btn{
  background:var(--accent2);border:none;color:#fff;
  border-radius:6px;padding:6px 12px;cursor:pointer;font-size:12px;font-weight:600;
  transition:background .2s;
}
.resume-btn:hover{background:var(--accent);}
.resume-dismiss{
  background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);
  color:#94a3b8;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:12px;
}

/* ── Search ── */
.search-wrap{position:relative;margin-bottom:12px;}
.search-wrap .fa-magnifying-glass{
  position:absolute;left:14px;top:50%;transform:translateY(-50%);
  color:var(--muted);font-size:14px;pointer-events:none;
}
.search-input{
  width:100%;padding:11px 42px 11px 40px;
  border:1.5px solid var(--border);border-radius:var(--radius);
  font-size:14px;background:var(--card);color:var(--text);
  outline:none;transition:border-color .2s,box-shadow .2s;
}
.search-input:focus{border-color:var(--accent2);box-shadow:0 0 0 3px rgba(14,165,233,.12);}
.search-clear{
  position:absolute;right:13px;top:50%;transform:translateY(-50%);
  background:none;border:none;color:var(--muted);font-size:16px;
  cursor:pointer;display:none;padding:2px 4px;border-radius:4px;
  transition:color .2s;
}
.search-clear:hover{color:var(--text);}
.search-clear.visible{display:block;}

/* ── Filter Chips (Watched / Unwatched / All) ── */
.filter-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;}
.filter-chip{
  font-size:12.5px;font-weight:600;padding:6px 13px;border-radius:20px;
  border:1.5px solid var(--border);background:var(--card);color:var(--muted);
  cursor:pointer;transition:all .2s;
}
.filter-chip:hover{border-color:var(--accent2);color:var(--accent2);}
.filter-chip.active{background:var(--accent2);border-color:var(--accent2);color:#fff;}
.subject-filter-select{
  font-size:12.5px;font-weight:600;padding:6px 10px;border-radius:20px;
  border:1.5px solid var(--border);background:var(--card);color:var(--text);
  cursor:pointer;outline:none;max-width:160px;
}
.subject-filter-select:focus{border-color:var(--accent2);}

/* ── Toolbar ── */
.toolbar{display:flex;gap:8px;align-items:center;margin-bottom:14px;flex-wrap:wrap;}
.badge{
  font-size:12px;font-weight:500;border-radius:20px;padding:4px 12px;
  border:1.5px solid var(--border);background:var(--card);color:var(--muted);
}
.badge-progress{border-color:var(--accent2);color:var(--accent2);}
.badge-result{border-color:var(--accent);color:var(--accent);}

/* ── Subject Accordion ── */
.accordion-item{
  margin-bottom:10px;border-radius:var(--radius);
  background:var(--card);box-shadow:var(--shadow);
  border:1px solid var(--border);overflow:hidden;
}
.accordion-header{
  width:100%;background:var(--card);color:var(--text);border:none;
  text-align:left;padding:15px 18px;cursor:pointer;
  display:flex;align-items:center;gap:10px;
  transition:background .2s;
}
.accordion-header:hover{background:var(--bg);}
.accordion-header.active{background:var(--bg);}
.accordion-header:focus-visible{outline:2px solid var(--accent2);outline-offset:-2px;}
.sub-name{font-size:15px;font-weight:700;flex:1;letter-spacing:-.01em;}
.sub-count{
  background:#dbeafe;color:#1d4ed8;font-size:11px;font-weight:700;
  border-radius:20px;padding:3px 9px;flex-shrink:0;
}
html.dark .sub-count{background:#1e3a5f;color:#60a5fa;}
.sub-progress{font-size:12px;color:var(--muted);flex-shrink:0;}
.acc-arrow{
  color:var(--muted);font-size:20px;font-weight:300;
  transition:transform .35s cubic-bezier(.4,0,.2,1);flex-shrink:0;
  margin-left:4px;user-select:none;
}
.accordion-header.active .acc-arrow{transform:rotate(45deg);}
.accordion-content{
  overflow:hidden;max-height:0;
  transition:max-height .4s cubic-bezier(.4,0,.2,1);
  padding:0 14px;
}
.accordion-content.open{padding-bottom:8px;}

/* ── Topic Accordion ── */
.topic-accordion{margin:8px 0;border-radius:var(--radius-sm);overflow:hidden;}
.topic-header{
  width:100%;background:var(--bg);color:var(--text);border:none;
  text-align:left;padding:10px 13px;cursor:pointer;border-radius:var(--radius-sm);
  display:flex;align-items:center;gap:8px;font-size:14px;
  transition:background .2s,color .2s;
}
.topic-header .fa-folder{color:var(--accent2);font-size:13px;transition:color .2s;}
.topic-header:hover{background:var(--border);}
.topic-header.active{background:var(--accent2);color:#fff;}
.topic-header.active .fa-folder{color:rgba(255,255,255,.8);}
.topic-header:focus-visible{outline:2px solid var(--accent2);outline-offset:2px;}
html.dark .topic-header.active{background:#0369a1;}
.topic-name{flex:1;font-weight:600;}
.topic-count{
  font-size:11px;font-weight:700;border-radius:20px;padding:2px 8px;
  background:rgba(0,0,0,.1);flex-shrink:0;
}
.topic-header.active .topic-count{background:rgba(255,255,255,.2);}
.topic-progress{font-size:11px;flex-shrink:0;opacity:.8;}
.topic-content{
  max-height:0;overflow:hidden;
  transition:max-height .35s cubic-bezier(.4,0,.2,1);
  padding:0 4px;
}
/* direct (topic-less) lectures: hamesha visible, max-height:0 se hide nahi hona chahiye */
.topic-content.direct-content{max-height:none;overflow:visible;}

/* ── Lecture Row ── */
.lecture-entry{
  padding:11px 0;border-bottom:1px solid var(--border);
  border-left:3px solid transparent;padding-left:6px;
  transition:border-color .2s,background .2s;
}
.lecture-entry:last-child{border-bottom:none;}
.lecture-entry.watched{border-left-color:var(--green);}
.lecture-entry.now-active{
  border-left-color:var(--accent2);
  background:rgba(14,165,233,.05);
}
.lecture-meta{display:flex;align-items:flex-start;gap:7px;margin-bottom:9px;}
.watch-btn{
  background:none;border:2px solid var(--border);color:var(--muted);
  border-radius:50%;width:24px;height:24px;cursor:pointer;
  font-size:11px;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;margin-top:1px;transition:all .2s;padding:0;
}
.watch-btn:hover{border-color:var(--green);color:var(--green);}
.lecture-entry.watched .watch-btn{
  background:var(--green);border-color:var(--green);color:#fff;
}
.star-btn{
  background:none;border:none;color:var(--border);cursor:pointer;
  font-size:15px;padding:0 2px;flex-shrink:0;margin-top:0;line-height:1;
  transition:color .2s,transform .15s;
}
.star-btn:hover{color:#f5b301;transform:scale(1.15);}
.star-btn.active{color:#f5b301;}
.lecture-entry.starred{background:rgba(245,179,1,.05);}
.copy-btn{
  background:none;border:none;color:var(--muted);cursor:pointer;
  font-size:12px;padding:3px 5px;border-radius:5px;flex-shrink:0;
  opacity:0;transition:opacity .2s,color .2s,background .2s;margin-top:1px;
}
.lecture-entry:hover .copy-btn,.copy-btn:focus{opacity:1;}
.copy-btn:hover{color:var(--accent2);background:rgba(14,165,233,.1);}
.lecture-title{
  font-size:14px;font-weight:600;color:var(--text);flex:1;line-height:1.45;
}
.lecture-entry.watched .lecture-title{
  color:var(--muted);
  text-decoration:line-through;
  text-decoration-color:var(--green);
}
.lecture-links{display:flex;flex-wrap:wrap;gap:7px;}
mark{background:#fef3c7;color:#92400e;border-radius:3px;padding:0 2px;}
html.dark mark{background:#451a03;color:#fbbf24;}

/* ── Buttons ── */
.list-item{
  display:inline-flex;align-items:center;gap:6px;padding:7px 14px;
  border-radius:20px;text-decoration:none;font-size:13px;font-weight:500;
  cursor:pointer;border:1.5px solid transparent;
  transition:all .2s cubic-bezier(.4,0,.2,1);
}
.video-item{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe;}
.video-item:hover,.video-item.playing{
  background:var(--accent);color:#fff;border-color:var(--accent);
  transform:translateY(-1px);box-shadow:0 4px 12px rgba(37,99,235,.3);
}
.video-item:focus-visible{outline:2px solid var(--accent2);outline-offset:2px;}
html.dark .video-item{background:#172554;color:#93c5fd;border-color:#1e40af;}
html.dark .video-item:hover,html.dark .video-item.playing{
  background:var(--accent);color:#fff;border-color:var(--accent);
}
.pdf-item{background:#fff7ed;color:#c2410c;border-color:#fed7aa;}
.pdf-item:hover{background:#ea580c;color:#fff;border-color:#ea580c;transform:translateY(-1px);}
html.dark .pdf-item{background:#431407;color:#fb923c;border-color:#7c2d12;}

/* YouTube button */
.yt-item{background:#fff1f1;color:#cc0000;border-color:#ffb3b3;}
.yt-item:hover,.yt-item.playing{background:#cc0000;color:#fff;border-color:#cc0000;transform:translateY(-1px);}
html.dark .yt-item{background:#3d0000;color:#ff8080;border-color:#660000;}
html.dark .yt-item:hover,html.dark .yt-item.playing{background:#cc0000;color:#fff;}

/* ── YouTube Embed Wrapper (Clean & Merged) ── */
.yt-embed-wrapper {
  display: none;
  width: 100%;
  background: #000;
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 12px;
  position: sticky;
  top: calc(var(--header-h) + 3px);
  z-index: 1000;
  box-shadow: 0 8px 32px rgba(0,0,0,.28);
  flex-direction: column;
  align-items: center;
}
#yt-frame {
  width: 100%;
  aspect-ratio: 16 / 9;
  border: none;
  display: block;
}

.yt-embed-wrapper.show {
  display: flex;
}

#yt-frame {
  width: 100%;
  aspect-ratio: 16 / 9;
  border: none;
  display: block;
}

/* Permanent big "Open in YouTube" button */
#yt-open-link {
  display: block;
  width: fit-content;
  margin: 12px auto;
  background: #ff0000;
  color: #fff;
  font-size: 16px;
  font-weight: 800;
  padding: 12px 30px;
  border-radius: 30px;
  text-decoration: none;
  text-align: center;
  box-shadow: 0 4px 15px rgba(255,0,0,.4);
  transition: background 0.2s, transform 0.2s;
}
#yt-open-link:hover {
  background: #cc0000;
  transform: translateY(-2px);
}

/* ── YT Embed Fallback (error 153 etc.) ── */
.yt-embed-wrapper.yt-fallback::before {
  content: "⚠️ Video embed restricted. Watch directly on YouTube:";
  display: flex;
  align-items: center;
  justify-content: center;
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.85);
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  padding: 20px;
  text-align: center;
  z-index: 10;
  border-radius: var(--radius);
  flex-direction: column;
  gap: 15px;
  pointer-events: none; /* taaki link click ho sake */
}
.yt-embed-wrapper.yt-fallback .yt-open-link {
  z-index: 11;
  background: #cc0000;
  padding: 12px 25px;
  font-size: 16px;
  border-radius: 30px;
  font-weight: 800;
  bottom: auto;
  top: 60%;
  left: 50%;
  transform: translate(-50%, -50%);
  pointer-events: auto;
}

/* ── Empty state ── */
.empty-msg{text-align:center;padding:48px;color:var(--muted);font-size:15px;}

/* ── Footer ── */
.footer-wrap{
  text-align:center;margin:24px 0 20px;
  padding:18px 0;border-top:1px solid var(--border);
}
.footer-credit-btn{
  display:inline-flex;align-items:center;gap:8px;
  background:#0f172a;padding:9px 20px;border-radius:24px;
  text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.2);
  transition:transform .2s,box-shadow .2s;
}
.footer-credit-btn:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(0,0,0,.3);}
.shortcut-hint{margin-top:12px;font-size:11px;color:var(--muted);line-height:2;}

/* ── Drawer toggle ── */
.kk-drawer-toggle{
  width:34px;height:34px;
  padding:0!important;
  background:rgba(255,255,255,.1)!important;
  border:1px solid rgba(255,255,255,.18)!important;
  border-radius:8px!important;
  display:flex!important;flex-direction:column!important;
  align-items:center!important;justify-content:center!important;
  gap:4px!important;cursor:pointer!important;
  transition:background .2s!important;flex-shrink:0;
}
.kk-drawer-toggle:hover{background:rgba(255,255,255,.22)!important;}
.kk-drawer-toggle:focus-visible{outline:2px solid var(--accent2)!important;outline-offset:2px!important;}
.kk-drawer-toggle span{
  display:block!important;width:16px!important;height:2px!important;
  background:#fff!important;border-radius:3px!important;
  transition:all .35s cubic-bezier(.4,0,.2,1)!important;
}
.kk-drawer-toggle.active{background:var(--accent2)!important;border-color:var(--accent2)!important;}
.kk-drawer-toggle.active span:nth-child(1){transform:translateY(6px) rotate(45deg)!important;}
.kk-drawer-toggle.active span:nth-child(2){opacity:0!important;transform:scale(0)!important;}
.kk-drawer-toggle.active span:nth-child(3){transform:translateY(-6px) rotate(-45deg)!important;}

/* ── Responsive ── */
@media(max-width:600px){
  :root{--header-h:44px;}
  .header-title{font-size:13px;}
  .accordion-header{padding:13px 14px;}
  .sub-name{font-size:14px;}
  .main-container{padding:10px;}
  .now-playing-nav{display:none;}
}
@media(prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important;}
}

/* =========================
   FINAL PLYR MOBILE FIX
   ========================= */

.player-wrapper,
.player-wrapper > .plyr,
.plyr,
.plyr__video-wrapper,
.plyr__controls{
    overflow: visible !important;
}

.plyr{
    position: relative !important;
}

.plyr__menu{
    z-index: 9999 !important;
}

.plyr__menu__container{
    z-index: 99999 !important;
    max-height: min(220px, 45vh) !important;
    overflow-y: auto !important;
    overflow-x: hidden !important;
    border-radius: 10px !important;
}

.plyr__menu__container [role="menu"]{
    max-height: min(180px, 40vh) !important;
    overflow-y: auto !important;
}

/* Quality/speed menu items — bigger tap targets on mobile, clear active state */
.plyr__menu__container [role="menuitemradio"]{
    padding: 10px 14px !important;
    font-size: 14px !important;
    min-height: 40px !important;
}
.plyr__menu__container [role="menuitemradio"][aria-checked="true"]{
    font-weight: 700 !important;
    color: var(--accent2) !important;
}
@media(max-width:480px){
  .plyr__menu__container{ max-height:min(190px,38vh) !important; }
  .plyr__menu__container [role="menuitemradio"]{ padding:12px 14px !important; font-size:13.5px !important; }
}
/* HD badge next to 720p/1080p/1440p/2160p quality options */
.plyr__menu__container [data-plyr="quality"][value="720"] span::after,
.plyr__menu__container [data-plyr="quality"][value="1080"] span::after,
.plyr__menu__container [data-plyr="quality"][value="1440"] span::after,
.plyr__menu__container [data-plyr="quality"][value="2160"] span::after{
  content:'HD'; font-size:9px; font-weight:800; color:#fff;
  background:var(--accent2); border-radius:4px; padding:1px 5px; margin-left:6px;
  vertical-align:middle;
}

/* Smooth scrolling */
.plyr__menu__container::-webkit-scrollbar{
    width: 4px;
}

.plyr__menu__container::-webkit-scrollbar-thumb{
    border-radius: 10px;
}

/* ═══════════════════════════════════
   MODAL SYSTEM (Settings + PDF)
═══════════════════════════════════ */
.modal-overlay{
  position:fixed;inset:0;background:rgba(0,0,0,.6);
  display:flex;align-items:center;justify-content:center;
  z-index:9500;opacity:0;visibility:hidden;padding:16px;
  transition:opacity .25s,visibility .25s;
  backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);
}
.modal-overlay.open{opacity:1;visibility:visible;}
.modal-box{
  background:var(--card);border-radius:var(--radius);
  box-shadow:0 20px 60px rgba(0,0,0,.35);
  width:100%;max-width:420px;max-height:88vh;overflow-y:auto;
  transform:scale(.94) translateY(10px);transition:transform .25s;
}
.modal-overlay.open .modal-box{transform:scale(1) translateY(0);}
.modal-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:16px 18px;border-bottom:1px solid var(--border);
}
.modal-title{font-size:16px;font-weight:700;color:var(--text);}
.modal-close{
  background:none;border:none;color:var(--muted);font-size:18px;
  cursor:pointer;padding:4px 8px;border-radius:6px;transition:all .2s;
}
.modal-close:hover{background:var(--bg);color:var(--text);}
.modal-body{padding:18px;}

/* Settings form */
.setting-row{
  display:flex;align-items:center;justify-content:space-between;
  padding:12px 0;border-bottom:1px solid var(--border);gap:12px;
}
.setting-row:last-of-type{border-bottom:none;}
.setting-label{font-size:14px;font-weight:600;color:var(--text);}
.setting-hint{font-size:11.5px;color:var(--muted);margin-top:2px;}
.setting-control select,.setting-control input[type="number"]{
  padding:7px 10px;border:1.5px solid var(--border);border-radius:8px;
  background:var(--bg);color:var(--text);font-size:13px;width:90px;
}
.switch{position:relative;display:inline-block;width:42px;height:24px;flex-shrink:0;}
.switch input{opacity:0;width:0;height:0;}
.switch-track{
  position:absolute;inset:0;background:var(--border);border-radius:24px;
  cursor:pointer;transition:background .2s;
}
.switch-track::before{
  content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;
  background:#fff;border-radius:50%;transition:transform .2s;
  box-shadow:0 1px 3px rgba(0,0,0,.3);
}
.switch input:checked + .switch-track{background:var(--accent2);}
.switch input:checked + .switch-track::before{transform:translateX(18px);}
.modal-save-btn{
  width:100%;padding:11px;background:var(--accent2);color:#fff;
  border:none;border-radius:var(--radius-sm);font-size:14px;font-weight:700;
  cursor:pointer;margin-top:14px;transition:background .2s;
}
.modal-save-btn:hover{background:var(--accent);}

/* PDF modal specific */
.pdf-modal-box{max-width:900px;height:88vh;display:flex;flex-direction:column;}
.pdf-modal-body{flex:1;padding:0;display:flex;flex-direction:column;overflow:hidden;}
#pdf-frame{width:100%;flex:1;border:none;background:#525659;}
.pdf-modal-actions{
  display:flex;gap:8px;padding:10px 14px;border-top:1px solid var(--border);
  flex-wrap:wrap;
}
.pdf-action-btn{
  display:inline-flex;align-items:center;gap:6px;padding:8px 14px;
  border-radius:20px;font-size:12.5px;font-weight:600;text-decoration:none;
  background:var(--bg);color:var(--text);border:1.5px solid var(--border);
  cursor:pointer;transition:all .2s;
}
.pdf-action-btn:hover{border-color:var(--accent2);color:var(--accent2);}
@media(max-width:600px){
  .pdf-modal-box{height:92vh;}
  .modal-box{max-width:100%;}
}

"""




# ═══════════════════════════════════════════════════════════════════════════
#  DRAWER CSS + HTML + JS
# ═══════════════════════════════════════════════════════════════════════════

_DRAWER_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&display=swap');
.kk-drawer-overlay{
  position:fixed;top:0;left:0;width:100%;height:100%;
  background:rgba(0,0,0,.75);z-index:8000;opacity:0;visibility:hidden;
  transition:opacity .4s cubic-bezier(.4,0,.2,1),visibility .4s;
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
}
.kk-drawer-overlay.open{opacity:1;visibility:visible;}
.kk-drawer-nav{
  position:fixed;top:0;right:0;width:290px;max-width:82vw;height:100%;
  background:linear-gradient(180deg,rgba(10,20,35,.99),rgba(5,10,15,.99));
  z-index:8500;transform:translateX(105%);
  transition:transform .5s cubic-bezier(.77,0,.175,1);
  display:flex;flex-direction:column;
  box-shadow:-12px 0 48px rgba(0,0,0,.6);
  border-left:1px solid rgba(255,255,255,.07);overflow-y:auto;
}
.kk-drawer-nav{visibility:hidden;box-shadow:none;
  transition:transform .5s cubic-bezier(.77,0,.175,1),visibility 0s linear .5s,box-shadow 0s linear .5s;}
.kk-drawer-nav.open{transform:translateX(0);visibility:visible;box-shadow:-12px 0 48px rgba(0,0,0,.6);
  transition:transform .5s cubic-bezier(.77,0,.175,1),visibility 0s,box-shadow 0s;}
.kk-drawer-header{
  padding:26px 26px 18px;border-bottom:1px solid rgba(255,255,255,.08);flex-shrink:0;
}
.kk-drawer-logo{
  font-family:'Outfit',sans-serif;font-size:1.3rem;font-weight:800;
  display:flex;align-items:center;gap:10px;color:#f5f5ff;
}
.kk-drawer-logo i{color:#00f2ff;}
.kk-drawer-nav ul{list-style:none;padding:18px 22px;flex:1;margin:0;}
.kk-drawer-nav li{
  margin:3px 0;opacity:0;transform:translateX(40px);
  transition:opacity .4s cubic-bezier(.4,0,.2,1),transform .4s cubic-bezier(.4,0,.2,1);
}
.kk-drawer-nav.open li{opacity:1;transform:translateX(0);}
.kk-drawer-nav.open li:nth-child(1){transition-delay:.07s;}
.kk-drawer-nav.open li:nth-child(2){transition-delay:.12s;}
.kk-drawer-nav.open li:nth-child(3){transition-delay:.17s;}
.kk-drawer-nav.open li:nth-child(4){transition-delay:.22s;}
.kk-drawer-nav.open li:nth-child(5){transition-delay:.27s;}
.kk-drawer-nav.open li:nth-child(6){transition-delay:.32s;}
.kk-drawer-nav.open li:nth-child(7){transition-delay:.37s;}
.kk-drawer-nav a{
  font-family:'Outfit',sans-serif;font-size:1.02rem;font-weight:700;
  color:#f0f0ff;text-decoration:none;display:flex;align-items:center;gap:13px;
  padding:10px 8px;border-radius:10px;transition:all .3s ease;
}
.kk-drawer-nav a:hover{color:#00ffc8;background:rgba(0,255,200,.06);padding-left:15px;}
.kk-drawer-nav a:focus-visible{outline:2px solid #00f2ff;outline-offset:2px;}
.kk-drawer-nav a i{
  font-size:.9rem;width:32px;height:32px;display:flex;
  align-items:center;justify-content:center;background:rgba(20,10,40,.7);
  border-radius:9px;flex-shrink:0;transition:all .3s ease;
}
.kk-drawer-nav a:hover i{background:#00ffc8;color:#0a0118;}
.kk-drawer-social{
  padding:18px 22px 26px;border-top:1px solid rgba(255,255,255,.08);flex-shrink:0;
}
.kk-drawer-social-title{
  font-size:.68rem;color:#888;text-transform:uppercase;
  letter-spacing:3px;margin-bottom:12px;font-weight:600;font-family:'Outfit',sans-serif;
}
.kk-drawer-social-links{display:flex;gap:10px;flex-wrap:wrap;}
.kk-drawer-social-links a{
  width:44px;height:44px;background:rgba(20,10,40,.7)!important;
  border:1px solid rgba(255,255,255,.1);border-radius:13px;
  display:flex;align-items:center;justify-content:center;
  color:#fff;font-size:1.1rem;padding:0!important;gap:0!important;
  transition:all .35s ease;
}
.kk-drawer-social-links a:hover{
  border-color:#00f2ff!important;color:#00f2ff!important;
  background:rgba(0,242,255,.07)!important;padding-left:0!important;
  transform:translateY(-4px) rotate(4deg)!important;
  box-shadow:0 10px 25px rgba(0,242,255,.15);
}
.kk-drawer-social-links a:hover i{background:transparent!important;color:#00f2ff!important;}
"""

_DRAWER_HTML = """
<div class="kk-drawer-overlay" id="kk-drawer-overlay" aria-hidden="true"></div>
<nav class="kk-drawer-nav" id="kk-drawer-nav" aria-label="Main Navigation" role="navigation">
  <div class="kk-drawer-header">
    <div class="kk-drawer-logo"><i class="fa-solid fa-cube" aria-hidden="true"></i> Menu</div>
  </div>
  <ul role="menu">
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev" target="_blank" rel="noopener">
        <i class="fa-solid fa-globe" aria-hidden="true"></i> Official Website</a></li>
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev/App-Store/">
        <i class="fa-solid fa-rocket" aria-hidden="true"></i> App Store</a></li>
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev/Tools/">
        <i class="fa-solid fa-wand-magic-sparkles" aria-hidden="true"></i> Tools</a></li>
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev/Resume/" target="_blank" rel="noopener">
        <i class="fa-solid fa-file-invoice" aria-hidden="true"></i> Resume Maker</a></li>
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev/Test-Series/">
        <i class="fa-solid fa-layer-group" aria-hidden="true"></i> Test Series</a></li>
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev/Ai/">
        <i class="fa-solid fa-robot" aria-hidden="true"></i> Ai ChatBot</a></li>
    <li role="menuitem"><a href="https://babubhaikundan.pages.dev/About/">
        <i class="fa-solid fa-user-astronaut" aria-hidden="true"></i> About Me</a></li>
  </ul>
  <div class="kk-drawer-social">
    <div class="kk-drawer-social-title">Connect With Me</div>
    <div class="kk-drawer-social-links">
      <a href="https://instagram.com/babubhaikundan" target="_blank" rel="noopener" aria-label="Instagram">
        <i class="fa-brands fa-instagram" aria-hidden="true"></i></a>
      <a href="https://github.com/babubhaikundan" target="_blank" rel="noopener" aria-label="GitHub">
        <i class="fa-brands fa-github" aria-hidden="true"></i></a>
      <a href="https://twitter.com/babubhaikundan" target="_blank" rel="noopener" aria-label="Twitter / X">
        <i class="fa-brands fa-x-twitter" aria-hidden="true"></i></a>
      <a href="https://t.me/babubhaikundan" target="_blank" rel="noopener" aria-label="Telegram">
        <i class="fa-brands fa-telegram" aria-hidden="true"></i></a>
    </div>
  </div>
</nav>
"""

_DRAWER_JS = r"""
(function () {
  'use strict';
  var tb  = document.getElementById('kk-drawer-toggle');
  var nav = document.getElementById('kk-drawer-nav');
  var ov  = document.getElementById('kk-drawer-overlay');
  if (!tb || !nav || !ov) return;

  function openD() {
    nav.classList.add('open');
    ov.classList.add('open');
    tb.classList.add('active');
    tb.setAttribute('aria-expanded', 'true');
    ov.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    var firstLink = nav.querySelector('a');
    if (firstLink) setTimeout(function () { firstLink.focus(); }, 100);
  }
  function closeD() {
    nav.classList.remove('open');
    ov.classList.remove('open');
    tb.classList.remove('active');
    tb.setAttribute('aria-expanded', 'false');
    ov.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    tb.focus();
  }

  tb.addEventListener('click', function () {
    nav.classList.contains('open') ? closeD() : openD();
  });
  ov.addEventListener('click', closeD);

  nav.addEventListener('keydown', function (e) {
    if (e.key === 'Tab') {
      var focusable = nav.querySelectorAll('a, button, [tabindex]:not([tabindex="-1"])');
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }
    if (e.key === 'Escape') closeD();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && nav.classList.contains('open')) closeD();
  });
})();
"""


# ═══════════════════════════════════════════════════════════════════════════
#  JAVASCRIPT
# ═══════════════════════════════════════════════════════════════════════════

_JS_BODY = r"""
/* ═══════════════════════════════════
   STATE
═══════════════════════════════════ */
var player          = null;
var hlsInstance     = null;
var isPlayerReady   = false;
var currentLid      = null;
var currentPlayUrl  = null;
var currentPlayTitle = '';
var currentGIdx     = -1;
var currentlyPlayingBtn = null;
var autoMarked      = new Set();
var watchedSet      = new Set();
var lastSaveTime    = 0;
var autoNextTimer   = null;
var autoNextTarget  = null;
var lastErrorUrl    = null;
var _nativeTriedUrl  = null;  // HLS fail hone par native fallback sirf ek baar
var renderedSubjects = {};  
var globalLectureIdx = 0;   
var starredSet       = new Set();
var currentWatchFilter = 'all';   // 'all' | 'watched' | 'unwatched'
var currentSubjectFilter = '';    // '' = all subjects, else subIdx as string
var currentSearchTerm  = '';
var SETTINGS = {
  autoNextEnabled: true,
  autoNextSeconds: 5,
  defaultSpeed:    1,
  autoPip:         true
};

/* ═══════════════════════════════════
   TOAST
═══════════════════════════════════ */
function showToast(msg, type, duration) {
  type     = type     || 'info';
  duration = duration || 2800;
  var container = document.getElementById('toast-container');
  var t = document.createElement('div');
  t.className = 'toast toast-' + type;
  var icon = type === 'success' ? '✓' : type === 'error' ? '✕' : type === 'warn' ? '⚠' : 'ℹ';
  t.innerHTML = '<span style="font-size:15px">' + icon + '</span><span>' + msg + '</span>';
  container.appendChild(t);
  requestAnimationFrame(function () {
    requestAnimationFrame(function () { t.classList.add('show'); });
  });
  setTimeout(function () {
    t.classList.remove('show');
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 300);
  }, duration);
}

/* ═══════════════════════════════════
   WATCHED TRACKING
═══════════════════════════════════ */
function loadWatched() {
  try { watchedSet = new Set(JSON.parse(localStorage.getItem(FILE_KEY + '_w') || '[]')); } catch (e) {}
  updateWatchedUI();
}
function toggleWatched(lid) {
  var wasWatched = watchedSet.has(lid);
  if (wasWatched) {
    watchedSet.delete(lid);
    showToast('Marked as unwatched', 'warn');
  } else {
    watchedSet.add(lid);
    showToast('Marked as watched ✓', 'success');
  }
  _persistWatched();
  updateWatchedUI();
}
function markWatched(lid) {
  if (!lid || watchedSet.has(lid)) return;
  watchedSet.add(lid);
  _persistWatched();
  updateWatchedUI();
  showToast('Auto-marked as watched ✓', 'success');
}
function _persistWatched() {
  try { localStorage.setItem(FILE_KEY + '_w', JSON.stringify([...watchedSet])); } catch (e) {}
}

function updateWatchedUI() {
  document.querySelectorAll('.lecture-entry[data-lid]').forEach(function (entry) {
    var lid = entry.dataset.lid;
    var w   = watchedSet.has(lid);
    entry.classList.toggle('watched', w);
    var wb = entry.querySelector('.watch-btn');
    if (wb) {
      wb.innerHTML = w ? '&#10003;' : '&#9675;';
      wb.setAttribute('aria-pressed', w ? 'true' : 'false');
    }
  });

  document.querySelectorAll('.accordion-item').forEach(function (sub) {
    var lecs = sub.querySelectorAll('.lecture-entry[data-lid]');
    var wc   = [...lecs].filter(function (l) { return watchedSet.has(l.dataset.lid); }).length;
    var sp   = sub.querySelector('.sub-progress');
    if (sp) sp.textContent = lecs.length ? wc + '/' + lecs.length : '';

    sub.querySelectorAll('.topic-accordion').forEach(function (t) {
      var tl = t.querySelectorAll('.lecture-entry[data-lid]');
      var tw = [...tl].filter(function (l) { return watchedSet.has(l.dataset.lid); }).length;
      var tp = t.querySelector('.topic-progress');
      if (tp) tp.textContent = tl.length ? tw + '/' + tl.length : '';
    });
  });

  // FIX: use LECTURES.length (full course, always accurate) instead of
  // counting only currently-rendered DOM nodes — big courses with lazy
  // rendering used to show a wrong/partial percentage here.
  var total   = LECTURES.length;
  var watched = watchedSet.size;
  var pb   = document.getElementById('progress-badge');
  var fill = document.getElementById('progress-fill');
  if (total > 0) {
    var pct = Math.round(watched / total * 100);
    if (pb)   pb.textContent = 'Progress: ' + watched + '/' + total + ' (' + pct + '%)';
    if (fill) fill.style.width = pct + '%';
  }
}

/* ═══════════════════════════════════
   FAVORITE / STAR LECTURES
═══════════════════════════════════ */
function loadStars() {
  try { starredSet = new Set(JSON.parse(localStorage.getItem(FILE_KEY + '_star') || '[]')); } catch (e) {}
  updateStarUI();
}
function toggleStar(lid) {
  var was = starredSet.has(lid);
  if (was) { starredSet.delete(lid); showToast('Favorite se hataya', 'warn'); }
  else     { starredSet.add(lid);    showToast('\u2b50 Favorite mein add hua', 'success'); }
  try { localStorage.setItem(FILE_KEY + '_star', JSON.stringify([...starredSet])); } catch (e) {}
  updateStarUI();
}
function updateStarUI() {
  document.querySelectorAll('.lecture-entry[data-lid]').forEach(function (entry) {
    var lid = entry.dataset.lid;
    var s   = starredSet.has(lid);
    entry.classList.toggle('starred', s);
    var sb = entry.querySelector('.star-btn');
    if (sb) {
      sb.classList.toggle('active', s);
      sb.setAttribute('aria-pressed', s ? 'true' : 'false');
    }
  });
}

/* ═══════════════════════════════════
   CONTINUE WATCHING
═══════════════════════════════════ */
function saveLastPlayed(url, title, time) {
  var now = Date.now();
  if (now - lastSaveTime < 5000) return;
  lastSaveTime = now;
  try { localStorage.setItem(FILE_KEY + '_last', JSON.stringify({ url: url, title: title, time: Math.floor(time) })); } catch (e) {}
}
function checkResume() {
  try {
    var s = JSON.parse(localStorage.getItem(FILE_KEY + '_last') || 'null');
    if (s && s.url && s.time > 5) {
      var m   = Math.floor(s.time / 60);
      var sec = String(s.time % 60).padStart(2, '0');
      document.getElementById('resume-text').textContent =
        'Continue: "' + (s.title || '') + '" at ' + m + ':' + sec;
      document.getElementById('resume-banner').style.display = 'flex';
      window._resumeUrl  = s.url;
      window._resumeTime = s.time;
    }
  } catch (e) {}
}
function resumeVideo() {
  document.getElementById('resume-banner').style.display = 'none';
  if (!window._resumeUrl) return;
  var ytId = _getYtId(window._resumeUrl);
  if (ytId) {
    _showYTPlayer(ytId);
    setNowPlaying('Resuming…', -1);
  } else {
    _showDirectPlayer();
    loadNewVideo(window._resumeUrl, window._resumeTime || 0);
  }
}
function dismissResume() {
  document.getElementById('resume-banner').style.display = 'none';
  try { localStorage.removeItem(FILE_KEY + '_last'); } catch (e) {}
}

/* ═══════════════════════════════════
   DARK MODE
═══════════════════════════════════ */
function toggleDark() {
  var d   = document.documentElement.classList.toggle('dark');
  var btn = document.getElementById('darkBtn');
  if (btn) btn.textContent = d ? '\u2600\uFE0F' : '\uD83C\uDF19';
  try { localStorage.setItem('bbk_dark', d ? '1' : '0'); } catch (e) {}
}
function initDarkMode() {
  try {
    if (localStorage.getItem('bbk_dark') === '1') {
      document.documentElement.classList.add('dark');
      var b = document.getElementById('darkBtn');
      if (b) b.textContent = '\u2600\uFE0F';
    }
  } catch (e) {}
}

/* ═══════════════════════════════════
   EXPAND / COLLAPSE ALL
═══════════════════════════════════ */
function expandAll() {
  var headers = Array.prototype.slice.call(document.querySelectorAll('.accordion-header'));
  var BATCH = 4;   // subjects rendered per animation frame — keeps UI responsive
  var i = 0;

  if (headers.length > 8) showToast('Sab expand ho rahe hain\u2026', 'info', 1400);

  function step() {
    var end = Math.min(i + BATCH, headers.length);
    for (; i < end; i++) {
      var btn = headers[i];
      var subIdx = parseInt(btn.getAttribute('data-subidx'), 10);
      if (!isNaN(subIdx) && !renderedSubjects[subIdx]) {
        renderLecturesForSubject(subIdx);
      }
      btn.classList.add('active');
      btn.setAttribute('aria-expanded', 'true');
      var content = btn.nextElementSibling;
      content.classList.add('open');
      content.style.maxHeight = 'none';
    }
    if (i < headers.length) {
      requestAnimationFrame(step);
    } else {
      document.querySelectorAll('.topic-header').forEach(function (b) {
        b.classList.add('active');
        b.setAttribute('aria-expanded', 'true');
        b.nextElementSibling.style.maxHeight = 'none';
      });
    }
  }
  requestAnimationFrame(step);
}

function collapseAll() {
  document.querySelectorAll('.accordion-header.active').forEach(function (b) {
    b.classList.remove('active');
    b.setAttribute('aria-expanded', 'false');
    var content = b.nextElementSibling;
    content.classList.remove('open');
    content.style.maxHeight = null;
  });
  document.querySelectorAll('.topic-header.active').forEach(function (b) {
    b.classList.remove('active');
    b.setAttribute('aria-expanded', 'false');
    b.nextElementSibling.style.maxHeight = null;
  });
}

/* ═══════════════════════════════════
   SEARCH  (debounced 200 ms)
═══════════════════════════════════ */
var _searchTimer = null;
function filterContent(rawTerm) {
  currentSearchTerm = rawTerm;
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(function () { _doFilter(rawTerm); }, 200);
  var clearBtn = document.getElementById('search-clear');
  if (clearBtn) clearBtn.classList.toggle('visible', rawTerm.trim().length > 0);
}
function clearSearch() {
  var input = document.getElementById('searchInput');
  if (input) { input.value = ''; input.focus(); }
  filterContent('');
}
function setWatchFilter(val) {
  currentWatchFilter = val;
  document.querySelectorAll('.filter-chip').forEach(function (c) {
    c.classList.toggle('active', c.dataset.filter === val);
  });
  _doFilter(currentSearchTerm);
}
function setSubjectFilter(val) {
  currentSubjectFilter = val;
  _doFilter(currentSearchTerm);
}

function _doFilter(rawTerm) {
  var term = rawTerm.trim().toLowerCase();

  /* FIX (perf): don't force-render every subject anymore — that's what
     caused big courses (600+ lectures) to hang/freeze on search/filter.
     Matches (text + watched/unwatched + subject) are computed against the
     raw LECTURES data array (already in memory) — no DOM cost at all.
     Only subjects that actually have a visible match get rendered/shown;
     everything else stays hidden & unrendered. */

  var activeFilter = currentWatchFilter || 'all';        // 'all' | 'watched' | 'unwatched'
  var subFilter     = currentSubjectFilter !== '' ? parseInt(currentSubjectFilter, 10) : null;
  var noFilterAtAll = !term && activeFilter === 'all' && subFilter === null;

  // FAST PATH — everything cleared: just show subjects as-is, render nothing new.
  if (noFilterAtAll) {
    document.querySelectorAll('.accordion-item').forEach(function (subEl) {
      subEl.style.display = '';
      var titleEl;
      subEl.querySelectorAll('.lecture-entry').forEach(function (lec) {
        lec.style.display = '';
        titleEl = lec.querySelector('.lecture-title');
        if (titleEl) titleEl.innerHTML = titleEl.dataset.title || titleEl.textContent;
      });
      subEl.querySelectorAll('.topic-accordion').forEach(function (t) { t.style.display = ''; });
    });
    var cb0 = document.getElementById('search-result-count');
    if (cb0) cb0.style.display = 'none';
    return;
  }

  var matchedSubs = {};   // subIdx -> true (subject has ≥1 visible match)
  var matchedLids = {};   // lid -> true (this specific lecture is visible)

  for (var i = 0; i < LECTURES.length; i++) {
    var lec = LECTURES[i];
    if (subFilter !== null && lec.subIdx !== subFilter) continue;
    if (term && lec.title.toLowerCase().indexOf(term) === -1) continue;
    var watched = watchedSet.has(lec.lid);
    if (activeFilter === 'watched'   && !watched) continue;
    if (activeFilter === 'unwatched' &&  watched) continue;
    matchedLids[lec.lid] = true;
    matchedSubs[lec.subIdx] = true;
  }

  // Render only the subjects that actually contain a match
  Object.keys(matchedSubs).forEach(function (subIdxStr) {
    var subIdx = parseInt(subIdxStr, 10);
    if (!renderedSubjects[subIdx]) renderLecturesForSubject(subIdx);
  });

  var esc_re  = term ? new RegExp('(' + term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi') : null;
  var visible = 0;

  document.querySelectorAll('.accordion-item').forEach(function (subEl) {
    var subIdx = parseInt(subEl.querySelector('.accordion-header').getAttribute('data-subidx'), 10);

    if (!matchedSubs[subIdx]) {
      subEl.style.display = 'none';
      return;
    }
    if (!renderedSubjects[subIdx]) {
      // Shouldn't normally happen (we just rendered above) — safety net.
      subEl.style.display = 'none';
      return;
    }

    var subHasVisible = false;

    subEl.querySelectorAll('.topic-accordion').forEach(function (topicEl) {
      var topicHasVisible = false;
      topicEl.querySelectorAll('.lecture-entry').forEach(function (lec) {
        var lid     = lec.dataset.lid;
        var titleEl = lec.querySelector('.lecture-title');
        var orig    = titleEl.dataset.title || titleEl.textContent;
        var match   = !!matchedLids[lid];
        lec.style.display = match ? '' : 'none';
        if (match) {
          topicHasVisible = true; subHasVisible = true; visible++;
          titleEl.innerHTML = term ? orig.replace(esc_re, '<mark>$1</mark>') : orig;
        }
      });
      topicEl.style.display = topicHasVisible ? '' : 'none';
      if (topicHasVisible) {
        var th = topicEl.querySelector('.topic-header');
        th.classList.add('active');
        th.setAttribute('aria-expanded', 'true');
        topicEl.querySelector('.topic-content').style.maxHeight = '99999px';
      }
    });

    subEl.querySelectorAll('.accordion-content > .lecture-entry').forEach(function (lec) {
      var lid     = lec.dataset.lid;
      var titleEl = lec.querySelector('.lecture-title');
      var orig    = titleEl.dataset.title || titleEl.textContent;
      var match   = !!matchedLids[lid];
      lec.style.display = match ? '' : 'none';
      if (match) {
        subHasVisible = true; visible++;
        titleEl.innerHTML = term ? orig.replace(esc_re, '<mark>$1</mark>') : orig;
      }
    });

    subEl.style.display = subHasVisible ? '' : 'none';
    if (subHasVisible) {
      var ah = subEl.querySelector('.accordion-header');
      ah.classList.add('active');
      ah.setAttribute('aria-expanded', 'true');
      var ac = subEl.querySelector('.accordion-content');
      ac.classList.add('open');
      ac.style.maxHeight = '99999px';
    }
  });

  var cb = document.getElementById('search-result-count');
  if (cb) {
    var showBadge = term || activeFilter !== 'all';
    cb.textContent   = showBadge ? visible + ' results' : '';
    cb.style.display = showBadge ? '' : 'none';
  }
}

/* ═══════════════════════════════════
   NOW PLAYING + NAV
═══════════════════════════════════ */
function setNowPlaying(title, gidx) {
  var np  = document.getElementById('now-playing');
  var npt = document.getElementById('now-playing-title');
  if (!np || !npt) return;
  if (title) {
    npt.textContent = title;
    np.style.display = 'flex';
    _updateNavBtns(gidx);
  } else {
    np.style.display = 'none';
  }
}
function _updateNavBtns(gidx) {
  var prevBtn = document.getElementById('btn-prev');
  var nextBtn = document.getElementById('btn-next');
  var all     = document.querySelectorAll('.lecture-entry[data-gidx]');
  var max     = all.length - 1;
  if (prevBtn) prevBtn.disabled = gidx <= 0;
  if (nextBtn) nextBtn.disabled = gidx >= max;
}
function playPrev() {
  if (currentGIdx <= 0) return;
  var entry = document.querySelector('.lecture-entry[data-gidx="' + (currentGIdx - 1) + '"]');
  if (!entry) return;
  var btn = entry.querySelector('.video-item');
  if (btn) btn.click();
}
function playNext() {
  var entry = document.querySelector('.lecture-entry[data-gidx="' + (currentGIdx + 1) + '"]');
  if (!entry) return;
  var btn = entry.querySelector('.video-item');
  if (btn) btn.click();
}

/* ═══════════════════════════════════
   AUTO-NEXT COUNTDOWN
═══════════════════════════════════ */
function _startAutoNext(nextEntry) {
  if (!SETTINGS.autoNextEnabled) return;   // user turned auto-next off in Settings
  var btn = nextEntry.querySelector('.video-item');
  if (!btn) return;
  autoNextTarget = btn;
  var banner    = document.getElementById('autonext-banner');
  var countEl   = document.getElementById('autonext-count');
  var labelEl   = document.getElementById('autonext-label');
  var nextTitle = btn.dataset.title || 'Next lecture';
  if (labelEl) labelEl.textContent = 'Next: "' + nextTitle + '"';
  banner.classList.add('show');

  var count = SETTINGS.autoNextSeconds || 5;
  if (countEl) countEl.textContent = count;
  autoNextTimer = setInterval(function () {
    count--;
    if (countEl) countEl.textContent = count;
    if (count <= 0) {
      _cancelAutoNext();
      if (autoNextTarget) autoNextTarget.click();
    }
  }, 1000);
}
function _cancelAutoNext() {
  clearInterval(autoNextTimer);
  autoNextTimer  = null;
  autoNextTarget = null;
  var banner = document.getElementById('autonext-banner');
  if (banner) banner.classList.remove('show');
}
function cancelAutoNext() { _cancelAutoNext(); }
function playAutoNext() {
  var t = autoNextTarget;
  _cancelAutoNext();
  if (t) t.click();
}

/* ═══════════════════════════════════
   COPY LINK
═══════════════════════════════════ */
function copyLectureLink(lid) {
  var entry = document.querySelector('.lecture-entry[data-lid="' + lid + '"]');
  if (!entry) return;
  var btn = entry.querySelector('.video-item');
  var url = btn ? btn.dataset.url : window.location.href;
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(function () {
      showToast('Link copied to clipboard!', 'success');
    }).catch(function () {
      _fallbackCopy(url);
    });
  } else {
    _fallbackCopy(url);
  }
}
function _fallbackCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity  = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
    showToast('Link copied!', 'success');
  } catch (e) {
    showToast('Could not copy link', 'error');
  }
  document.body.removeChild(ta);
}

/* ═══════════════════════════════════
   PLAYER — TEARDOWN
═══════════════════════════════════ */
function _destroyPlayer() {
  _cancelAutoNext();
  setLoading(false);
  hideError();

  if (hlsInstance) {
    try { hlsInstance.destroy(); } catch (e) {}
    hlsInstance = null;
  }
  if (player) {
    try { player.destroy(); } catch (e) {}
    player = null;
  }
  isPlayerReady = false;
}

/* ═══════════════════════════════════
   PLAYER — UI HELPERS
═══════════════════════════════════ */
function setLoading(on) {
  var el = document.getElementById('player-loading');
  if (el) el.classList.toggle('visible', on);
}
function showError(msg) {
  var el   = document.getElementById('player-error');
  var pm   = document.getElementById('player-error-msg');
  var link = document.getElementById('player-error-link');
  if (el) el.classList.add('visible');
  if (pm) pm.textContent = msg || 'An error occurred while loading the video.';
  if (link) {
    if (lastErrorUrl) { link.href = lastErrorUrl; link.style.display = 'inline-flex'; }
    else { link.style.display = 'none'; }
  }
}
function hideError() {
  var el = document.getElementById('player-error');
  if (el) el.classList.remove('visible');
}
function retryVideo() {
  hideError();
  if (lastErrorUrl) loadNewVideo(lastErrorUrl, 0);
}

/* ═══════════════════════════════════
   YOUTUBE SUPPORT
═══════════════════════════════════ */
function _getYtId(url) {
  if (!url) return null;
  var m = url.match(/(?:https?:)?\/\/?(?:www\.)?(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|live\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
  return m ? m[1] : null;
}
function _showYTPlayer(ytId) {
  var pw   = document.getElementById('player-wrapper');
  var ytW  = document.getElementById('yt-embed-wrapper');
  var frame = document.getElementById('yt-frame');
  var link = document.getElementById('yt-open-link');
  if (pw)   pw.style.display = 'none';
  if (frame) frame.src = 'https://www.youtube-nocookie.com/embed/' + ytId +
    '?autoplay=1&rel=0&fs=1&color=white';
  if (link) link.href = 'https://www.youtube.com/watch?v=' + ytId;
  if (ytW)  ytW.classList.add('show');   // <-- class "show" se display:flex ho jayega
  setLoading(false);
}
function _showDirectPlayer() {
  var pw    = document.getElementById('player-wrapper');
  var ytW   = document.getElementById('yt-embed-wrapper');
  var frame = document.getElementById('yt-frame');
  if (ytW)   ytW.style.display = 'none';
  if (frame) frame.src = '';   /* stop YouTube audio */
  if (pw)    pw.style.display = 'block';
}

/* ═══════════════════════════════════
   PLAYER — PLAY VIDEO
═══════════════════════════════════ */
function playVideo(event, element) {
  if (event) event.preventDefault();
  var ytId  = element.dataset.yt  || null;
  var url   = element.dataset.url || null;
  var lid   = element.dataset.lid   || null;
  var title = element.dataset.title || '';
  var gidx  = parseInt(element.dataset.gidx, 10);
  if (!ytId && !url) return;

  // NEW: If it's a YouTube link but not embeddable, open in new tab
  if (!ytId && element.classList.contains('yt-item')) {
    window.open(url, '_blank');
    showToast('YouTube link opened in new tab', 'info');
    return;
  }

  _destroyPlayer();
  hideError();
  lastErrorUrl = url;
  _nativeTriedUrl = null;

  if (currentlyPlayingBtn) currentlyPlayingBtn.classList.remove('playing');
  element.classList.add('playing');
  currentlyPlayingBtn = element;

  document.querySelectorAll('.lecture-entry.now-active')
    .forEach(function (e) { e.classList.remove('now-active'); });
  var parentEntry = element.closest('.lecture-entry');
  if (parentEntry) {
    parentEntry.classList.add('now-active');
    _openParentAccordions(parentEntry);
    setTimeout(function () {
      parentEntry.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 400);
  }

  currentLid        = lid;
  currentPlayTitle  = title;
  currentGIdx       = gidx;
  setNowPlaying(title, gidx);

  if (ytId) {
    currentPlayUrl = 'https://youtu.be/' + ytId;
    _showYTPlayer(ytId);
    showToast('▶ YouTube video loading…', 'info', 1800);
  } else {
    currentPlayUrl = url;
    setLoading(true);
    _showDirectPlayer();
    setTimeout(function () { loadNewVideo(url, 0); }, 50);
  }
}

function _openParentAccordions(entry) {
  var topicContent = entry.closest('.topic-content');
  if (topicContent) {
    var th = topicContent.previousElementSibling;
    if (th && !th.classList.contains('active')) {
      th.classList.add('active');
      th.setAttribute('aria-expanded', 'true');
      topicContent.style.maxHeight = topicContent.scrollHeight + 'px';
    }
  }
  var accContent = entry.closest('.accordion-content');
  if (accContent) {
    var ah = accContent.previousElementSibling;
    if (ah && !ah.classList.contains('active')) {
      ah.classList.add('active');
      ah.setAttribute('aria-expanded', 'true');
      accContent.classList.add('open');
    }
    accContent.style.maxHeight = 'none';
  }
}

/* ═══════════════════════════════════
   PLAYER — ATTACH EVENTS
═══════════════════════════════════ */
function _attachEvents(startTime) {
  player.on('ready', function () {
    isPlayerReady = true;
    setLoading(false);
    if (startTime > 0) {
      try { player.currentTime = startTime; } catch (e) {}
    }
    player.play().catch(function () {});
  });

  player.on('timeupdate', function () {
    if (!isPlayerReady || !currentPlayUrl) return;
    var dur = player.duration;
    var cur = player.currentTime;
    if (dur > 0 && cur > 3) {
      saveLastPlayed(currentPlayUrl, currentPlayTitle, cur);
      if (currentLid && (cur / dur) > 0.80 && !autoMarked.has(currentLid)) {
        autoMarked.add(currentLid);
        markWatched(currentLid);
      }
    }
  });

  player.on('ended', function () {
    var nextEntry = document.querySelector(
      '.lecture-entry[data-gidx="' + (currentGIdx + 1) + '"]'
    );
    if (nextEntry) _startAutoNext(nextEntry);
  });

  player.on('enterfullscreen', function () {
    try {
      if (screen.orientation && typeof screen.orientation.lock === 'function') {
        screen.orientation.lock('landscape').catch(function () {});
      }
    } catch (e) {}
  });
  player.on('exitfullscreen', function () {
    try {
      if (screen.orientation && typeof screen.orientation.unlock === 'function') {
        screen.orientation.unlock();
      }
    } catch (e) {}
  });

  player.on('error', function (event) {
    setLoading(false);
    var _me = player && player.media && player.media.error;
    showError('Video nahi chal saki' + (_me ? ' [media error ' + _me.code + ']' : '') +
              '. Direct link se dekh lo ya link sahi hai check karo.');
    showToast('Playback error', 'error');
  });
}

/* ═══════════════════════════════════
   PLAYER — LOAD VIDEO
═══════════════════════════════════ */
function loadNewVideo(url, startTime) {
  startTime = startTime || 0;
  var videoEl = document.getElementById('player');

  /* FIX: mute & volume removed from controls array */
  var plyrOpts = {
    controls: [
      'play-large', 'play', 'progress', 'current-time',
      'settings', 'pip', 'fullscreen'
    ],
    settings:  ['speed', 'quality'],
    speed:     { selected: SETTINGS.defaultSpeed || 1, options: [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5] },
    fullscreen:{ enabled: true, fallback: true, iosNative: true },
    clickToPlay: true,
    keyboard:  { focused: true, global: false },
    tooltips:  { controls: true, seek: true },
  };

  var isHLS = url.indexOf('.m3u8') !== -1;

  /* Plyr CDN load nahi hua (offline/blocked) -> native controls se chala do */
  if (typeof Plyr === 'undefined') {
    videoEl.controls = true;
    if (isHLS && typeof Hls !== 'undefined' && Hls.isSupported()) {
      hlsInstance = new Hls();
      hlsInstance.loadSource(url);
      hlsInstance.attachMedia(videoEl);
    } else {
      videoEl.src = url;
    }
    setLoading(false);
    videoEl.play().catch(function () {});
    return;
  }

  if (isHLS && typeof Hls !== 'undefined' && Hls.isSupported()) {
    hlsInstance = new Hls({
      enableWorker:    true,
      maxBufferLength: 30,
      maxMaxBufferLength: 300,
      maxBufferSize:   60 * 1000 * 1000,
      maxBufferHole:   0.5,
      startFragPrefetch: true,
    });
    hlsInstance.loadSource(url);
    hlsInstance.attachMedia(videoEl);

    hlsInstance.on(Hls.Events.MANIFEST_PARSED, function (event, data) {
      var levels   = hlsInstance.levels.map(function (l) { return l.height; });
      var uniqLvls = [...new Set(levels)];
      uniqLvls.unshift(0);

      plyrOpts.quality = {
        default:  0,
        options:  uniqLvls,
        forced:   true,
        onChange: updateQuality,
      };
      plyrOpts.i18n = { qualityLabel: { 0: 'Auto' } };

      player = new Plyr(videoEl, plyrOpts);

      hlsInstance.on(Hls.Events.LEVEL_SWITCHED, function (ev, d) {
        var span = document.querySelector(
          ".plyr__menu__container [data-plyr='quality'][value='0'] span"
        );
        if (span) {
          span.innerHTML = hlsInstance.autoLevelEnabled
            ? 'Auto (' + hlsInstance.levels[d.level].height + 'p)'
            : 'Auto';
        }
      });

      _attachEvents(startTime);
    });

    hlsInstance.on(Hls.Events.ERROR, function (event, data) {
      if (data.fatal) {
        var _code   = (data.response && data.response.code) ? ' HTTP ' + data.response.code : '';
        var _detail = (data.details || data.type || 'unknown') + _code;
        try { console.warn('HLS fatal error:', data); } catch (e) {}
        try { hlsInstance.destroy(); } catch (e) {}
        hlsInstance = null;

        /* Manifest/network fail (CORS ya hls.js issue) -> browser ke native HLS se ek baar try.
           <video src> par CORS lagta nahi, isliye Android Chrome par aksar chal jata hai. */
        if (!player && _nativeTriedUrl !== url) {
          _nativeTriedUrl = url;
          showToast('HLS fail (' + _detail + ') \u2014 native player try kar raha hoon\u2026', 'warn', 2600);
          videoEl.src = url;
          player = new Plyr(videoEl, plyrOpts);
          _attachEvents(startTime);
          return;
        }

        setLoading(false);
        showError('Video load nahi ho saki [' + _detail + ']. Direct link se khol kar dekh lo.');
        showToast('Stream error: ' + _detail, 'error');
      }
    });

  } else if (isHLS && videoEl.canPlayType('application/vnd.apple.mpegurl')) {
    videoEl.src = url;
    player = new Plyr(videoEl, plyrOpts);
    _attachEvents(startTime);

  } else {
    videoEl.src = url;
    player = new Plyr(videoEl, plyrOpts);
    _attachEvents(startTime);
  }
}

function updateQuality(quality) {
  if (!hlsInstance) return;
  if (quality === 0) {
    hlsInstance.currentLevel = -1;
  } else {
    for (var i = 0; i < hlsInstance.levels.length; i++) {
      if (hlsInstance.levels[i].height === quality) {
        hlsInstance.currentLevel = i;
        break;
      }
    }
  }
}

/* ═══════════════════════════════════
   DOUBLE-TAP / DOUBLE-CLICK SEEK
═══════════════════════════════════ */
var _lastTapTime = 0;

function sanitizeId(str) {
    return str.replace(/[^a-zA-Z0-9]/g, '_');
}

/* ── Lazy Rendering ── */
function renderLecturesForSubject(subIdx) {
  if (renderedSubjects[subIdx]) return;

  var header = document.querySelector('.accordion-header[data-subidx="' + subIdx + '"]');
  if (!header) return;
  var contentId = header.getAttribute('aria-controls');
  var content = document.getElementById(contentId);
  if (!content) return;

  var subjectLectures = LECTURES.filter(function(l) { return l.subIdx === subIdx; });
  var direct = subjectLectures.filter(function(l) { return l.topic === null; });
  var topics = {};
  subjectLectures.forEach(function(l) {
    if (l.topic) {
      if (!topics[l.topic]) topics[l.topic] = [];
      topics[l.topic].push(l);
    }
  });

  // Render direct lectures
  var directDiv = document.getElementById('direct-' + subIdx);
  if (directDiv && direct.length > 0) {
    var html = '';
    direct.forEach(function(lec) {
      html += _renderLectureHTML(lec, globalLectureIdx++);
    });
    directDiv.innerHTML = html;
  }

  // Render each topic
  for (var tname in topics) {
    var tid = 'topic-' + subIdx + '-' + sanitizeId(tname);
    var topicDiv = document.getElementById(tid);
    if (topicDiv) {
      var html = '';
      topics[tname].forEach(function(lec) {
        html += _renderLectureHTML(lec, globalLectureIdx++);
      });
      topicDiv.innerHTML = html;
    }
  }

  renderedSubjects[subIdx] = true;
  updateWatchedUI(); // apply watched state to newly rendered lectures
  updateStarUI();    // apply favorite state to newly rendered lectures
}


function htmlAttrEscape(str) {
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


function _renderLectureHTML(lec, gidx) {
  var title = lec.title;
  var lid = lec.lid;
  var videos = lec.videos;
  var pdfs = lec.pdfs;
  var et = title;
  var eta = htmlAttrEscape(title);
  var multi = videos.length > 1;

  var videoLinks = '';
  for (var i = 0; i < videos.length; i++) {
    var vurl = videos[i];
    var ytId = _getYtId(vurl);
    var isYt = !!ytId;
    var isProbablyYt = !isYt && (vurl.indexOf('youtube.com/') !== -1 || vurl.indexOf('youtu.be/') !== -1);
    var label = multi ? 'Part ' + (i+1) + ' &#9654;' : (isYt || isProbablyYt ? '&#9654;&nbsp;YouTube' : '&#9654;&nbsp;Play');
    var extraCls = (isYt || isProbablyYt) ? ' yt-item' : '';
    var dataPart = isYt ? 'data-yt="' + htmlAttrEscape(ytId) + '"' : 'data-url="' + htmlAttrEscape(vurl) + '"';
    var ariaLbl = isYt ? 'Watch on YouTube: ' + eta : (isProbablyYt ? 'Open YouTube link: ' + eta : 'Play ' + eta + (multi ? ' part ' + (i+1) : ''));
    videoLinks += '<a href="#" class="list-item video-item' + extraCls + '" role="button" tabindex="0" ' +
      dataPart + ' data-lid="' + lid + '" data-title="' + eta + '" data-gidx="' + gidx + '" ' +
      'aria-label="' + ariaLbl + '" onclick="playVideo(event,this)" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();playVideo(event,this);}">' + label + '</a>';
  }

  var pdfLinks = '';
  for (var j = 0; j < pdfs.length; j++) {
    var eu = htmlAttrEscape(pdfs[j]);
    pdfLinks += '<a href="' + eu + '" target="_blank" rel="noopener noreferrer" class="list-item pdf-item" ' +
      'data-url="' + eu + '" data-title="' + eta + '" ' +
      'aria-label="Open PDF for ' + eta + '" ' +
      'onclick="openPdfModal(this.dataset.url,this.dataset.title);event.preventDefault();">' +
      '<i class="fa-solid fa-file-pdf" aria-hidden="true"></i>&nbsp;PDF</a>';
  }

  var watchBtn = '<button class="watch-btn" data-lid="' + lid + '" onclick="toggleWatched(\'' + lid + '\')" aria-label="Mark as watched" aria-pressed="false" title="Mark watched">&#9675;</button>';
  var starBtn  = '<button class="star-btn" data-lid="' + lid + '" onclick="toggleStar(\'' + lid + '\')" aria-label="Add to favorites" aria-pressed="false" title="Favorite"><i class="fa-solid fa-star" aria-hidden="true"></i></button>';
  var copyBtn = videos.length ? '<button class="copy-btn" data-lid="' + lid + '" onclick="copyLectureLink(\'' + lid + '\')" aria-label="Copy link" title="Copy link"><i class="fa-solid fa-link" aria-hidden="true"></i></button>' : '';

  return '<div class="lecture-entry" data-lid="' + lid + '" data-gidx="' + gidx + '">' +
    '<div class="lecture-meta">' + watchBtn + starBtn + '<p class="lecture-title" data-title="' + eta + '">' + et + '</p>' + copyBtn + '</div>' +
    '<div class="lecture-links">' + videoLinks + pdfLinks + '</div></div>';
}

function _setupDoubleTapSeek() {
  var wrapper = document.querySelector('.player-wrapper');
  if (!wrapper) return;

  wrapper.addEventListener('dblclick', function (e) {
    if (e.target.closest('.plyr__controls')) return;
    e.preventDefault();
    if (!player || !isPlayerReady) return;
    var rect = wrapper.getBoundingClientRect();
    var x    = e.clientX - rect.left;
    x < rect.width / 2 ? player.rewind(10) : player.forward(10);
    showToast(x < rect.width / 2 ? '⏪ -10s' : '⏩ +10s', 'info', 900);
  });

  wrapper.addEventListener('touchend', function (e) {
    if (e.target.closest('.plyr__controls')) return;
    var now  = Date.now();
    var diff = now - _lastTapTime;
    if (diff > 0 && diff < 300 && _lastTapTime > 0) {
      e.preventDefault();
      if (player && isPlayerReady) {
        var rect = wrapper.getBoundingClientRect();
        var x    = e.changedTouches[0].clientX - rect.left;
        x < rect.width / 2 ? player.rewind(10) : player.forward(10);
        showToast(x < rect.width / 2 ? '⏪ -10s' : '⏩ +10s', 'info', 900);
      }
      _lastTapTime = 0;
    } else {
      _lastTapTime = now;
      setTimeout(function () { _lastTapTime = 0; }, 310);
    }
  }, { passive: false });
}

/* ═══════════════════════════════════
   KEYBOARD SHORTCUTS
═══════════════════════════════════ */
function _initKeyboard() {
  document.addEventListener('keydown', function (e) {
    var tag = document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement.isContentEditable) return;

    switch (e.code) {
      case 'Space':
        if (player && isPlayerReady) { e.preventDefault(); player.togglePlay(); }
        break;
      case 'KeyF':
        if (player && isPlayerReady) player.fullscreen.toggle();
        break;
      case 'ArrowLeft':
        if (player && isPlayerReady) { e.preventDefault(); player.rewind(10); showToast('⏪ -10s','info',900); }
        break;
      case 'ArrowRight':
        if (player && isPlayerReady) { e.preventDefault(); player.forward(10); showToast('⏩ +10s','info',900); }
        break;
      case 'ArrowUp':
        if (player && isPlayerReady) { e.preventDefault(); player.increaseVolume(0.1); }
        break;
      case 'ArrowDown':
        if (player && isPlayerReady) { e.preventDefault(); player.decreaseVolume(0.1); }
        break;
      case 'KeyM':
        if (player && isPlayerReady) { player.muted = !player.muted; showToast(player.muted ? '🔇 Muted' : '🔊 Unmuted','info',900); }
        break;
      case 'KeyD':
        toggleDark();
        break;
      case 'KeyN':
        playNext();
        break;
      case 'KeyP':
        playPrev();
        break;
      case 'KeyE':
        expandAll();
        break;
      case 'KeyC':
        collapseAll();
        break;
      case 'Slash':
        e.preventDefault();
        var si = document.getElementById('searchInput');
        if (si) si.focus();
        break;
    }
  });
}

/* ═══════════════════════════════════
   ACCORDIONS
═══════════════════════════════════ */
function _initAccordions() {
  document.querySelectorAll('.accordion-header').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var isActive = btn.classList.contains('active');
      document.querySelectorAll('.accordion-header').forEach(function (b) {
        if (b !== btn) {
          b.classList.remove('active');
          b.setAttribute('aria-expanded', 'false');
          var c = b.nextElementSibling;
          c.classList.remove('open');
          c.style.maxHeight = null;
        }
      });
      if (!isActive) {
        // Lazy render subject on first expand
        var subIdx = parseInt(btn.getAttribute('data-subidx'));
        if (!isNaN(subIdx) && !renderedSubjects[subIdx]) {
          renderLecturesForSubject(subIdx);
        }
        btn.classList.add('active');
        btn.setAttribute('aria-expanded', 'true');
        var content = btn.nextElementSibling;
        content.classList.add('open');
        content.style.maxHeight = content.scrollHeight + 'px';
        content.addEventListener('transitionend', function fix() {
          content.removeEventListener('transitionend', fix);
          if (btn.classList.contains('active')) {
            content.style.maxHeight = 'none';
          }
        }, { once: true });
      } else {
        btn.classList.remove('active');
        btn.setAttribute('aria-expanded', 'false');
        var content2 = btn.nextElementSibling;
        content2.style.maxHeight = content2.scrollHeight + 'px';
        requestAnimationFrame(function () {
          content2.style.maxHeight = null;
          content2.classList.remove('open');
        });
      }
    });
  });

  document.querySelectorAll('.topic-header').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var isActive = btn.classList.contains('active');
      var pc       = btn.closest('.accordion-content');

      if (pc) {
        pc.querySelectorAll('.topic-header').forEach(function (b) {
          if (b !== btn) {
            b.classList.remove('active');
            b.setAttribute('aria-expanded', 'false');
            b.nextElementSibling.style.maxHeight = null;
          }
        });
      }

      if (!isActive) {
        btn.classList.add('active');
        btn.setAttribute('aria-expanded', 'true');
        var tc = btn.nextElementSibling;
        tc.style.maxHeight = tc.scrollHeight + 'px';

        if (pc) {
          var subHeader = pc.previousElementSibling;
          if (subHeader && !subHeader.classList.contains('active')) {
            subHeader.classList.add('active');
            subHeader.setAttribute('aria-expanded', 'true');
            pc.classList.add('open');
          }
          pc.style.maxHeight = 'none';
        }
      } else {
        btn.classList.remove('active');
        btn.setAttribute('aria-expanded', 'false');
        btn.nextElementSibling.style.maxHeight = null;
      }
    });
  });
}

/* ═══════════════════════════════════
   SETTINGS
═══════════════════════════════════ */
function loadSettings() {
  try {
    var raw = localStorage.getItem('bbk_settings');
    if (raw) {
      var saved = JSON.parse(raw);
      for (var k in saved) { if (k in SETTINGS) SETTINGS[k] = saved[k]; }
    }
  } catch (e) {}
  // Reflect into UI controls if the modal markup exists
  var el;
  if ((el = document.getElementById('set-autonext')))   el.checked = SETTINGS.autoNextEnabled;
  if ((el = document.getElementById('set-autoseconds'))) el.value  = SETTINGS.autoNextSeconds;
  if ((el = document.getElementById('set-speed')))       el.value  = String(SETTINGS.defaultSpeed);
  if ((el = document.getElementById('set-dark')))        el.checked = document.documentElement.classList.contains('dark');
  if ((el = document.getElementById('set-pip')))         el.checked = SETTINGS.autoPip;
}
function saveSettingsFromForm() {
  var el;
  if ((el = document.getElementById('set-autonext')))   SETTINGS.autoNextEnabled = el.checked;
  if ((el = document.getElementById('set-autoseconds'))) SETTINGS.autoNextSeconds = Math.max(1, parseInt(el.value, 10) || 5);
  if ((el = document.getElementById('set-speed')))       SETTINGS.defaultSpeed    = parseFloat(el.value) || 1;
  if ((el = document.getElementById('set-pip')))         SETTINGS.autoPip         = el.checked;
  try { localStorage.setItem('bbk_settings', JSON.stringify(SETTINGS)); } catch (e) {}

  // Dark mode default — single source of truth is the existing 'bbk_dark' key
  if ((el = document.getElementById('set-dark'))) {
    var wantDark = el.checked;
    var isDark   = document.documentElement.classList.contains('dark');
    if (wantDark !== isDark) toggleDark();
  }

  showToast('Settings save ho gayi \u2713', 'success');
  closeSettings();
}
function openSettings() {
  var m = document.getElementById('settings-modal');
  if (m) { m.classList.add('open'); document.body.style.overflow = 'hidden'; }
}
function closeSettings() {
  var m = document.getElementById('settings-modal');
  if (m) { m.classList.remove('open'); document.body.style.overflow = ''; }
}

/* ═══════════════════════════════════
   AUTO PICTURE-IN-PICTURE
═══════════════════════════════════ */
function _initAutoPip() {
  if (!('pictureInPictureEnabled' in document)) return;
  document.addEventListener('visibilitychange', function () {
    var videoEl = document.getElementById('player');
    if (!videoEl) return;
    if (document.hidden) {
      if (SETTINGS.autoPip && player && isPlayerReady && !videoEl.paused &&
          document.pictureInPictureElement !== videoEl) {
        videoEl.requestPictureInPicture().catch(function () {});
      }
    } else {
      if (document.pictureInPictureElement === videoEl) {
        document.exitPictureInPicture().catch(function () {});
      }
    }
  });
}

/* ═══════════════════════════════════
   PDF MODAL
═══════════════════════════════════ */
var _pdfCurrentUrl = null;
function openPdfModal(url, title) {
  _pdfCurrentUrl = url;
  var modal  = document.getElementById('pdf-modal');
  var frame  = document.getElementById('pdf-frame');
  var titleEl = document.getElementById('pdf-modal-title');
  var openTab = document.getElementById('pdf-open-tab');
  var dlBtn   = document.getElementById('pdf-download');
  if (titleEl) titleEl.textContent = title || 'PDF';
  if (frame)   frame.src = url;
  if (openTab) openTab.href = url;
  if (dlBtn)   dlBtn.href = url;
  if (modal)   { modal.classList.add('open'); document.body.style.overflow = 'hidden'; }
}
function closePdfModal() {
  var modal = document.getElementById('pdf-modal');
  var frame = document.getElementById('pdf-frame');
  if (frame) frame.src = 'about:blank';
  if (modal) { modal.classList.remove('open'); document.body.style.overflow = ''; }
  _pdfCurrentUrl = null;
}
function pdfModalFullscreen() {
  var frame = document.getElementById('pdf-frame');
  if (frame && frame.requestFullscreen) frame.requestFullscreen().catch(function () {});
}

/* ═══════════════════════════════════
   INIT
═══════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function () {
  loadSettings();
  initDarkMode();
  loadWatched();
  loadStars();
  checkResume();
  _initAccordions();
  _initKeyboard();
  _setupDoubleTapSeek();
  _initAutoPip();

  document.querySelectorAll('.modal-overlay').forEach(function (ov) {
    ov.addEventListener('click', function (e) {
      if (e.target === ov) {
        if (ov.id === 'settings-modal') closeSettings();
        if (ov.id === 'pdf-modal') closePdfModal();
      }
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeSettings(); closePdfModal(); }
  });
});
"""


def _build_js(file_key: str) -> str:
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", file_key)[:48]
    return (
        "const FILE_KEY = " + json.dumps(safe_key) + ";\n"
        + _JS_BODY
        + "\n"
        + _DRAWER_JS
    )


# ═══════════════════════════════════════════════════════════════════════════
#  ANTI-FOUC
# ═══════════════════════════════════════════════════════════════════════════

_ANTI_FOUC_JS = textwrap.dedent("""\
    (function(){
      try{
        if(localStorage.getItem('bbk_dark')==='1'){
          document.documentElement.classList.add('dark');
        }
      }catch(e){}
    })();
""")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
import json as _json

def _lectures_to_json(structured):
    """Flat list of lectures with subIdx and topic info."""
    data = []
    for sub_idx, sub in enumerate(structured):
        for lec in sub.get("direct_lectures", []):
            data.append({
                "subIdx": sub_idx,
                "topic": None,
                "videos": lec["videos"],
                "pdfs": lec["pdfs"],
                "title": lec["title"],
                "lid": lec["lid"]
            })
        for tname, tdata in sub.get("topics", {}).items():
            for lec in tdata["lectures"]:
                data.append({
                    "subIdx": sub_idx,
                    "topic": tname,
                    "videos": lec["videos"],
                    "pdfs": lec["pdfs"],
                    "title": lec["title"],
                    "lid": lec["lid"]
                })
    return data
    
    
def generate_html(file_name: str, structured_list: list) -> str:
    content_html = _build_content_html(structured_list)
    total        = count_total_lectures(structured_list)
    js           = _build_js(file_name)
    ename        = html.escape(file_name)

    subject_options = '<option value="">All Subjects</option>' + "".join(
        f'<option value="{i}">{html.escape(sub["name"])}</option>'
        for i, sub in enumerate(structured_list)
    )

    lines = [
        '<!DOCTYPE html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">',
        '<meta name="theme-color" content="#0f172a">',
        f'<title>{ename}</title>',
        f'<script>{_ANTI_FOUC_JS}</script>',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.6.0/css/all.min.css">',
        '<link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css">',
        f'<style>{_CSS}</style>',
        f'<style>{_DRAWER_CSS}</style>',
        '</head>',
        '<body>',

        '<div id="toast-container" aria-live="polite" aria-atomic="false"></div>',
        _DRAWER_HTML,

        # ── Header ──
        '<header class="header" role="banner">',
        f'  <span class="header-title">{ename}</span>',
        '  <div class="header-controls">',
        '    <button onclick="expandAll()" class="ctrl-btn" title="Expand all (E)" aria-label="Expand all">\u229e</button>',
        '    <button onclick="collapseAll()" class="ctrl-btn" title="Collapse all (C)" aria-label="Collapse all">\u229f</button>',
        '    <button onclick="toggleDark()" class="ctrl-btn" id="darkBtn" title="Toggle dark mode (D)" aria-label="Toggle dark mode">\U0001f319</button>',
        '    <button onclick="openSettings()" class="ctrl-btn" title="Settings" aria-label="Open settings"><i class="fa-solid fa-gear" aria-hidden="true"></i></button>',
        '    <button class="kk-drawer-toggle" id="kk-drawer-toggle"',
        '      aria-label="Open menu" aria-expanded="false" aria-haspopup="true">',
        '      <span></span><span></span><span></span>',
        '    </button>',
        '  </div>',
        '</header>',

        '<div class="progress-bar-track" role="progressbar" aria-label="Overall progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">',
        '  <div class="progress-bar-fill" id="progress-fill"></div>',
        '</div>',

        '<main class="main-container" id="main-content">',

        '  <div class="player-wrapper" id="player-wrapper">',
        '    <video id="player" playsinline controls preload="none"',
        '      aria-label="Lecture video player"></video>',
        '    <div class="player-loading" id="player-loading" aria-live="polite" aria-label="Loading video">',
        '      <div class="spinner" role="status"></div>',
        '    </div>',
        '    <div class="player-error" id="player-error" role="alert">',
        '      <div class="player-error-title">\u26a0\ufe0f Failed to load video</div>',
        '      <p id="player-error-msg">An error occurred while loading the video.</p>',
        '      <button class="retry-btn" onclick="retryVideo()">\u21ba Retry</button>',
        '      <a class="retry-btn open-link-btn" id="player-error-link" href="#" target="_blank" rel="noopener" style="display:none">\U0001f517 Direct Link Kholo</a>',
        '    </div>',
        '  </div>',   # end .player-wrapper

        # ── YouTube embed (shown instead of Plyr for YouTube URLs) ──
        '<div class="yt-embed-wrapper" id="yt-embed-wrapper">',
        '  <iframe id="yt-frame" src=""',
        '    allow="autoplay; fullscreen; encrypted-media; picture-in-picture"',
        '    referrerpolicy="no-referrer-when-downgrade"',
        '    allowfullscreen',
        '    aria-label="YouTube video player"></iframe>',
        '  <a id="yt-open-link" class="yt-open-link" href="#" target="_blank" rel="noopener">',
        '    &#9654; Open in YouTube',
        '  </a>',
        '</div>',

        '  <div id="now-playing" class="now-playing" aria-live="polite">',
        '    <span class="now-playing-dot" aria-hidden="true"></span>',
        '    <span class="now-playing-title" id="now-playing-title"></span>',
        '    <div class="now-playing-nav">',
        '      <button class="nav-btn" id="btn-prev" onclick="playPrev()" disabled',
        '        title="Previous (P)" aria-label="Previous lecture">\u276e Prev</button>',
        '      <button class="nav-btn" id="btn-next" onclick="playNext()"',
        '        title="Next (N)" aria-label="Next lecture">Next \u276f</button>',
        '    </div>',
        '  </div>',

        '  <div id="autonext-banner" class="autonext-banner" role="status">',
        '    <div class="autonext-count" id="autonext-count">5</div>',
        '    <div class="autonext-label" id="autonext-label">Loading next…</div>',
        '    <button class="autonext-play" onclick="playAutoNext()">\u25b6 Play Now</button>',
        '    <button class="autonext-cancel" onclick="cancelAutoNext()">\u2715 Cancel</button>',
        '  </div>',

        '  <div id="resume-banner" class="resume-banner" role="status">',
        '    <span id="resume-text"></span>',
        '    <button class="resume-btn" onclick="resumeVideo()">\u25b6 Resume</button>',
        '    <button class="resume-dismiss" onclick="dismissResume()" aria-label="Dismiss">\u2715</button>',
        '  </div>',

        '  <div class="search-wrap" role="search">',
        '    <i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i>',
        '    <input class="search-input" type="search" id="searchInput"',
        '      placeholder="Search lectures\u2026 (press /)" autocomplete="off"',
        '      aria-label="Search lectures"',
        '      oninput="filterContent(this.value)">',
        '    <button class="search-clear" id="search-clear"',
        '      onclick="clearSearch()" aria-label="Clear search">\u2715</button>',
        '  </div>',

        '  <div class="filter-chips" role="group" aria-label="Filter lectures">',
        '    <button class="filter-chip active" data-filter="all" onclick="setWatchFilter(\'all\')">All</button>',
        '    <button class="filter-chip" data-filter="unwatched" onclick="setWatchFilter(\'unwatched\')">\u25cb Unwatched</button>',
        '    <button class="filter-chip" data-filter="watched" onclick="setWatchFilter(\'watched\')">\u2713 Watched</button>',
        f'    <select id="subjectFilter" class="subject-filter-select" onchange="setSubjectFilter(this.value)" aria-label="Filter by subject">{subject_options}</select>',
        '  </div>',

        '  <div class="toolbar" role="toolbar" aria-label="Lecture info">',
        f'    <span class="badge" aria-label="{total} total lectures">{total} lectures</span>',
        '    <span class="badge badge-result" id="search-result-count" style="display:none" aria-live="polite"></span>',
        '    <span class="badge badge-progress" id="progress-badge" aria-live="polite"></span>',
        '  </div>',

        f'  <div id="content-container" role="list" aria-label="Course content">{content_html}</div>',
        '</main>',

        # ── Settings Modal ──
        '<div class="modal-overlay" id="settings-modal" role="dialog" aria-modal="true" aria-label="Settings">',
        '  <div class="modal-box">',
        '    <div class="modal-header">',
        '      <span class="modal-title"><i class="fa-solid fa-gear" aria-hidden="true"></i>&nbsp; Settings</span>',
        '      <button class="modal-close" onclick="closeSettings()" aria-label="Close">\u2715</button>',
        '    </div>',
        '    <div class="modal-body">',

        '      <div class="setting-row">',
        '        <div><div class="setting-label">Auto-next lecture</div>',
        '          <div class="setting-hint">Video khatam hote hi agla lecture chale</div></div>',
        '        <label class="switch"><input type="checkbox" id="set-autonext" checked>',
        '          <span class="switch-track"></span></label>',
        '      </div>',

        '      <div class="setting-row">',
        '        <div><div class="setting-label">Auto-next delay</div>',
        '          <div class="setting-hint">Countdown seconds agle video se pehle</div></div>',
        '        <div class="setting-control"><input type="number" id="set-autoseconds" min="1" max="30" value="5"></div>',
        '      </div>',

        '      <div class="setting-row">',
        '        <div><div class="setting-label">Default playback speed</div>',
        '          <div class="setting-hint">Har naye video ki default speed</div></div>',
        '        <div class="setting-control"><select id="set-speed">',
        '          <option value="0.5">0.5x</option><option value="0.75">0.75x</option>',
        '          <option value="1" selected>1x (Normal)</option><option value="1.25">1.25x</option>',
        '          <option value="1.5">1.5x</option><option value="1.75">1.75x</option>',
        '          <option value="2">2x</option>',
        '        </select></div>',
        '      </div>',

        '      <div class="setting-row">',
        '        <div><div class="setting-label">Dark mode by default</div>',
        '          <div class="setting-hint">App khulte hi dark theme lagi rahe</div></div>',
        '        <label class="switch"><input type="checkbox" id="set-dark">',
        '          <span class="switch-track"></span></label>',
        '      </div>',

        '      <div class="setting-row">',
        '        <div><div class="setting-label">Auto Picture-in-Picture</div>',
        '          <div class="setting-hint">Tab switch karte hi video floating ho jaaye</div></div>',
        '        <label class="switch"><input type="checkbox" id="set-pip" checked>',
        '          <span class="switch-track"></span></label>',
        '      </div>',

        '      <button class="modal-save-btn" onclick="saveSettingsFromForm()">Save Settings</button>',
        '    </div>',
        '  </div>',
        '</div>',

        # ── PDF Modal ──
        '<div class="modal-overlay" id="pdf-modal" role="dialog" aria-modal="true" aria-label="PDF viewer">',
        '  <div class="modal-box pdf-modal-box">',
        '    <div class="modal-header">',
        '      <span class="modal-title" id="pdf-modal-title"><i class="fa-solid fa-file-pdf" aria-hidden="true"></i>&nbsp; PDF</span>',
        '      <button class="modal-close" onclick="closePdfModal()" aria-label="Close">\u2715</button>',
        '    </div>',
        '    <div class="pdf-modal-body">',
        '      <iframe id="pdf-frame" src="about:blank" title="PDF document"></iframe>',
        '    </div>',
        '    <div class="pdf-modal-actions">',
        '      <a id="pdf-open-tab" class="pdf-action-btn" href="#" target="_blank" rel="noopener">',
        '        <i class="fa-solid fa-up-right-from-square" aria-hidden="true"></i> Naye Tab Mein Kholo</a>',
        '      <a id="pdf-download" class="pdf-action-btn" href="#" download target="_blank" rel="noopener">',
        '        <i class="fa-solid fa-download" aria-hidden="true"></i> Download</a>',
        '      <button class="pdf-action-btn" onclick="pdfModalFullscreen()">',
        '        <i class="fa-solid fa-expand" aria-hidden="true"></i> Fullscreen</button>',
        '      <button class="pdf-action-btn" onclick="closePdfModal()">',
        '        <i class="fa-solid fa-xmark" aria-hidden="true"></i> Close</button>',
        '    </div>',
        '  </div>',
        '</div>',

        # ── Footer — Telegram link, text "Babu Bhai Kundan" ──
        '<footer class="footer-wrap">',
        '  <a class="footer-credit-btn" href="https://t.me/BabuBhaiKundan"',
        '     target="_blank" rel="noopener noreferrer" aria-label="Telegram: Babu Bhai Kundan">',
        '    <i class="fa-brands fa-telegram" aria-hidden="true" style="color:#29b5e8;font-size:18px"></i>',
        '    <span style="color:#ffffff;font-weight:800;font-size:14px">Babu Bhai Kundan</span>',
        '  </a>',
        '  <p class="shortcut-hint">',
        '    <kbd>Space</kbd>=play/pause &nbsp;|&nbsp;',
        '    <kbd>F</kbd>=fullscreen &nbsp;|&nbsp;',
        '    <kbd>&larr;&rarr;</kbd>=&plusmn;10s &nbsp;|&nbsp;',
        '    <kbd>&uarr;&darr;</kbd>=volume &nbsp;|&nbsp;',
        '    <kbd>M</kbd>=mute &nbsp;|&nbsp;',
        '    <kbd>N</kbd>=next &nbsp;|&nbsp;',
        '    <kbd>P</kbd>=prev &nbsp;|&nbsp;',
        '    <kbd>D</kbd>=dark &nbsp;|&nbsp;',
        '    <kbd>/</kbd>=search',
        '  </p>',
        '</footer>',

        '<script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>',
        
        '<script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>',
        f'<script>var LECTURES = {_json.dumps(_lectures_to_json(structured_list), ensure_ascii=False)};</script>',
        f'<script>{js}</script>',
        '</body>',
        '</html>',
    ]

    return "\n".join(lines)
