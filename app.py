from flask import Flask, request, jsonify, render_template_string, session, Response
import os
import re
import uuid
import html
import base64
import time
import requests
from groq import Groq

app = Flask(__name__)
# Pulled from the environment in production; the fallback only runs locally.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB safety cap

_groq_client = None


def client_chat(**kwargs):
    """Lazily build the Groq client so the site still boots before the key is set."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    return _groq_client.chat.completions.create(**kwargs)

# ---------------------------------------------------------------------------
# BUSINESS DETAILS  --  edit these in one place if anything ever changes
# ---------------------------------------------------------------------------
BUSINESS = {
    "name": "A&J Property Maintenance Solutions",
    "short": "A&J",
    "owner": "the A&J team",          # put the owner's first name here for a personal sign-off
    "phone_display": "07378 571162",
    "phone_e164": "447378571162",     # used for tel: and WhatsApp links
    "email_public": "Klontian12@gmail.com",  # shown on the site
    "area_line": "Portsmouth, Southampton, Bournemouth & Guildford",
    "postcode": "PO1 5JA",
    "instagram": "https://instagram.com/ajpropertym",
    "facebook": "https://facebook.com/share/1G9Pn4snuv/",
}

# Where lead emails are sent. Set NOTIFY_TO in your environment.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
NOTIFY_TO = os.environ.get("NOTIFY_TO", "Klontian12@gmail.com")
# The "from" address must be on a domain you've verified in Resend. While you're
# testing you can use Resend's shared sender below; swap to your domain later.
MAIL_FROM = os.environ.get("MAIL_FROM", "A&J Website <onboarding@resend.dev>")

# --- Photo upload settings ---
MAX_IMAGES_PER_SESSION = 6
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 6 * 1024 * 1024

# ---------------------------------------------------------------------------
# SERVICES  --  drives the "What we do" grid
# ---------------------------------------------------------------------------
def _icon(path):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            + path + '</svg>')

SERVICES = [
    {"title": "Bathrooms & Wet Rooms",
     "desc": "Full bathroom installs from strip-out to finish — tiling, suites, walk-in showers and wet rooms.",
     "icon": _icon('<path d="M4 12h16v3a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z"/><path d="M6 12V6a2 2 0 0 1 2-2h1"/><path d="M9 5l2 2"/>')},
    {"title": "Kitchens",
     "desc": "Supply and fit, worktops, splashbacks and full kitchen refits finished to a high standard.",
     "icon": _icon('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M7 6h.01M11 6h.01"/>')},
    {"title": "Painting & Decorating",
     "desc": "Interior and exterior painting, wallpapering, feature walls and panelling, cleanly cut in.",
     "icon": _icon('<path d="M3 7h14a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2h-7"/><path d="M10 13v4a2 2 0 0 1-2 2H7"/><rect x="3" y="4" width="4" height="6" rx="1"/>')},
    {"title": "Tiling",
     "desc": "Walls and floors — herringbone, large-format, mosaic and natural stone laid precisely.",
     "icon": _icon('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>')},
    {"title": "Paving & Landscaping",
     "desc": "Patios, porcelain paving, steps, turfing and full garden transformations.",
     "icon": _icon('<path d="M3 20l4-9 4 5 3-4 7 8z"/><circle cx="8" cy="6" r="2"/>')},
    {"title": "Groundwork & Concreting",
     "desc": "Bases, footings, retaining walls and drainage — the solid stuff done properly.",
     "icon": _icon('<path d="M3 17h18"/><path d="M5 17l2-5h10l2 5"/><path d="M9 12V8h6v4"/>')},
    {"title": "Fencing & Joinery",
     "desc": "Fencing, gates, bespoke worktops, panelling and general carpentry.",
     "icon": _icon('<path d="M4 21V8l3-3 3 3v13"/><path d="M14 21V8l3-3 3 3v13"/><path d="M2 12h20"/>')},
    {"title": "Plumbing & Electrical",
     "desc": "Qualified plumbing and certified electrical work — repairs, installs and fault finding.",
     "icon": _icon('<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>')},
    {"title": "Handyman & Repairs",
     "desc": "Odd jobs, flat-pack, shelving, repairs — no job too small to keep things ticking over.",
     "icon": _icon('<path d="M14 7l3 3-7 7-3-3z"/><path d="M17 10l3-3a3 3 0 0 0-4-4l-3 3"/><path d="M7 14l-4 4 3 3 4-4"/>')},
]

# ---------------------------------------------------------------------------
# PORTFOLIO  --  to add more photos: drop the file in static/images/portfolio/
# and add a line here. "cat" must match one of the FILTERS below.
# ---------------------------------------------------------------------------
P = "static/images/portfolio/"
PORTFOLIO = [
    {"img": P+"large-patio-porcelain.jpg",        "cat": "Paving & Gardens", "cap": "Large-format porcelain patio, freshly laid"},
    {"img": P+"stone-patio-curved-steps.jpg",     "cat": "Paving & Gardens", "cap": "Stone patio with curved steps and brick edging"},
    {"img": P+"raised-porcelain-patio.jpg",       "cat": "Paving & Gardens", "cap": "Raised porcelain patio with timber sleepers"},
    {"img": P+"patio-artificial-grass.jpg",       "cat": "Paving & Gardens", "cap": "Patio and artificial grass garden finish"},
    {"img": P+"large-format-patio.jpg",           "cat": "Paving & Gardens", "cap": "Clean large-format garden patio"},
    {"img": P+"side-path-porcelain-tiles.jpg",    "cat": "Paving & Gardens", "cap": "Side path finished with porcelain tiles"},
    {"img": P+"doorstep-patio-detail.jpg",        "cat": "Paving & Gardens", "cap": "Patio and doorstep detail"},
    {"img": P+"block-paving-driveway.jpg",        "cat": "Driveways",        "cap": "Block paving driveway with red border"},
    {"img": P+"composite-fence-front.jpg",        "cat": "Exterior",         "cap": "Composite front fencing on brick wall"},
    {"img": P+"victorian-front-step.jpg",         "cat": "Tiling",           "cap": "Front step tiled with patterned border"},
    {"img": P+"patterned-utility-tiles.jpg",      "cat": "Tiling",           "cap": "Patterned utility room floor tiles"},
    {"img": P+"garden-swing-base.jpg",            "cat": "Building",         "cap": "Garden base ready for a swing frame"},
    {"img": P+"concrete-base-prep.jpg",           "cat": "Building",         "cap": "Concrete base preparation with reinforcement"},
    {"img": P+"concrete-base-finished.jpg",       "cat": "Building",         "cap": "Finished concrete base"},
]
FILTERS = ["All", "Paving & Gardens", "Tiling", "Driveways", "Building", "Exterior"]

# ---------------------------------------------------------------------------
# HERO VIDEO  --  the single biggest "wow" lever. Drop one of his best clips
# (landscape, ~10-25s) in static/videos/ and set the filename below. It plays
# muted, looped, full-screen behind the headline. Leave "" to use a photo.
# Example:  HERO_VIDEO = "static/videos/hero-reel.mp4"
# ---------------------------------------------------------------------------
HERO_VIDEO = ""

# ---------------------------------------------------------------------------
# VIDEOS  --  add clips to static/videos/ then list them here. Leave empty to
# hide the whole section. Example:
#   {"src": "static/videos/bathroom-reveal.mp4", "poster": P+"bathroom-black-marble-bath.webp", "cap": "Bathroom reveal"}
# ---------------------------------------------------------------------------
VIDEOS = [
    {"src": "static/videos/reel-bathroom-transformation.mp4",
     "poster": P+"reel-bathroom-poster.jpg",
     "cap": "Old bathroom to modern design — full transformation"},
    {"src": "static/videos/reel-wallpaper.mp4",
     "poster": P+"reel-wallpaper-poster.jpg",
     "cap": "Feature wall — wallpaper hung start to finish"},
    {"src": "static/videos/reel-porcelain-patio.mp4",
     "poster": P+"reel-patio-poster.jpg",
     "cap": "Grey porcelain patio, freshly laid"},
    {"src": "static/videos/reel-patio-laying.mp4",
     "poster": P+"reel-laying-poster.jpg",
     "cap": "New patio going down — base to finish"},
]

# ---------------------------------------------------------------------------
# REVIEWS  --  the two below are the real reviews from the current site.
# Paste your Google reviews in the same format and they'll appear automatically.
# ---------------------------------------------------------------------------
REVIEWS = [
    {"text": "I highly recommend Klod. He installed drainage in my back garden and refreshed my garden slabs last year. I asked him back again to install my kitchen extractor. Friendly, professional, reliable and always helpful.",
     "name": "Jessie Hoang", "where": "Google review"},
    {"text": "A&J recently completed a job at my house and did an amazing job. He took care of the landscaping and necessary work with impressive efficiency and reliability. The result was outstanding.",
     "name": "Annie Barone", "where": "Google review"},
    {"text": "Amazing guys. Did our porch today and did an incredible job. Highly recommend. Very kind people as well.",
     "name": "Ann Shahid", "where": "Google review"},
    {"text": "Brilliant work fixing flood damage to a bedroom. They fitted me in quickly while still taking time to do the job properly. Kind, friendly and professional.",
     "name": "Katy Stewart", "where": "Google review"},
    {"text": "We have used him a few times because we always get the best results. Klod is friendly, helpful and reliable. Great work, highly recommended.",
     "name": "Dannie Oakley", "where": "Google review"},
    {"text": "Very happy with the work done by A&J Property Maintenance. They fixed several issues and did an excellent paint job. Tidy, professional and great attention to detail.",
     "name": "Karaj Qioleyu", "where": "Google review"},
    {"text": "Reliable, trustworthy and very experienced. Did a great job. Highly recommended.",
     "name": "Silvia Montisci", "where": "Google review"},
    {"text": "Very efficient and professional. Would keep using him as my go-to for home works. Thank you.",
     "name": "Florence Okoh", "where": "Google review"},
    {"text": "Arranged with my tenant, gave a reasonable quote, arrived on time and did excellent work. New sink fitted and wall tiled. Neat, tidy and a great result.",
     "name": "Debjcairns", "where": "Google review"},
    {"text": "Recommended for radiator installation. Very considerate, honest and trustworthy, with excellent communication. I would not hesitate to contact him again.",
     "name": "Federica Biondo", "where": "Google review"},
    {"text": "Klod is professional and polite. His timekeeping is good, he works incredibly hard and cleans up after himself. Definitely our go-to person from now on.",
     "name": "Mac", "where": "Google review"},
]

# ===========================================================================
# LEAD CAPTURE  (contact detection + email)  -- proven server-side logic
# ===========================================================================
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+44|0)\d[\d\s\-\.]{8,11}(?!\d)")
POSTCODE_RE = re.compile(r"\b[A-Za-z]{1,2}\d[A-Za-z\d]?\s*\d[A-Za-z]{2}\b")


def _customer_text(conv):
    return " ".join(m["content"] for m in conv if m.get("role") == "user")


def find_email(conv):
    m = EMAIL_RE.search(_customer_text(conv))
    return m.group(0) if m else None


def find_phone(conv):
    for cand in PHONE_RE.findall(_customer_text(conv)):
        digits = re.sub(r"\D", "", cand)
        if digits.startswith("00"):
            continue
        if digits.startswith("44"):
            digits = "0" + digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            return f"{digits[:5]} {digits[5:]}"
    return None


def find_postcode(conv):
    m = POSTCODE_RE.search(_customer_text(conv))
    if not m:
        return None
    raw = re.sub(r"\s+", "", m.group(0)).upper()
    return raw[:-3] + " " + raw[-3:]


def has_contact_info(conv):
    return bool(find_email(conv) or find_phone(conv))


CLOSING_RE = re.compile(
    r"\b(no longer interested|not interested|no thanks|no thank you|"
    r"that'?s all|that'?s it|that'?s everything|nothing else|all good|"
    r"that'?s great thank|thanks that'?s|goodbye|bye for now|no more|"
    r"i'?m good|im good)\b", re.I)


def _looks_like_closing(text):
    return bool(CLOSING_RE.search(text or ""))


def _transcript(conv):
    out = []
    for m in conv:
        if m["role"] == "user":
            out.append(f"Customer: {m['content']}")
        elif m["role"] == "assistant":
            out.append(f"A&J Assistant: {m['content']}")
    return "\n\n".join(out)


LEAD_SUMMARY_PROMPT = """You are turning a website chat into a clean lead for a
property maintenance company. Read the conversation and output EXACTLY these
labelled lines and nothing else. Fill each in from what the customer actually
said; write "Not specified" if they didn't. Keep each line short.

Name:
Job / work wanted:
Property type (domestic or commercial):
Approx budget (in GBP £; note if total or a rate):
Preferred timing:
Urgency (1-5 where 1=no rush, 5=urgent - infer from what they said):
Location / area:
Other notes:"""


def summarise_lead(conv):
    try:
        resp = client_chat(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": LEAD_SUMMARY_PROMPT},
                      {"role": "user", "content": _transcript(conv)}],
            max_tokens=250, temperature=0.2)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Lead summary failed: {e}")
        return None


def _post_resend(subject, text, html_body=None, attachments=None):
    if not RESEND_API_KEY:
        print("RESEND_API_KEY not set, skipping email")
        return
    payload = {"from": MAIL_FROM, "to": [NOTIFY_TO], "subject": subject, "text": text}
    if html_body:
        payload["html"] = html_body
    if attachments:
        payload["attachments"] = [{"filename": a["filename"], "content": a["b64"]} for a in attachments]
    try:
        r = requests.post("https://api.resend.com/emails",
                          headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                          json=payload, timeout=15)
        if r.status_code >= 300:
            print(f"Resend error: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Failed to send email: {e}")


def _parse_summary(structured):
    out = {}
    if not structured:
        return out
    for line in structured.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _lead_fields(conv):
    s = _parse_summary(summarise_lead(conv))

    def pick(*keys):
        for k in keys:
            v = s.get(k)
            if v and v.lower() not in ("not specified", "not provided", "n/a", "none", "-"):
                return v
        return None

    return {
        "Name": pick("name"),
        "Phone": find_phone(conv),
        "Email": find_email(conv),
        "Postcode": find_postcode(conv),
        "Area": pick("location / area", "location", "area"),
        "Job": pick("job / work wanted", "job", "work wanted"),
        "Property": pick("property type (domestic or commercial)", "property type", "property"),
        "Budget": pick("approx budget", "budget"),
        "Preferred timing": pick("preferred timing", "timing"),
        "Urgency": pick("urgency (1-5 where 1=no rush, 5=urgent - infer from what they said)", "urgency"),
        "Notes": pick("other notes", "notes"),
    }


def _row(label, value):
    if not value:
        return ""
    return ('<tr>'
            f'<td style="padding:10px 16px;border-bottom:1px solid #eee;color:#8a8a8a;'
            f'font-size:13px;white-space:nowrap;vertical-align:top;width:130px">{html.escape(label)}</td>'
            f'<td style="padding:10px 16px;border-bottom:1px solid #eee;color:#1a1a1a;'
            f'font-size:14px;font-weight:600">{html.escape(str(value))}</td></tr>')


def _transcript_html(conv):
    rows = []
    for m in conv:
        if m["role"] == "user":
            who, color, bg = "Customer", "#0a0a0a", "#f5f4f0"
        elif m["role"] == "assistant":
            who, color, bg = "A&J Assistant", "#9a7d1a", "#ffffff"
        else:
            continue
        text = html.escape(m["content"]).replace("\n", "<br>")
        rows.append(f'<div style="margin:0 0 12px"><div style="font-size:11px;letter-spacing:.05em;'
                    f'text-transform:uppercase;color:{color};font-weight:700;margin-bottom:4px">{who}</div>'
                    f'<div style="background:{bg};border:1px solid #ececec;border-radius:10px;padding:11px 14px;'
                    f'font-size:14px;color:#2a2a2a;line-height:1.5">{text}</div></div>')
    return "".join(rows)


def _urgency_badge(u):
    if not u:
        return ""
    m = re.search(r"[1-5]", str(u))
    if not m:
        return ""
    score = int(m.group(0))
    colours = {1: ("#e8f5e9", "#2e7d32", "1 — No rush"), 2: ("#f1f8e9", "#558b2f", "2 — Low"),
               3: ("#fff8e1", "#f57f17", "3 — Moderate"), 4: ("#fff3e0", "#e65100", "4 — Fairly urgent"),
               5: ("#ffebee", "#b71c1c", "5 — URGENT — reply ASAP")}
    bg, fg, label = colours.get(score, ("#f5f5f5", "#555", str(score)))
    return (f'<div style="margin:0 0 20px"><div style="font-size:11px;letter-spacing:.08em;'
            f'text-transform:uppercase;color:#999;font-weight:700;margin-bottom:6px">Urgency</div>'
            f'<span style="display:inline-block;background:{bg};color:{fg};border:1px solid {fg};'
            f'border-radius:999px;padding:5px 14px;font-size:13px;font-weight:700">{label}</span></div>')


def _lead_email_html(fields, conv, image_count):
    urgency_val = fields.pop("Urgency", None)
    rows = "".join(_row(k, v) for k, v in fields.items())
    photos_line = ""
    if image_count:
        photos_line = ('<p style="margin:0 0 20px;font-size:14px;color:#1a1a1a">'
                       f'\U0001F4CE <strong>{image_count} photo(s)</strong> attached to this email.</p>')
    return ('<!DOCTYPE html><html><body style="margin:0;background:#f0efea;padding:24px;'
            'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
            '<div style="max-width:620px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;'
            'box-shadow:0 2px 12px rgba(0,0,0,.07)"><div style="background:#0a0a0a;padding:24px 28px">'
            '<div style="color:#D4AF37;font-size:12px;letter-spacing:.18em;text-transform:uppercase;'
            'font-weight:700">A&amp;J Property Maintenance</div>'
            '<div style="color:#fff;font-size:21px;font-weight:700;margin-top:5px">New enquiry from your website</div></div>'
            '<div style="padding:26px 28px"><p style="margin:0 0 20px;font-size:14px;color:#666">'
            'Here are the details captured by your website assistant:</p>'
            f'{_urgency_badge(urgency_val)}{photos_line}'
            '<table style="width:100%;border-collapse:collapse;border:1px solid #eee;border-radius:8px;'
            f'overflow:hidden;margin-bottom:28px">{rows}</table>'
            '<div style="font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#999;'
            'font-weight:700;margin-bottom:14px">Full conversation</div>'
            f'{_transcript_html(conv)}</div>'
            '<div style="background:#faf9f6;padding:16px 28px;border-top:1px solid #eee;font-size:12px;color:#aaa">'
            'Sent automatically by the A&amp;J Property Maintenance website assistant.</div>'
            '</div></body></html>')


def send_lead_email(conv, images=None):
    images = images or []
    fields = _lead_fields(conv)
    text_lines = ["NEW LEAD - A&J Property Maintenance", "===================================="]
    for k, v in fields.items():
        if v:
            text_lines.append(f"{k}: {v}")
    if images:
        text_lines.append(f"Photos attached: {len(images)}")
    text_lines += ["====================================", "", "Full conversation:", "", _transcript(conv)]
    html_body = _lead_email_html(fields, conv, len(images))
    urgency_m = re.search(r"[1-5]", str(fields.get("Urgency", "")))
    score = int(urgency_m.group(0)) if urgency_m else 0
    prefix = "🔴 URGENT — " if score >= 5 else ("🟠 " if score >= 4 else "")
    contact = fields.get("Phone") or fields.get("Email") or "no number yet"
    bits = [b for b in (fields.get("Name"), fields.get("Area") or fields.get("Postcode")) if b]
    subject = prefix + "New lead - " + (" \u00b7 ".join(bits + [contact]) if bits else contact)
    _post_resend(subject, "\n".join(text_lines), html_body=html_body, attachments=images)


def send_photo_followup(conv, images):
    if not images:
        return
    phone = find_phone(conv) or "Not provided"
    email = find_email(conv) or "Not provided"
    postcode = find_postcode(conv) or "Not provided"
    text = (f"ADDITIONAL PHOTO(S) - A&J\nRelates to a lead you've already been emailed about.\n"
            f"Phone: {phone}\nEmail: {email}\nPostcode: {postcode}\nPhotos attached: {len(images)}\n")
    _post_resend(f"Photo added - lead: {phone}", text, attachments=images)


# ===========================================================================
# CHAT BOT
# ===========================================================================
SYSTEM_PROMPT = f"""
You are the friendly virtual assistant for {BUSINESS['name']}, a property
maintenance company in Portsmouth covering {BUSINESS['area_line']}. You're the
first point of contact for new enquiries on the website.

About the business:
- Trusted local team, domestic and commercial work, free no-obligation quotes.
- All trades under one roof: bathrooms & wet rooms, kitchens, painting &
  decorating, tiling, paving & landscaping, groundwork & concreting, fencing,
  joinery, plumbing, electrical, cleaning and general handyman work.
- Quality workmanship, tidy, reliable, clear communication.

YOUR TONE — this is important:
Warm, friendly and down-to-earth, like a helpful local tradesperson sending a
quick message. Keep it short and natural. No corporate filler like "Great
question!", "I'd be happy to help!", "Certainly!". One or two sentences per
message. Ask ONE thing at a time and wait for the answer. Never use bullet
points or long paragraphs in chat.

Good example: "Happy to help! What's the job — bathroom, kitchen, decorating,
something outside?"

CONVERSATION FLOW — work through these one at a time, in order:
1. Find out what the job is.
2. Get a bit more detail on the scope (rooms, rough size, any specifics).
3. Ask if it's a domestic or commercial property.
4. Offer photos via the paperclip — "Got a couple of photos? Pop them in with
   the paperclip, it really helps us quote. Or we can arrange a visit."
5. Ask for a rough budget — frame it as helpful for the quote; fine if they'd
   rather not say. Note whether it's a total or a rate, in pounds. If a budget
   looks very low for the work described, gently flag it without being blunt,
   then carry on.
6. Ask how urgent it is — "How soon are you hoping to get this done?"
7. Get their name, postcode or area, and best contact number or email. Repeat
   the number/email back to check it's right.
8. Once you've worked through everything, wrap up warmly and confirm their
   enquiry has been sent over to {BUSINESS['owner']}, who'll be in touch about a
   free quote — usually the same day.

WHEN TO FINISH: Only add the [[READY]] signal once you have ASKED about ALL of
these: the job, scope, domestic/commercial, offered photos/visit, budget,
urgency, name, postcode/area, and contact details (and confirmed them). It's
fine if they decline some — but you must have ASKED each one. Do NOT add
[[READY]] just because they gave a number. [[READY]] is a hidden tag stripped
automatically — never shown to the customer. Put it on its own line at the very
end of the final wrap-up message only.

MEMORY RULE: Before every reply, look at the whole conversation. Never ask for
something the customer has already answered or already uploaded. If a customer
gives a phone number or email near the end, either ask the next missing checklist
question or wrap up — do not restart from the first question.
"""

all_conversations = {}
notified_sessions = set()
chat_activity = {}
session_images = {}


SERVICE_WORDS = re.compile(
    r"\b(bathroom|kitchen|bedroom|room|paint|painting|decorate|decorating|"
    r"wallpaper|tiling|tile|floor|flooring|patio|paving|garden|fence|"
    r"fencing|driveway|plumbing|electrical|repair|repairs|maintenance)\b",
    re.I,
)
SCOPE_WORDS = re.compile(
    r"\b(room|rooms|bedroom|bedrooms|bathroom|kitchen|small|medium|large|"
    r"m2|sqm|wall|walls|ceiling|ceilings|floor|floors|whole|part|refit)\b",
    re.I,
)
PROPERTY_WORDS = re.compile(r"\b(domestic|commercial|home|house|flat|office|shop|restaurant|rental)\b", re.I)
BUDGET_DECLINE_RE = re.compile(r"\b(not sure|unsure|don't know|dont know|rather not|no budget|not yet)\b", re.I)


def _after_assistant_question(conv, patterns):
    """Return the first customer reply after an assistant asked one of patterns."""
    asked = False
    for msg in conv:
        role = msg.get("role")
        text = msg.get("content", "")
        if role == "assistant" and any(p in text.lower() for p in patterns):
            asked = True
            continue
        if asked and role == "user" and text.strip():
            return text.strip()
    return None


def _conversation_status(conv, session_id):
    user_text = _customer_text(conv)
    all_text = " ".join(m.get("content", "") for m in conv)
    budget_answer = _after_assistant_question(conv, ("budget",))
    urgency_answer = _after_assistant_question(conv, ("how soon", "urgent", "urgency", "hoping to get this done"))
    name_answer = _after_assistant_question(conv, ("name",))

    return {
        "job": bool(SERVICE_WORDS.search(user_text)),
        "scope": bool(SCOPE_WORDS.search(user_text)),
        "property": bool(PROPERTY_WORDS.search(user_text)),
        "photo": bool(session_images.get(session_id)) or "attached a photo" in all_text.lower()
                 or "paperclip" in all_text.lower() or "arrange a visit" in all_text.lower(),
        "budget": bool(budget_answer and (re.search(r"\d", budget_answer) or BUDGET_DECLINE_RE.search(budget_answer))),
        "urgency": bool(urgency_answer),
        "name": bool(name_answer and re.search(r"[A-Za-z]{2,}", name_answer)),
        "postcode": bool(find_postcode(conv)),
        "contact": has_contact_info(conv),
    }


def _next_missing_item(status):
    labels = [
        ("job", "job/work wanted"),
        ("scope", "rough size or scope"),
        ("property", "domestic or commercial property"),
        ("photo", "photos or offer of a visit"),
        ("budget", "rough budget"),
        ("urgency", "preferred timing or urgency"),
        ("name", "customer name"),
        ("postcode", "postcode or area"),
        ("contact", "phone number or email"),
    ]
    for key, label in labels:
        if not status.get(key):
            return label
    return "done"


def _chat_memory_hint(conv, session_id):
    status = _conversation_status(conv, session_id)
    next_item = _next_missing_item(status)
    facts = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in status.items())
    if next_item == "done":
        action = (
            "All required lead details are present. Wrap up warmly, say the enquiry "
            f"has been sent to {BUSINESS['owner']}, and add [[READY]] on its own line."
        )
    else:
        action = (
            f"The next missing item is: {next_item}. Ask only for that. Do not restart "
            "the conversation and do not ask again for anything marked yes."
        )
    return (
        "Conversation memory/checklist for this exact chat:\n"
        f"{facts}\n"
        f"{action}"
    )


def _fixed_next_question(next_item):
    questions = {
        "job/work wanted": "What's the job you need help with?",
        "rough size or scope": "Roughly how big is it, or what parts need doing?",
        "domestic or commercial property": "Is it for your home or a commercial property?",
        "photos or offer of a visit": (
            "Got a couple of photos? Pop them in with the paperclip, it really helps us quote. "
            "Or we can arrange a visit."
        ),
        "rough budget": (
            "Do you have a rough budget in mind? It's fine if not — it just helps us quote properly."
        ),
        "preferred timing or urgency": "How soon are you hoping to get this done?",
        "customer name": "What's your name, please?",
        "postcode or area": "What's your postcode or area?",
        "phone number or email": "What's the best phone number or email for you?",
    }
    return questions.get(next_item)


def _reply_repeats_answered_item(reply, status):
    text = reply.lower()
    repeated_checks = [
        ("job", ("what's the job", "what is the job", "bathroom, kitchen", "something outside")),
        ("scope", ("how big", "roughly how big", "how many", "approximate size")),
        ("property", ("domestic or commercial", "home or a commercial")),
        ("photo", ("got a couple of photos", "pop them in", "paperclip", "send photo", "send them")),
        ("budget", ("rough budget", "budget in mind")),
        ("urgency", ("how soon", "urgent", "when are you hoping")),
        ("name", ("what's your name", "your name")),
        ("postcode", ("postcode", "area")),
        ("contact", ("phone number", "email", "best contact")),
    ]
    return any(status.get(key) and any(phrase in text for phrase in phrases)
               for key, phrases in repeated_checks)


def _decode_image_data_url(data_url):
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None
    try:
        header, b64 = data_url.split(",", 1)
    except ValueError:
        return None
    if ";base64" not in header:
        return None
    content_type = header[len("data:"):].split(";", 1)[0].lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
    return {"filename": f"job-photo-{uuid.uuid4().hex[:8]}.{ext}", "content_type": content_type,
            "b64": base64.b64encode(raw).decode("ascii")}


# ===========================================================================
# THE PAGE
# ===========================================================================
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ b.name }} | Portsmouth Property Maintenance</title>
<meta name="description" content="Reliable property maintenance across {{ b.area_line }}. Bathrooms, kitchens, decorating, tiling, paving, groundwork, fencing, plumbing & electrical. Free no-obligation quotes.">
<link rel="icon" href="{{ url_for('static', filename='images/logo.jpg') }}">
<meta property="og:title" content="{{ b.name }} | Portsmouth Property Maintenance">
<meta property="og:description" content="All trades under one roof across {{ b.area_line }}. Free quotes.">
<meta property="og:type" content="website">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#0c0b09; --ink2:#15130f; --panel:#1b1813; --cream:#f6f1e7; --mut:#a89c86;
  --gold:#d4af37; --gold-soft:#ecd089; --line:rgba(212,175,55,.22); --rad:16px;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--ink);color:var(--cream);font-family:'Inter',system-ui,sans-serif;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
a{color:inherit;text-decoration:none}
img{max-width:100%;display:block}
button,input{font:inherit}
.serif{font-family:'Fraunces',Georgia,serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
.eyebrow{font-size:12px;letter-spacing:.34em;text-transform:uppercase;color:var(--gold);font-weight:600}
section{position:relative}
h2.title{font-family:'Fraunces',serif;font-weight:600;font-size:clamp(28px,4.2vw,44px);line-height:1.08;margin:14px 0 10px}
.lede{color:var(--mut);max-width:620px;font-size:clamp(15px,1.8vw,17px)}

/* reveal */
.reveal{opacity:1;transform:none;transition:opacity .7s ease,transform .7s ease}
.js .reveal{opacity:0;transform:translateY(22px)}
.reveal.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none;transition:none}}

/* nav */
nav{position:sticky;top:0;z-index:60;background:rgba(12,11,9,.78);backdrop-filter:blur(12px) saturate(140%);
  border-bottom:1px solid var(--line)}
nav .bar{display:flex;align-items:center;justify-content:space-between;height:68px}
.brand{display:flex;align-items:center;gap:12px;font-family:'Fraunces',serif;font-weight:600;letter-spacing:.04em}
.brand img{width:38px;height:38px;border-radius:50%;border:1px solid var(--line);object-fit:cover}
.brand b{color:var(--gold);font-size:18px}.brand span{font-size:11px;color:var(--mut);letter-spacing:.22em;text-transform:uppercase;display:block;margin-top:-2px}
.navlinks{display:flex;align-items:center;gap:30px}
.navlinks a{font-size:14px;color:#e9e2d3;opacity:.85;letter-spacing:.02em}
.navlinks a:hover{color:var(--gold);opacity:1}
.navcta{border:1px solid var(--gold);color:var(--gold)!important;padding:9px 18px;border-radius:999px;opacity:1!important;font-weight:500;transition:.2s}
.navcta:hover{background:var(--gold);color:var(--ink)!important}
.burger{display:none;background:none;border:0;color:var(--gold);cursor:pointer;padding:6px}
@media(max-width:860px){
  .navlinks{position:fixed;inset:68px 0 auto 0;flex-direction:column;gap:0;background:var(--ink2);
    border-bottom:1px solid var(--line);padding:8px 0;transform:translateY(-130%);transition:.35s;opacity:0}
  .navlinks.open{transform:none;opacity:1}
  .navlinks a{width:100%;padding:14px 24px}.navcta{margin:10px 24px;text-align:center}
  .burger{display:block}
}

/* hero */
.hero{min-height:92vh;display:flex;align-items:center;position:relative;isolation:isolate}
.hero::before{content:"";position:absolute;inset:0;z-index:-2;
  background:linear-gradient(180deg,rgba(8,7,6,.62),rgba(8,7,6,.86)),
  url('{{ url_for('static', filename='images/portfolio/large-patio-porcelain.jpg') }}') center/cover}
.hero::after{content:"";position:absolute;inset:0;z-index:-1;background:radial-gradient(120% 80% at 80% 0%,rgba(212,175,55,.16),transparent 55%)}
.hero .inner{max-width:760px;padding:40px 24px}
.hero h1{font-family:'Fraunces',serif;font-weight:600;font-size:clamp(40px,7vw,76px);line-height:1.02;margin:18px 0 18px;color:#fff;letter-spacing:-.01em}
.hero h1 em{font-style:italic;color:var(--gold-soft)}
.hero p{font-size:clamp(16px,2.2vw,20px);color:#e5ddcd;max-width:560px;margin-bottom:32px}
.cta-row{display:flex;gap:14px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:9px;padding:14px 26px;border-radius:999px;font-weight:600;font-size:15px;cursor:pointer;border:1px solid transparent;transition:.22s}
.btn-gold{background:var(--gold);color:var(--ink)}
.btn-gold:hover{background:var(--gold-soft);transform:translateY(-2px)}
.btn-ghost{border-color:rgba(246,241,231,.32);color:#fff}
.btn-ghost:hover{border-color:var(--gold);color:var(--gold)}
.hero .meta{display:flex;gap:26px;flex-wrap:wrap;margin-top:40px;color:var(--mut);font-size:13.5px;letter-spacing:.02em}
.hero .meta b{color:var(--cream);font-weight:600}
/* hero video background */
.hero.has-video::before{display:none}
.hero-bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:-2}
.hero-overlay{position:absolute;inset:0;z-index:-1;
  background:linear-gradient(180deg,rgba(8,7,6,.55),rgba(8,7,6,.82)),
  radial-gradient(120% 80% at 80% 0%,rgba(212,175,55,.18),transparent 55%)}
/* scroll progress */
.progress{position:fixed;top:0;left:0;height:3px;width:0;z-index:100;
  background:linear-gradient(90deg,var(--gold),var(--gold-soft));transition:width .1s linear}

/* trust strip */
.strip{border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--ink2)}
.strip .wrap{display:flex;flex-wrap:wrap;gap:14px 40px;padding:20px 24px;align-items:center;justify-content:center}
.strip span{display:inline-flex;align-items:center;gap:9px;font-size:13.5px;color:#d9d0bd;letter-spacing:.02em}
.strip svg{width:18px;height:18px;color:var(--gold)}

/* services */
.sec{padding:clamp(64px,9vw,110px) 0}
.svc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:16px;margin-top:42px}
.svc{background:linear-gradient(180deg,var(--panel),var(--ink2));border:1px solid var(--line);border-radius:var(--rad);
  padding:26px 24px;transition:.25s}
.svc:hover{transform:translateY(-4px);border-color:rgba(212,175,55,.5);box-shadow:0 18px 40px -24px rgba(212,175,55,.4)}
.svc .ic{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;background:rgba(212,175,55,.1);
  border:1px solid var(--line);color:var(--gold);margin-bottom:16px}
.svc .ic svg{width:24px;height:24px}
.svc h3{font-family:'Fraunces',serif;font-size:19px;font-weight:600;margin-bottom:7px}
.svc p{font-size:14px;color:var(--mut)}

/* portfolio */
.filters{display:flex;flex-wrap:wrap;gap:9px;margin:34px 0 26px}
.filters button{background:transparent;border:1px solid var(--line);color:#d8cfbc;padding:8px 16px;border-radius:999px;
  font-size:13px;font-weight:500;cursor:pointer;transition:.2s;font-family:inherit}
.filters button:hover{border-color:var(--gold);color:var(--gold)}
.filters button.active{background:var(--gold);color:var(--ink);border-color:var(--gold)}
.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.shot{position:relative;min-height:0;aspect-ratio:4/3;border-radius:14px;overflow:hidden;cursor:pointer;
  border:1px solid var(--line);background:var(--ink2)}
.shot:nth-child(1),.shot:nth-child(2){grid-column:span 2;aspect-ratio:16/9}
.shot img{width:100%;height:100%;object-fit:cover;transition:transform .5s ease;display:block}
.shot:hover img{transform:scale(1.05)}
.shot figcaption{position:absolute;inset:auto 0 0 0;padding:34px 14px 12px;font-size:12.5px;color:#f3ecdd;
  background:linear-gradient(transparent,rgba(7,6,5,.9));opacity:1}
.shot .tag{position:absolute;top:10px;left:10px;font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--gold);background:rgba(7,6,5,.72);border:1px solid var(--line);padding:4px 9px;border-radius:999px}
@media(max-width:760px){
  .wrap{padding:0 18px}
  nav .bar{height:62px}
  .navlinks{inset:62px 0 auto 0}
  .hero{min-height:78vh}
  .hero .inner{padding:34px 18px 48px}
  .hero h1{font-size:clamp(38px,12vw,54px)}
  .hero p{font-size:17px;line-height:1.55;max-width:34rem}
  .hero .eyebrow{font-size:11px;letter-spacing:.2em}
  .hero .meta{gap:12px;margin-top:28px}
  .hero .meta div{width:100%}
  .cta-row{display:grid;grid-template-columns:1fr;gap:10px}
  .btn{width:100%;justify-content:center;padding:13px 18px;text-align:center}
  .filters{overflow-x:auto;flex-wrap:nowrap;margin-left:-18px;margin-right:-18px;padding:0 18px 4px;scrollbar-width:none}
  .filters::-webkit-scrollbar{display:none}
  .filters button{flex:0 0 auto}
  .gallery{grid-template-columns:1fr;gap:14px}
  .shot,.shot:nth-child(1),.shot:nth-child(2){grid-column:auto;aspect-ratio:4/3}
  .shot figcaption{font-size:12px}
}

/* lightbox */
.lb{position:fixed;inset:0;z-index:120;background:rgba(6,5,4,.94);display:none;align-items:center;justify-content:center;padding:24px}
.lb.open{display:flex}
.lb img{max-width:92vw;max-height:82vh;border-radius:10px;box-shadow:0 30px 80px -20px rgba(0,0,0,.8)}
.lb .cap{position:absolute;bottom:26px;left:0;right:0;text-align:center;color:#e8e0cf;font-size:14px;padding:0 24px}
.lb button{position:absolute;background:rgba(255,255,255,.06);border:1px solid var(--line);color:#fff;width:48px;height:48px;
  border-radius:50%;font-size:22px;cursor:pointer;display:grid;place-items:center}
.lb .x{top:20px;right:20px}.lb .prev{left:20px;top:50%;transform:translateY(-50%)}.lb .next{right:20px;top:50%;transform:translateY(-50%)}
@media(max-width:600px){.lb .prev,.lb .next{display:none}}

/* reels (vertical) */
.reel-grid{display:flex;gap:18px;flex-wrap:wrap;justify-content:center;margin-top:42px}
.reel{position:relative;width:265px;aspect-ratio:9/16;border-radius:24px;overflow:hidden;border:1px solid var(--line);
  background:#000;cursor:pointer;box-shadow:0 26px 60px -28px rgba(0,0,0,.85);transition:transform .3s}
.reel:hover{transform:translateY(-5px)}
.reel video{width:100%;height:100%;object-fit:cover;display:block}
.reel .cap{position:absolute;left:0;right:0;bottom:0;padding:34px 16px 16px;font-size:13px;color:#f3ecdd;z-index:2;
  background:linear-gradient(transparent,rgba(6,5,4,.92))}
.reel .sound{position:absolute;top:12px;right:12px;z-index:3;width:38px;height:38px;border-radius:50%;pointer-events:none;
  background:rgba(7,6,5,.55);border:1px solid var(--line);color:#fff;display:grid;place-items:center;backdrop-filter:blur(5px)}
.reel .sound svg{width:18px;height:18px}
.reel .badge{position:absolute;top:13px;left:13px;z-index:3;font-size:10px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--gold);background:rgba(7,6,5,.55);border:1px solid var(--line);padding:5px 10px;border-radius:999px;backdrop-filter:blur(5px)}

/* why */
.why{background:var(--ink2);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.why-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:30px;margin-top:42px}
.why-grid .n{font-family:'Fraunces',serif;color:var(--gold);font-size:34px;font-weight:600}
.why-grid h3{font-family:'Fraunces',serif;font-size:20px;margin:8px 0 6px}
.why-grid p{color:var(--mut);font-size:14.5px}

/* reviews */
.rev-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px;margin-top:40px}
.rev{background:linear-gradient(180deg,var(--panel),var(--ink2));border:1px solid var(--line);border-radius:var(--rad);padding:28px 26px}
.stars{color:var(--gold);letter-spacing:3px;font-size:15px;margin-bottom:14px}
.rev p{font-size:15px;color:#ece4d3;line-height:1.65}
.rev .who{margin-top:16px;font-size:13px;color:var(--mut);letter-spacing:.02em}
.rev .who b{color:var(--cream);font-weight:600}
.rev .rtags{margin-top:14px;font-size:11.5px;letter-spacing:.05em;color:var(--gold);text-transform:uppercase}

/* contact */
.contact{background:radial-gradient(120% 90% at 50% -10%,rgba(212,175,55,.12),transparent 60%),var(--ink)}
.cgrid{display:grid;grid-template-columns:1.1fr .9fr;gap:40px;margin-top:42px;align-items:start}
@media(max-width:820px){.cgrid{grid-template-columns:1fr}}
.ccard{background:var(--ink2);border:1px solid var(--line);border-radius:var(--rad);padding:30px}
.crow{display:flex;align-items:center;gap:14px;padding:15px 0;border-bottom:1px solid rgba(212,175,55,.12)}
.crow:last-child{border-bottom:0}
.crow .ic{width:42px;height:42px;border-radius:11px;display:grid;place-items:center;background:rgba(212,175,55,.1);border:1px solid var(--line);color:var(--gold);flex:none}
.crow .ic svg{width:20px;height:20px}
.crow .lbl{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)}
.crow .val{font-size:16px;color:var(--cream);font-weight:500;overflow-wrap:anywhere}
.socials{display:flex;gap:12px;margin-top:22px}
.socials a{width:44px;height:44px;border-radius:11px;display:grid;place-items:center;border:1px solid var(--line);color:var(--gold);transition:.2s}
.socials a:hover{background:var(--gold);color:var(--ink)}
.socials svg{width:20px;height:20px}

/* footer */
footer{border-top:1px solid var(--line);background:var(--ink2);padding:34px 0;color:var(--mut);font-size:13px}
footer .wrap{display:flex;flex-wrap:wrap;gap:14px;justify-content:space-between;align-items:center}
footer a{color:var(--gold-soft)}
footer a:hover{color:var(--gold)}

/* WhatsApp float */
.wa{position:fixed;left:20px;bottom:22px;z-index:90;width:56px;height:56px;border-radius:50%;background:#25D366;
  display:grid;place-items:center;box-shadow:0 10px 30px -8px rgba(37,211,102,.7);transition:.2s}
.wa:hover{transform:scale(1.07)}.wa svg{width:30px;height:30px;color:#fff}

/* chat widget */
.chat-btn{position:fixed;right:20px;bottom:22px;z-index:95;background:var(--gold);color:var(--ink);border:0;border-radius:999px;
  padding:14px 22px;font-weight:600;font-family:inherit;font-size:15px;cursor:pointer;display:flex;align-items:center;gap:9px;
  box-shadow:0 12px 34px -10px rgba(212,175,55,.8);transition:.2s}
.chat-btn:hover{transform:translateY(-2px)}
.chat-btn svg{width:20px;height:20px}
.chat-panel{position:fixed;right:20px;bottom:22px;z-index:96;width:min(390px,calc(100vw - 40px));height:min(620px,calc(100vh - 44px));
  background:#15130f;border:1px solid var(--line);border-radius:20px;display:none;flex-direction:column;overflow:hidden;
  box-shadow:0 30px 80px -20px rgba(0,0,0,.7)}
.chat-panel.open{display:flex}
.chat-head{background:linear-gradient(120deg,#1d1a14,#13110d);padding:16px 18px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--line)}
.chat-head img{width:38px;height:38px;border-radius:50%;border:1px solid var(--line)}
.chat-head .t{font-family:'Fraunces',serif;font-weight:600;color:var(--gold)}
.chat-head .s{font-size:11.5px;color:var(--mut)}
.chat-head .close{margin-left:auto;background:none;border:0;color:var(--mut);font-size:22px;cursor:pointer}
.msgs{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:82%;padding:11px 14px;border-radius:14px;font-size:14.5px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word}
.msg.bot{align-self:flex-start;background:#211d16;border:1px solid var(--line);color:#ece4d3;border-bottom-left-radius:4px}
.msg.user{align-self:flex-end;background:var(--gold);color:var(--ink);border-bottom-right-radius:4px;font-weight:500}
.msg.img{padding:4px;background:#211d16;border:1px solid var(--line)}
.msg.img img{border-radius:10px;max-width:180px}
.typing{align-self:flex-start;color:var(--mut);font-size:13px;padding:4px 6px}
.chat-in{display:flex;gap:8px;padding:12px;border-top:1px solid var(--line);background:#13110d;align-items:center}
.chat-in input[type=text]{flex:1;background:#211d16;border:1px solid var(--line);color:var(--cream);border-radius:999px;
  padding:11px 16px;font-size:14.5px;font-family:inherit;outline:none}
.chat-in input[type=text]:focus{border-color:var(--gold)}
.iconbtn{background:#211d16;border:1px solid var(--line);color:var(--gold);width:42px;height:42px;border-radius:50%;
  cursor:pointer;display:grid;place-items:center;flex:none;transition:.2s}
.iconbtn:hover{background:var(--gold);color:var(--ink)}.iconbtn svg{width:19px;height:19px}
.iconbtn.busy{opacity:.5;pointer-events:none}
.hp{position:absolute;left:-9999px}
@media(max-width:520px){
  .sec{padding:54px 0}
  .svc-grid,.why-grid,.rev-grid{grid-template-columns:1fr}
  .ccard{padding:22px 18px}
  .crow{align-items:flex-start}
  .chat-btn{left:76px;right:14px;bottom:16px;justify-content:center;padding:13px 14px}
  .wa{left:14px;bottom:16px;width:50px;height:50px}
  .chat-panel{inset:0;z-index:200;width:100vw;height:100vh;height:100dvh;max-height:none;border:0;border-radius:0}
  .chat-head{padding:10px 14px;padding-top:max(10px,env(safe-area-inset-top));gap:10px;flex:none}
  .chat-head img{width:32px;height:32px}
  .chat-head .s{display:none}
  .chat-head .close{font-size:28px;line-height:1;color:#f6f1e7}
  .msgs{padding:12px;gap:10px;min-height:0}
  .msg{max-width:88%;font-size:14px;padding:10px 12px}
  .chat-in{padding:10px 8px;padding-bottom:max(10px,env(safe-area-inset-bottom));gap:6px;flex:none}
  .chat-in input[type=text]{min-width:0;padding:10px 12px;font-size:16px}
  .iconbtn{width:38px;height:38px}
}
</style>
</head>
<body>
<script>if('IntersectionObserver' in window){document.documentElement.classList.add('js')}</script>

<div class="progress" id="progress"></div>

<nav>
  <div class="wrap bar">
    <a class="brand" href="#top">
      <img src="{{ url_for('static', filename='images/logo.jpg') }}" alt="A&J logo">
      <span style="line-height:1.05"><b>A&amp;J</b><span>Property Maintenance</span></span>
    </a>
    <button class="burger" onclick="document.getElementById('nl').classList.toggle('open')" aria-label="Menu">
      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
    </button>
    <div class="navlinks" id="nl">
      <a href="#services" onclick="closeNav()">Services</a>
      <a href="#work" onclick="closeNav()">Our Work</a>
      <a href="#reviews" onclick="closeNav()">Reviews</a>
      <a href="#contact" onclick="closeNav()">Contact</a>
      <a class="navcta" href="#contact" onclick="closeNav();openChat()">Free Quote</a>
    </div>
  </div>
</nav>

<header class="hero {{ 'has-video' if hero_video else '' }}" id="top">
  {% if hero_video %}
  <video class="hero-bg" autoplay muted loop playsinline preload="auto"
         poster="{{ url_for('static', filename='images/portfolio/large-patio-porcelain.jpg') }}">
    <source src="{{ url_for('static', filename=hero_video[7:]) }}" type="video/mp4">
  </video>
  <div class="hero-overlay"></div>
  {% endif %}
  <div class="wrap inner">
    <div class="eyebrow reveal">Portsmouth & nearby</div>
    <h1 class="reveal">All trades,<br><em>one trusted team.</em></h1>
    <p class="reveal">Bathrooms, kitchens, patios, decorating and repairs — tidy property maintenance finished properly across Portsmouth and nearby areas.</p>
    <div class="cta-row reveal">
      <button class="btn btn-gold" onclick="openChat()">Get a free quote
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
      </button>
      <a class="btn btn-ghost" href="tel:+{{ b.phone_e164 }}">Call {{ b.phone_display }}</a>
    </div>
    <div class="meta reveal">
      <div><b>Free</b> no-obligation quotes</div>
      <div><b>Tidy</b> &amp; reliable</div>
      <div><b>All trades</b> under one roof</div>
    </div>
  </div>
</header>

<div class="strip">
  <div class="wrap">
    {% for t in ["Bathrooms & Wet Rooms","Kitchens","Decorating","Paving & Landscaping","Plumbing & Electrical","Groundwork"] %}
    <span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>{{ t }}</span>
    {% endfor %}
  </div>
</div>

<section class="sec" id="services">
  <div class="wrap">
    <div class="eyebrow reveal">What we do</div>
    <h2 class="title reveal">Everything your property needs,<br>handled by one team.</h2>
    <p class="lede reveal">No chasing five different trades. We cover the lot — indoors and out, big jobs and small.</p>
    <div class="svc-grid">
      {% for s in services %}
      <div class="svc reveal"><div class="ic">{{ s.icon|safe }}</div><h3>{{ s.title }}</h3><p>{{ s.desc }}</p></div>
      {% endfor %}
    </div>
  </div>
</section>

<section class="sec" id="work" style="padding-top:0">
  <div class="wrap">
    <div class="eyebrow reveal">Our work</div>
    <h2 class="title reveal">Recent projects</h2>
    <p class="lede reveal">A few jobs from around Portsmouth and beyond. Tap any photo to take a closer look.</p>
    <div class="filters reveal">
      {% for f in filters %}<button class="{{ 'active' if f=='All' else '' }}" data-filter="{{ f }}">{{ f }}</button>{% endfor %}
    </div>
    <div class="gallery" id="gallery">
      {% for item in portfolio %}
      <figure class="shot reveal" data-cat="{{ item.cat }}" data-cap="{{ item.cap }}">
        <span class="tag">{{ item.cat }}</span>
        <img src="{{ url_for('static', filename=item.img[7:]) }}" alt="{{ item.cap }}" loading="lazy">
        <figcaption>{{ item.cap }}</figcaption>
      </figure>
      {% endfor %}
    </div>
  </div>
</section>

{% if videos %}
<section class="sec" id="videos" style="padding-top:0">
  <div class="wrap">
    <div class="eyebrow reveal">Watch us work</div>
    <h2 class="title reveal">Straight from the job</h2>
    <p class="lede reveal">Real clips from real jobs around Portsmouth. They play as you scroll — tap any one for sound.</p>
    <div class="reel-grid">
      {% for v in videos %}
      <figure class="reel reveal" onclick="toggleSound(this)">
        <span class="badge">Reel</span>
        <span class="sound" id="snd{{ loop.index }}"></span>
        <video muted loop playsinline preload="metadata" {% if v.poster %}poster="{{ url_for('static', filename=v.poster[7:]) }}"{% endif %}>
          <source src="{{ url_for('static', filename=v.src[7:]) }}" type="video/mp4">
        </video>
        {% if v.cap %}<figcaption class="cap">{{ v.cap }}</figcaption>{% endif %}
      </figure>
      {% endfor %}
    </div>
  </div>
</section>
{% endif %}

<section class="sec why">
  <div class="wrap">
    <div class="eyebrow reveal">Why A&amp;J</div>
    <h2 class="title reveal">Reliable work, done right.</h2>
    <div class="why-grid">
      <div class="reveal"><div class="n">01</div><h3>Driven by professionalism</h3><p>Care and attention to detail on every job, left clean and tidy.</p></div>
      <div class="reveal"><div class="n">02</div><h3>Focused on you</h3><p>We listen, communicate clearly and tailor the work to what you actually need.</p></div>
      <div class="reveal"><div class="n">03</div><h3>Quality &amp; speed</h3><p>Efficient work without cutting corners — dependable results every time.</p></div>
    </div>
  </div>
</section>

<section class="sec" id="reviews">
  <div class="wrap">
    <div class="eyebrow reveal">Reviews</div>
    <h2 class="title reveal">What customers say</h2>
    <p class="lede reveal">Real feedback from people across Portsmouth and the surrounding areas.</p>
    <div class="rev-grid">
      {% for r in reviews %}
      <div class="rev reveal"><div class="stars">★★★★★</div><p>“{{ r.text }}”</p>
        {% if r.tags %}<div class="rtags">{{ r.tags }}</div>{% endif %}
        <div class="who"><b>{{ r.name }}</b> · {{ r.where }}</div></div>
      {% endfor %}
    </div>
  </div>
</section>

<section class="sec contact" id="contact">
  <div class="wrap">
    <div class="eyebrow reveal">Get in touch</div>
    <h2 class="title reveal">Free quote, no obligation.</h2>
    <p class="lede reveal">Tell us about the job and we'll get straight back to you — usually the same day. Use the chat for the quickest quote, or reach us any way you like.</p>
    <div class="cgrid">
      <div class="ccard reveal">
        <div class="crow"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg></div>
          <div><div class="lbl">Call us</div><a class="val" href="tel:+{{ b.phone_e164 }}">{{ b.phone_display }}</a></div></div>
        <div class="crow"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="m4 6 8 6 8-6"/></svg></div>
          <div><div class="lbl">Email</div><a class="val" href="mailto:{{ b.email_public }}">{{ b.email_public }}</a></div></div>
        <div class="crow"><div class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg></div>
          <div><div class="lbl">Area covered</div><div class="val">{{ b.area_line }}</div></div></div>
        <div class="socials">
          <a href="https://wa.me/{{ b.phone_e164 }}" aria-label="WhatsApp" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.5 14.4c-.3-.2-1.7-.8-2-.9-.3-.1-.5-.2-.7.2-.2.3-.7.9-.9 1.1-.2.2-.3.2-.6.1-1.8-.9-3-1.6-4.2-3.6-.3-.5.3-.5.8-1.6.1-.2 0-.4 0-.5 0-.2-.7-1.6-.9-2.2-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.5s1.1 2.9 1.2 3.1c.2.2 2.1 3.3 5.2 4.6 2 .8 2.7.9 3.7.8.6-.1 1.7-.7 2-1.4.2-.7.2-1.2.2-1.4-.1-.1-.3-.2-.6-.3z"/><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2c-1.5 0-3-.4-4.3-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2z"/></svg></a>
          <a href="{{ b.instagram }}" aria-label="Instagram" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg></a>
          <a href="{{ b.facebook }}" aria-label="Facebook" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 9h3V6h-3a4 4 0 0 0-4 4v2H8v3h2v6h3v-6h2.5l.5-3H13v-1.5A1.5 1.5 0 0 1 14 9z"/></svg></a>
        </div>
      </div>
      <div class="ccard reveal" style="display:flex;flex-direction:column;justify-content:center;text-align:center;gap:14px">
        <div style="font-family:'Fraunces',serif;font-size:24px;color:var(--gold-soft)">Quickest way to a quote</div>
        <p style="color:var(--mut);font-size:15px">Chat to our assistant — describe the job, drop a photo, and we'll do the rest.</p>
        <button class="btn btn-gold" style="align-self:center" onclick="openChat()">Start a chat
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>
      </div>
    </div>
  </div>
</section>

<footer>
  <div class="wrap">
    <div>© <span id="yr"></span> {{ b.name }} Ltd · {{ b.postcode }} Portsmouth</div>
    <div><a href="/privacy-policy">Privacy Policy</a> · Built with care · Bathrooms · Kitchens · Decorating · Landscaping · Maintenance</div>
  </div>
</footer>

<a class="wa" href="https://wa.me/{{ b.phone_e164 }}" target="_blank" rel="noopener" aria-label="WhatsApp us">
  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.5 14.4c-.3-.2-1.7-.8-2-.9-.3-.1-.5-.2-.7.2-.2.3-.7.9-.9 1.1-.2.2-.3.2-.6.1-1.8-.9-3-1.6-4.2-3.6-.3-.5.3-.5.8-1.6.1-.2 0-.4 0-.5 0-.2-.7-1.6-.9-2.2-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.5s1.1 2.9 1.2 3.1c.2.2 2.1 3.3 5.2 4.6 2 .8 2.7.9 3.7.8.6-.1 1.7-.7 2-1.4.2-.7.2-1.2.2-1.4-.1-.1-.3-.2-.6-.3z"/><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2c-1.5 0-3-.4-4.3-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2z"/></svg>
</a>

<!-- lightbox -->
<div class="lb" id="lb">
  <button class="x" onclick="closeLb()">×</button>
  <button class="prev" onclick="stepLb(-1)">‹</button>
  <button class="next" onclick="stepLb(1)">›</button>
  <img id="lbimg" src="" alt="">
  <div class="cap" id="lbcap"></div>
</div>

<!-- chat -->
<button class="chat-btn" id="chatBtn" onclick="openChat()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
  Chat for a quote
</button>
<div class="chat-panel" id="chatPanel">
  <div class="chat-head">
    <img src="{{ url_for('static', filename='images/logo.jpg') }}" alt="">
    <div><div class="t">A&amp;J Assistant</div><div class="s">Typically replies in seconds</div></div>
    <button class="close" onclick="closeChat()">×</button>
  </div>
  <div class="msgs" id="msgs"></div>
  <div class="chat-in">
    <input type="text" class="hp" id="website" tabindex="-1" autocomplete="off" aria-hidden="true">
    <button class="iconbtn" id="attachBtn" onclick="document.getElementById('fileIn').click()" aria-label="Attach photo">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.4 11.05 12.25 20.2a5 5 0 0 1-7.07-7.07l9.19-9.19a3 3 0 0 1 4.24 4.24l-9.2 9.19a1 1 0 0 1-1.41-1.41l8.49-8.49"/></svg>
    </button>
    <input type="file" id="fileIn" accept="image/*" multiple style="display:none">
    <input type="text" id="chatInput" placeholder="Describe your job…" autocomplete="off">
    <button class="iconbtn" onclick="sendMsg()" aria-label="Send">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/></svg>
    </button>
  </div>
</div>

<script>
// reels: autoplay muted when in view, tap for sound
const ICON_MUTE='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M22 9l-6 6M16 9l6 6"/></svg>';
const ICON_SOUND='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14"/></svg>';
document.querySelectorAll('.reel .sound').forEach(s=>s.innerHTML=ICON_MUTE);
const reelVids=[...document.querySelectorAll('.reel video')];
if('IntersectionObserver' in window){
  const rio=new IntersectionObserver((es)=>{es.forEach(e=>{
    if(e.isIntersecting){e.target.play().catch(()=>{})}else{e.target.pause()}})},{threshold:.55});
  reelVids.forEach(v=>rio.observe(v));
}
function toggleSound(fig){const v=fig.querySelector('video');const btn=fig.querySelector('.sound');
  const unmute=v.muted;
  document.querySelectorAll('.reel').forEach(o=>{const ov=o.querySelector('video');
    if(ov!==v){ov.muted=true;o.querySelector('.sound').innerHTML=ICON_MUTE}});
  v.muted=!unmute;btn.innerHTML=v.muted?ICON_MUTE:ICON_SOUND;v.play().catch(()=>{});}

document.getElementById('yr').textContent = new Date().getFullYear();
function closeNav(){document.getElementById('nl').classList.remove('open')}

// scroll progress bar
const prog=document.getElementById('progress');
addEventListener('scroll',()=>{const h=document.documentElement;
  const sc=h.scrollTop/(h.scrollHeight-h.clientHeight);prog.style.width=(sc*100)+'%'},{passive:true});

// scroll reveal
if('IntersectionObserver' in window){
  const io = new IntersectionObserver((es)=>{es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}})},{threshold:.12});
  document.querySelectorAll('.reveal').forEach(el=>io.observe(el));
}else{
  document.querySelectorAll('.reveal').forEach(el=>el.classList.add('in'));
}

// filters
document.querySelectorAll('.filters button').forEach(btn=>{
  btn.onclick=()=>{
    document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const f=btn.dataset.filter;
    document.querySelectorAll('.shot').forEach(s=>{
      s.style.display=(f==='All'||s.dataset.cat===f)?'':'none';
    });
  };
});

// lightbox
let shots=[...document.querySelectorAll('.shot')], lbi=0;
function visibleShots(){return shots.filter(s=>s.style.display!=='none')}
shots.forEach(s=>{s.onclick=()=>{const vs=visibleShots();lbi=vs.indexOf(s);showLb(vs)}});
function showLb(vs){const s=vs[lbi];document.getElementById('lbimg').src=s.querySelector('img').src;
  document.getElementById('lbcap').textContent=s.dataset.cap;document.getElementById('lb').classList.add('open')}
function stepLb(d){const vs=visibleShots();lbi=(lbi+d+vs.length)%vs.length;showLb(vs)}
function closeLb(){document.getElementById('lb').classList.remove('open')}
document.getElementById('lb').onclick=e=>{if(e.target.id==='lb')closeLb()};
document.addEventListener('keydown',e=>{if(!document.getElementById('lb').classList.contains('open'))return;
  if(e.key==='Escape')closeLb();if(e.key==='ArrowRight')stepLb(1);if(e.key==='ArrowLeft')stepLb(-1)});

// chat
let greeted=false;
function isPhone(){return window.matchMedia('(max-width: 520px)').matches}
function openChat(){document.getElementById('chatPanel').classList.add('open');document.getElementById('chatBtn').style.display='none';document.body.style.overflow='hidden';
  if(!greeted){greeted=true;addMsg("Hi! 👋 I'm here for A&J Property Maintenance. What can we help you with — bathroom, kitchen, decorating, something outside?","bot")}
  if(!isPhone())document.getElementById('chatInput').focus()}
function closeChat(){document.getElementById('chatPanel').classList.remove('open');document.getElementById('chatBtn').style.display='flex';document.body.style.overflow=''}
function addMsg(t,who){const m=document.createElement('div');m.className='msg '+who;m.textContent=t;
  const box=document.getElementById('msgs');box.appendChild(m);box.scrollTop=box.scrollHeight}
function addImg(src){const m=document.createElement('div');m.className='msg img user';const i=document.createElement('img');i.src=src;m.appendChild(i);
  const box=document.getElementById('msgs');box.appendChild(m);box.scrollTop=box.scrollHeight}
function typing(on){const box=document.getElementById('msgs');let t=document.getElementById('typing');
  if(on&&!t){t=document.createElement('div');t.id='typing';t.className='typing';t.textContent='A&J is typing…';box.appendChild(t);box.scrollTop=box.scrollHeight}
  else if(!on&&t){t.remove()}}
async function sendMsg(){const inp=document.getElementById('chatInput');const text=inp.value.trim();if(!text)return;
  addMsg(text,'user');inp.value='';typing(true);
  try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
    body:JSON.stringify({message:text,website:document.getElementById('website').value})});
    const d=await r.json();typing(false);addMsg(d.reply,'bot');
  }catch(e){typing(false);addMsg("Sorry, something glitched there — give that another go?","bot")}}
document.getElementById('chatInput').addEventListener('keydown',e=>{if(e.key==='Enter')sendMsg()});
document.getElementById('chatInput').addEventListener('focus',()=>{
  if(isPhone())setTimeout(()=>{const box=document.getElementById('msgs');box.scrollTop=box.scrollHeight},250);
});

// resize image client-side before upload
function resizeImage(file){return new Promise((res,rej)=>{const r=new FileReader();
  r.onload=()=>{const img=new Image();img.onload=()=>{const max=1280;let{width:w,height:h}=img;
    if(w>max||h>max){if(w>h){h=Math.round(h*max/w);w=max}else{w=Math.round(w*max/h);h=max}}
    const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(img,0,0,w,h);
    res(c.toDataURL('image/jpeg',0.82))};img.onerror=rej;img.src=r.result};r.onerror=rej;r.readAsDataURL(file)})}
document.getElementById('fileIn').addEventListener('change',async e=>{const files=[...e.target.files];e.target.value='';
  const ab=document.getElementById('attachBtn');ab.classList.add('busy');
  for(const file of files){if(!file.type||file.type.indexOf('image/')!==0){addMsg("That doesn't look like a photo — try an image file.","bot");continue}
    let url;try{url=await resizeImage(file)}catch(_){addMsg("Couldn't read that one. If it's a HEIC iPhone photo, save it as JPG first.","bot");continue}
    addImg(url);try{const r=await fetch('/upload',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({image:url})});
      const d=await r.json();addMsg(d.reply,'bot')}catch(_){addMsg("The photo didn't upload — try again in a sec.","bot")}}
  ab.classList.remove('busy')});
</script>
</body></html>"""


PRIVACY_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Privacy Policy | {{ b.name }}</title>
<meta name="description" content="Privacy policy for {{ b.name }}.">
<link rel="icon" href="{{ url_for('static', filename='images/logo.jpg') }}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--ink:#0c0b09;--ink2:#15130f;--cream:#f6f1e7;--mut:#a89c86;--gold:#d4af37;--gold-soft:#ecd089;--line:rgba(212,175,55,.22)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--ink);color:var(--cream);font-family:'Inter',system-ui,sans-serif;line-height:1.7;-webkit-font-smoothing:antialiased}
a{color:var(--gold-soft);text-decoration:none}
a:hover{color:var(--gold)}
.wrap{max-width:860px;margin:0 auto;padding:48px 22px 72px}
.brand{display:flex;align-items:center;gap:12px;margin-bottom:44px;color:var(--gold);font-family:'Fraunces',Georgia,serif;font-size:20px;font-weight:600}
.brand img{width:42px;height:42px;border-radius:50%;border:1px solid var(--line)}
.back{display:inline-flex;margin-bottom:22px;color:var(--gold-soft);font-size:14px}
.eyebrow{font-size:12px;letter-spacing:.26em;text-transform:uppercase;color:var(--gold);font-weight:600}
h1{font-family:'Fraunces',Georgia,serif;font-size:clamp(34px,7vw,58px);line-height:1.05;margin:12px 0 16px;color:#fff}
h2{font-family:'Fraunces',Georgia,serif;font-size:24px;margin:34px 0 8px;color:#fff}
p,li{color:#d8cfbc;font-size:16px}
ul{padding-left:22px;margin:10px 0 0}
.panel{background:var(--ink2);border:1px solid var(--line);border-radius:16px;padding:26px;margin-top:30px}
.small{font-size:14px;color:var(--mut);margin-top:8px}
footer{border-top:1px solid var(--line);padding-top:24px;margin-top:42px;color:var(--mut);font-size:14px}
@media(max-width:560px){.wrap{padding:34px 18px 56px}.panel{padding:20px}p,li{font-size:15px}}
</style>
</head>
<body>
<main class="wrap">
  <a class="brand" href="/"><img src="{{ url_for('static', filename='images/logo.jpg') }}" alt="A&J logo">A&amp;J Property Maintenance</a>
  <a class="back" href="/">Back to home</a>
  <div class="eyebrow">Privacy Policy</div>
  <h1>How we handle your information</h1>
  <p>This privacy policy explains how {{ b.name }} collects and uses information when you contact us through this website.</p>
  <p class="small">Last updated: 25 June 2026</p>

  <section class="panel">
    <h2>Who we are</h2>
    <p>{{ b.name }} provides property maintenance services across {{ b.area_line }}. If you have questions about this policy, contact us at <a href="mailto:{{ b.email_public }}">{{ b.email_public }}</a> or call <a href="tel:+{{ b.phone_e164 }}">{{ b.phone_display }}</a>.</p>

    <h2>What information we collect</h2>
    <p>When you use the site, chat assistant, quote form, phone links or email links, we may collect:</p>
    <ul>
      <li>Your name, phone number, email address, postcode or area.</li>
      <li>Details about the job you want quoted.</li>
      <li>Photos you upload through the chat to help us understand the work.</li>
      <li>The conversation you have with the website assistant.</li>
      <li>Basic technical information needed to run the website, such as session cookies and server logs.</li>
    </ul>

    <h2>How we use it</h2>
    <p>We use your information to respond to enquiries, prepare quotes, arrange visits, manage customer communication, improve the website and protect the site from spam or abuse.</p>

    <h2>Chat assistant and uploaded photos</h2>
    <p>The website assistant collects the details you provide and emails them to the business so we can follow up. If you upload photos, those photos may be included with the enquiry email.</p>

    <h2>Cookies</h2>
    <p>This site uses essential session cookies so the chat can keep track of the current conversation. These cookies are used to make the website work and are not used for advertising.</p>

    <h2>Who we share information with</h2>
    <p>We do not sell your information. We may use trusted service providers to operate the website, process chat messages, send enquiry emails, host the site and manage customer communication. These providers only process information for the purposes of running the service.</p>

    <h2>How long we keep information</h2>
    <p>We keep enquiry details for as long as needed to respond to you, provide a quote, carry out work, keep business records and deal with any follow-up questions. You can ask us to delete your enquiry information where we no longer need it.</p>

    <h2>Your rights</h2>
    <p>You can contact us to ask for a copy of the personal information we hold about you, to correct it, or to ask us to delete it where appropriate. Email <a href="mailto:{{ b.email_public }}">{{ b.email_public }}</a>.</p>

    <h2>Changes to this policy</h2>
    <p>We may update this policy from time to time. The latest version will always be shown on this page.</p>
  </section>

  <footer>© {{ b.name }} Ltd · {{ b.postcode }} Portsmouth</footer>
</main>
</body>
</html>"""


def ensure_session():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())


@app.route("/")
def home():
    ensure_session()
    return render_template_string(PAGE, b=BUSINESS, services=SERVICES,
                                  portfolio=PORTFOLIO, filters=FILTERS,
                                  videos=VIDEOS, reviews=REVIEWS, hero_video=HERO_VIDEO)


@app.route("/privacy-policy")
def privacy_policy():
    return render_template_string(PRIVACY_PAGE, b=BUSINESS)


@app.route("/sitemap.xml")
def sitemap():
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           '<url><loc>https://aj-propertymaintenance.co.uk/</loc></url>'
           '<url><loc>https://aj-propertymaintenance.co.uk/privacy-policy</loc></url>'
           '</urlset>')
    return Response(xml, mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\n", mimetype="text/plain")


@app.route("/chat", methods=["POST"])
def chat_endpoint():
    session_id = session.get("session_id") or str(uuid.uuid4())
    session["session_id"] = session_id
    if session_id not in all_conversations:
        all_conversations[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversation = all_conversations[session_id]

    data = request.get_json(silent=True) or {}
    if (data.get("website") or "").strip():        # honeypot
        return jsonify({"reply": "Thanks!"})

    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"reply": "Sorry, I didn't catch that — could you type that again?"})

    now = time.time()
    recent = [t for t in chat_activity.get(session_id, []) if now - t < 60]
    if len(recent) >= 20:
        return jsonify({"reply": "You're sending messages very quickly — give it a few seconds and try again."})
    if len(conversation) >= 60:
        return jsonify({"reply": "Thanks for all the detail! Drop your name and number and the team will pick this up with you personally."})
    recent.append(now)
    chat_activity[session_id] = recent

    conversation.append({"role": "user", "content": user_message})
    status = _conversation_status(conversation, session_id)
    next_item = _next_missing_item(status)
    try:
        messages = list(conversation)
        messages.append({"role": "system", "content": _chat_memory_hint(conversation, session_id)})
        response = client_chat(
            model="llama-3.3-70b-versatile", messages=messages, max_tokens=256, timeout=20)
        ai_reply = response.choices[0].message.content
    except Exception as e:
        print(f"Chat completion failed: {e}")
        conversation.pop()
        return jsonify({"reply": "Sorry, I had a brief hiccup there — could you send that again?"})

    lead_ready = bool(re.search(r"\[\[?\s*READY\s*\]?\]", ai_reply, re.I))
    ai_reply = re.sub(r"\[\[?\s*READY\s*\]?\]", "", ai_reply).replace("[LEAD_CAPTURED]", "").strip()
    if next_item == "done":
        lead_ready = True
    if next_item != "done" and _reply_repeats_answered_item(ai_reply, status):
        ai_reply = _fixed_next_question(next_item) or ai_reply
        lead_ready = False
    if not ai_reply:
        ai_reply = ("Thanks — that's everything we need for now. A&J will be in touch shortly "
                    "to arrange your free quote.")
    conversation.append({"role": "assistant", "content": ai_reply})

    if session_id not in notified_sessions and has_contact_info(conversation):
        if lead_ready or _looks_like_closing(user_message) or len(conversation) >= 24:
            notified_sessions.add(session_id)
            send_lead_email(list(conversation), list(session_images.get(session_id, [])))

    return jsonify({"reply": ai_reply})


@app.route("/upload", methods=["POST"])
def upload_endpoint():
    session_id = session.get("session_id") or str(uuid.uuid4())
    session["session_id"] = session_id
    if session_id not in all_conversations:
        all_conversations[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversation = all_conversations[session_id]

    data = request.get_json(silent=True) or {}
    image = _decode_image_data_url(data.get("image", ""))
    if image is None:
        return jsonify({"reply": "Sorry, I couldn't read that image. Please try a JPG or PNG."}), 400

    images = session_images.setdefault(session_id, [])
    if len(images) >= MAX_IMAGES_PER_SESSION:
        return jsonify({"reply": "Thanks — that's plenty of photos for now. Leave your name and number and we'll take a look."})
    images.append(image)
    conversation.append({"role": "user", "content": "(Customer attached a photo of the job)"})
    reply = ("Thanks, got your photo — that really helps us picture the job. Add more if you like, "
             "or leave your name and number and we'll get you a free quote.")
    conversation.append({"role": "assistant", "content": reply})
    if session_id in notified_sessions:
        send_photo_followup(list(conversation), [image])
    return jsonify({"reply": reply})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port)
