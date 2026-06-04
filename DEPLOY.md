# Deployment Guide — Kim's Finance Tracker

## What you need
- A GitHub account (free) → github.com
- A Streamlit Cloud account (free) → share.streamlit.io

---

## Step 1 — Create a .gitignore file

Before pushing anything, create a file called `.gitignore` in this folder with this content:

```
# Never commit real bank data
*.csv
*.xlsx
*.xls

# Python
__pycache__/
*.pyc
.env

# Mac
.DS_Store
.~lock.*
```

This ensures your actual bank statements never get pushed to GitHub.

---

## Step 2 — Push to GitHub

### First time (create the repo):

1. Go to github.com → click **New repository**
2. Name it: `finance-buddy` (private recommended)
3. Do NOT check "Add a README" — leave it empty
4. Copy the repo URL (looks like `https://github.com/yourusername/finance-buddy.git`)

Then in Terminal, navigate to this folder and run:

```bash
cd "/Users/kimvuong/Documents/Finance Tracker/Finance buddy"
git init
git add app.py requirements.txt merchant_rules.json merchant_registry.json zelle_registry.json DEPLOY.md
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/yourusername/finance-buddy.git
git push -u origin main
```

### Every time you make changes:

```bash
cd "/Users/kimvuong/Documents/Finance Tracker/Finance buddy"
git add app.py merchant_rules.json merchant_registry.json zelle_registry.json
git commit -m "Update rules and app"
git push
```

---

## Step 3 — Deploy on Streamlit Cloud

1. Go to **share.streamlit.io** and sign in with GitHub
2. Click **New app**
3. Select:
   - Repository: `yourusername/finance-buddy`
   - Branch: `main`
   - Main file path: `app.py`
4. Click **Deploy**

Streamlit will build and host your app. You'll get a public URL like:
`https://yourusername-finance-buddy-app-xxxx.streamlit.app`

---

## Step 4 — Keep rules in sync

When you classify transactions locally (Review Queue saves rules to `merchant_rules.json` automatically), push the updated file to GitHub:

```bash
git add merchant_rules.json zelle_registry.json merchant_registry.json
git commit -m "Update classification rules"
git push
```

Streamlit Cloud will auto-redeploy within ~1 minute.

---

## Files that belong in the repo

| File | Include? | Why |
|---|---|---|
| `app.py` | ✅ Yes | The app itself |
| `requirements.txt` | ✅ Yes | Tells Streamlit what to install |
| `merchant_rules.json` | ✅ Yes | Your classification rulebook |
| `merchant_registry.json` | ✅ Yes | Merchant memory |
| `zelle_registry.json` | ✅ Yes | Zelle people memory |
| `*.csv` | ❌ Never | Real bank data — keep local only |
| `*.xlsx` | ❌ Never | Real bank data — keep local only |

---

## Tips

- Keep the repo **private** so your financial rules aren't public
- The app runs entirely in your browser session — uploaded CSV files are never stored by Streamlit
- If you want the app to remember classifications across sessions (not just the current upload), push updated `merchant_rules.json` after classifying
