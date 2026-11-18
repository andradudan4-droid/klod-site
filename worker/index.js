// Cloudflare Worker for A&J Property Maintenance Solutions. The shared chat engine is
// in core.js; this file holds the A&J wording, send rule and email layout (as app.py).
import { makeWorker, row, transcript, transcriptHtml, urgencyBadge, urgentPrefix, photosLine, missedLine,
  findPhone, findEmail, findPostcode, hasContact } from "./core.js";
import { SYSTEM_PROMPT, LEAD_SUMMARY_PROMPT } from "./prompts.js";

// ---- app.py's checklist: has each lead detail come up yet? ----
const SERVICE_WORDS = /\b(bathroom|kitchen|bedroom|room|paint|painting|decorate|decorating|wallpaper|tiling|tile|floor|flooring|patio|paving|garden|fence|fencing|driveway|plumbing|electrical|repair|repairs|maintenance)\b/i;
const SCOPE_WORDS = /\b(room|rooms|bedroom|bedrooms|bathroom|kitchen|small|medium|large|m2|sqm|wall|walls|ceiling|ceilings|floor|floors|whole|part|refit)\b/i;
const PROPERTY_WORDS = /\b(domestic|commercial|home|house|flat|office|shop|restaurant|rental)\b/i;
const BUDGET_DECLINE_RE = /\b(not sure|unsure|don't know|dont know|rather not|no budget|not yet)\b/i;

function afterAssistantQuestion(conv, patterns) {
  let asked = false;
  for (const m of conv) {
    if (m.role === "assistant" && patterns.some((p) => m.content.toLowerCase().includes(p))) { asked = true; continue; }
    if (asked && m.role === "user" && m.content.trim()) return m.content.trim();
  }
  return null;
}

function status(conv) {
  const userText = conv.filter((m) => m.role === "user").map((m) => m.content).join(" ");
  const allText = conv.map((m) => m.content).join(" ").toLowerCase();
  const budget = afterAssistantQuestion(conv, ["budget"]);
  const urgency = afterAssistantQuestion(conv, ["how soon", "urgent", "urgency", "hoping to get this done"]);
  const name = afterAssistantQuestion(conv, ["name"]);
  return {
    job: SERVICE_WORDS.test(userText),
    scope: SCOPE_WORDS.test(userText),
    property: PROPERTY_WORDS.test(userText),
    photo: allText.includes("attached a photo") || allText.includes("paperclip") || allText.includes("arrange a visit"),
    budget: !!(budget && (/\d/.test(budget) || BUDGET_DECLINE_RE.test(budget))),
    urgency: !!urgency,
    name: !!(name && /[A-Za-z]{2,}/.test(name)),
    postcode: !!findPostcode(conv),
    contact: hasContact(conv),
  };
}

// Same rule as app.py: send when every detail is in, or after 6 messages once the
// job is known, or after 12 messages. (Lengths there included the system prompt.)
function sendNowAfter(full, conv) {
  const s = status(conv);
  const done = Object.values(s).every(Boolean);
  const n = full.length + 1;
  return done || n >= 12 || (s.job && n >= 6);
}

// ---- emails ----
function leadEmail({ pick, conv, images, missed }) {
  const fields = {
    Name: pick("name"),
    Phone: findPhone(conv),
    Email: findEmail(conv),
    Postcode: findPostcode(conv),
    Area: pick("location / area", "location", "area"),
    Job: pick("job / work wanted", "job", "work wanted"),
    Property: pick("property type (domestic or commercial)", "property type", "property"),
    Budget: pick("approx budget", "budget"),
    "Preferred timing": pick("preferred timing", "timing"),
    Urgency: pick("urgency (1-5 where 1=no rush, 5=urgent - infer from what they said)", "urgency"),
    Notes: pick("other notes", "notes"),
  };
  const line = "====================================";
  const text = ["NEW LEAD - A&J Property Maintenance Solutions", line];
  for (const [k, v] of Object.entries(fields)) if (v) text.push(`${k}: ${v}`);
  if (images.length) text.push(`Photos attached: ${images.length}`);
  if (missed) text.push(`Photos not attached (customer left the page): ${missed}`);
  text.push(line, "", "Full conversation:", "", transcript(conv));

  const { Urgency, ...rest } = fields;
  const html = '<!DOCTYPE html><html><body style="margin:0;background:#f0efea;padding:24px;' +
    'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif">' +
    '<div style="max-width:620px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;' +
    'box-shadow:0 2px 12px rgba(0,0,0,.07)"><div style="background:#0a0a0a;padding:24px 28px">' +
    '<div style="color:#D4AF37;font-size:12px;letter-spacing:.18em;text-transform:uppercase;font-weight:700">A&amp;J Property Maintenance Solutions</div>' +
    '<div style="color:#fff;font-size:21px;font-weight:700;margin-top:5px">New enquiry from your website</div></div>' +
    '<div style="padding:26px 28px"><p style="margin:0 0 20px;font-size:14px;color:#666">Here are the details captured by your website assistant:</p>' +
    urgencyBadge(Urgency) + photosLine(images.length) + missedLine(missed) +
    '<table style="width:100%;border-collapse:collapse;border:1px solid #eee;border-radius:8px;overflow:hidden;margin-bottom:28px">' +
    Object.entries(rest).map(([k, v]) => row(k, v)).join("") + '</table>' +
    '<div style="font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:#999;font-weight:700;margin-bottom:14px">Full conversation</div>' +
    transcriptHtml(conv, { userBg: "#f5f4f0", botLabel: "A&J Assistant", botColor: "#9a7d1a" }) + '</div>' +
    '<div style="background:#faf9f6;padding:16px 28px;border-top:1px solid #eee;font-size:12px;color:#aaa">' +
    'Sent automatically by the A&amp;J Property Maintenance Solutions website assistant.</div>' +
    '</div></body></html>';

  const contact = fields.Phone || fields.Email || "no number yet";
  const bits = [fields.Name, fields.Area || fields.Postcode].filter(Boolean);
  return {
    subject: urgentPrefix(Urgency) + "New lead - " + (bits.length ? [...bits, contact].join(" · ") : contact),
    text: text.join("\n"),
    html,
  };
}

function followUpEmail({ conv, images }) {
  const phone = findPhone(conv) || "Not provided";
  const email = findEmail(conv) || "Not provided";
  const postcode = findPostcode(conv) || "Not provided";
  return {
    subject: `Photo added - lead: ${phone}`,
    text: "ADDITIONAL PHOTO(S) - A&J\nRelates to a lead you've already been emailed about.\n" +
      `Phone: ${phone}\nEmail: ${email}\nPostcode: ${postcode}\nPhotos attached: ${images.length}\n`,
  };
}

export default makeWorker({
  SYSTEM_PROMPT,
  LEAD_SUMMARY_PROMPT,
  TEMPERATURE: 0.4,
  MAXED_REPLY: "Thanks for all the detail! Drop your name and number and the team will pick this up with you personally.",
  EMPTY_REPLY: "Thanks — that's everything we need for now. A&J will be in touch shortly to arrange your free quote.",
  sendNowAfter,
  leadEmail,
  followUpEmail,
});
