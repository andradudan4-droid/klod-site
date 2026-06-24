# A&J Property Maintenance — website

A bespoke Flask site: portfolio gallery, reviews, friendly AI quote bot (Groq),
photo upload, and email lead notifications (Resend).

---

## What's in this folder

```
klod-site/
├── app.py              ← the whole site + bot (edit business details at the top)
├── requirements.txt
├── Procfile            ← tells Render how to start the app
├── .gitignore
└── static/
    ├── images/
    │   ├── logo.jpg
    │   └── portfolio/  ← all the job photos (add more here)
    └── videos/         ← drop .mp4 clips here (see "Adding videos")
```

Everything you'll normally change lives in **three lists near the top of `app.py`**:
`BUSINESS` (name, phone, email, socials), `PORTFOLIO` (photos), `REVIEWS`, and `VIDEOS`.

---

## The keys you'll need (all have free tiers)

| Service | What it's for | Where |
|---|---|---|
| **Groq** | Powers the chat bot | https://console.groq.com → API Keys |
| **Resend** | Emails you each new lead | https://resend.com → API Keys |
| **GitHub** | Stores the code | https://github.com |
| **Render** | Hosts the live site | https://render.com |

You set these as **environment variables** on Render (Step 4) — never paste keys
into the code.

---

## Step 1 — (optional) run it on your own computer first

```bash
cd klod-site
pip install -r requirements.txt
export GROQ_API_KEY="your_groq_key"      # Windows: set GROQ_API_KEY=your_groq_key
python app.py
```

Open http://localhost:5001 . The site and gallery work without any keys; the bot
needs `GROQ_API_KEY`; lead emails need the Resend ones (Step 5).

---

## Step 2 — put the code on GitHub

Make a new **empty** repo on GitHub (e.g. `aj-site`), then in this folder:

```bash
cd klod-site
git init
git add .
git commit -m "A&J website"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/aj-site.git
git push -u origin main
```

If git asks you to log in, use a GitHub **Personal Access Token** as the password
(GitHub → Settings → Developer settings → Personal access tokens → generate one
with `repo` scope).

**Pushing future changes** (after editing anything):

```bash
git add .
git commit -m "what you changed"
git push
```

Render redeploys automatically every time you push. 🎉

---

## Step 3 — deploy on Render

1. Go to https://dashboard.render.com → **New** → **Web Service**.
2. Connect your GitHub and pick the `aj-site` repo.
3. Settings:
   - **Runtime:** Python
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
   - **Instance type:** Free
4. Click **Create Web Service**. First build takes ~2 minutes. You'll get a URL
   like `https://aj-site.onrender.com`.

> Heads-up: the Free tier sleeps after 15 min idle, so the first visit after a
> quiet spell takes ~30s to wake. Upgrading to the cheapest paid tier removes that.

---

## Step 4 — add the environment variables

In Render → your service → **Environment** → add these, then **Save** (it redeploys):

| Key | Value |
|---|---|
| `GROQ_API_KEY` | your Groq key |
| `SECRET_KEY` | any long random string (run `python -c "import secrets;print(secrets.token_hex(32))"`) |
| `RESEND_API_KEY` | your Resend key (Step 5) |
| `NOTIFY_TO` | the email address that should receive leads |
| `MAIL_FROM` | leave as `A&J Website <onboarding@resend.dev>` to start, change later (Step 5) |

The site works the moment `GROQ_API_KEY` and `SECRET_KEY` are set. Email needs Step 5.

---

## Step 5 — Resend (lead emails)

1. Sign up at https://resend.com.
2. **API Keys** → create one → put it in `RESEND_API_KEY` on Render.
3. To start, leave `MAIL_FROM` as `A&J Website <onboarding@resend.dev>` — Resend's
   shared test sender. Leads will arrive, but may land in spam.
4. **To make emails land properly** (recommended once it's live): in Resend →
   **Domains** → add `ajpropertymaintenanceltd.co.uk`, add the DNS records it gives
   you at the domain registrar, and once verified change `MAIL_FROM` to something
   like `A&J Website <leads@ajpropertymaintenanceltd.co.uk>`.

That's it — every completed chat now emails you a tidy lead with the job details,
urgency, contact info and any photos attached.

---

## Step 6 — (optional) point the real domain at it

In Render → Settings → **Custom Domains** → add the domain, then at the domain
registrar add the CNAME/A record Render shows you. Render issues HTTPS automatically.

---

## Adding more content later

**More photos** — drop the image into `static/images/portfolio/`, then add a line
to the `PORTFOLIO` list in `app.py`:

```python
{"img": P+"my-new-photo.jpg", "cat": "Bathrooms", "cap": "Short caption"},
```
`cat` must be one of: Bathrooms, Kitchens, Decorating, Paving & Gardens, Building,
Joinery, Exterior, Electrical.

**Videos** — put `clip.mp4` in `static/videos/`, then add to the `VIDEOS` list:

```python
{"src": "static/videos/clip.mp4",
 "poster": P+"bathroom-black-marble-bath.webp",   # thumbnail (optional)
 "cap": "Bathroom reveal"},
```
The whole video section stays hidden until `VIDEOS` has at least one entry. (Tip:
Instagram clips need downloading first — once you have the `.mp4` files, just drop
them in.)

**Google reviews** — add each one to the `REVIEWS` list:

```python
{"text": "the review text", "name": "Customer name", "where": "Area / postcode"},
```

Then `git add . && git commit -m "..." && git push` and it's live.

---

## Notes

- The owner's name in the bot's sign-off is set to "the A&J team". To personalise
  it, change `"owner"` in the `BUSINESS` dict at the top of `app.py`.
- The bot only emails a lead once it has a real phone number or email **and** has
  worked through the questions — so you won't get half-finished enquiries.
- `MAX_IMAGES_PER_SESSION`, rate limits and the bot's tone are all near the top of
  `app.py` if you ever want to tweak them.
# klod-site
