#!/usr/bin/env python3
"""Kim's Finance Dashboard v4 — grouped spending table, recurring block, merged food"""

import streamlit as st
import pandas as pd
import json
import hashlib
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
import io

st.set_page_config(
    page_title="Kim's Finance Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Design System ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background:#F4FAFD; border-right:1px solid #C9E8F5; }
[data-testid="stSidebar"] .stRadio label { font-size:14px; }
div[data-testid="metric-container"] {
    background:#F4FAFD; border:1px solid #C9E8F5;
    border-radius:10px; padding:14px 18px;
}
.ice-card {
    background:#F4FAFD; border:1px solid #C9E8F5;
    border-radius:10px; padding:1rem 1.25rem; margin-bottom:10px;
}
.insight-box {
    background:#EBF5FB; border-left:4px solid #2196F3;
    border-radius:0 8px 8px 0; padding:14px 18px; margin:6px 0;
    font-size:14px; line-height:1.7; color:#1a1a1a;
}
.insight-box b { font-weight:600; }
.insight-box ul { margin:6px 0 0 18px; }
.insight-box li { margin-bottom:4px; }
.section-label {
    font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.06em; color:#5D8AA8; margin-bottom:8px;
}
.cat-dot { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:6px; vertical-align:middle; }
.pos { color:#1E8449; font-weight:600; }
.neg { color:#C0392B; font-weight:600; }
.warn { color:#B7770D; font-weight:600; }
.muted { color:#888; }
table.clean { width:100%; border-collapse:collapse; font-size:13px; }
table.clean th { font-size:11px; color:#888; font-weight:400; padding:0 8px 7px; border-bottom:1px solid #e8e8e8; text-align:right; }
table.clean th:first-child { text-align:left; }
table.clean td { padding:7px 8px; border-bottom:1px solid #f0f0f0; color:#1a1a1a; text-align:right; vertical-align:middle; }
table.clean td:first-child { text-align:left; }
table.clean tr.highlight td { background:#EBF5FB; font-weight:600; }
table.clean tr.footer td { border-top:2px solid #ddd; border-bottom:none; font-weight:600; }
table.clean tr.group-hdr td {
    background:#F4FAFD; font-size:11px; font-weight:600; text-transform:uppercase;
    letter-spacing:.06em; color:#5D8AA8; padding:6px 8px;
    border-bottom:1px solid #C9E8F5; border-top:1px solid #C9E8F5;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORIES — MECE, direction-aware
# ══════════════════════════════════════════════════════════════════════════════

OUTFLOW_CATS = [
    "Food > Food / Coffee / Eat Out",
    "Food > Groceries",
    "Housing > Rent",
    "Housing > Utilities",
    "Housing > Internet",
    "Housing > Living",
    "Transportation > Uber",
    "Transportation > Gas",
    "Transportation > Rideshare",
    "Transportation > Parking",
    "Transportation > Public Transit",
    "Transportation > Insurance",
    "Education > Tuition",
    "Education > Books",
    "Education > Software",
    "Education > School Supplies",
    "Subscriptions > Streaming",
    "Subscriptions > Apps",
    "Subscriptions > Gym",
    "Subscriptions > Cloud Storage",
    "Subscriptions > LinkedIn",
    "Subscriptions > AI Tools",
    "Personal > Clothing",
    "Personal > Grooming",
    "Personal > Entertainment",
    "Personal > Shopping",
    "Savings > Money Transfer to Savings Account",
    "Savings > Investment Account Transfer",
    "Savings > Webull",
    "Savings > Fidelity",
    "Other > Bank Fees",
    "Credit Card > CC Payment - Exclude from Spending",
]

INFLOW_CATS = [
    "Income > Paycheck",
    "Income > Family Support",
    "Income > Consulting",
    "Income > Refund",
    "Income > Financial Aid",
    "Income > Scholarships",
    "Savings > Transfer Back from Savings",
    "Income > Other",
]

ALL_CATS = sorted(set(OUTFLOW_CATS + INFLOW_CATS))

EXCLUDE_FROM_SPENDING = {
    "CC Payment - Exclude from Spending",
    "Money Transfer to Savings Account",
    "Transfer Back from Savings",
    "Emergency Fund",
    "Investment Account Transfer",
    "Webull",
    "Fidelity",
}

# Categories where MoM comparison doesn't apply (fixed/semester costs)
FIXED_CATS = {"Tuition", "Rent", "Insurance"}

# Display order for spending table groups
GROUP_ORDER = ["Education", "Housing", "Food", "Transportation", "Personal", "Subscriptions", "Other"]

# Groups excluded from recurring block
RECURRING_EXCLUDE_GROUPS = {"Food", "Income", "Savings", "Credit Card"}

# Monthly spending budgets — add categories here if you want a budget bar in the dashboard
# e.g. "Food / Coffee / Eat Out": 400
BUDGETS = {}

CAT_COLORS = {
    "Food / Coffee / Eat Out": "#E24B4A",
    "Groceries":               "#639922",
    "Clothing":                "#7F77DD",
    "Uber":                    "#378ADD",
    "Rideshare":               "#378ADD",
    "Gas":                     "#45B7D1",
    "Subscriptions":           "#1D9E75",
    "LinkedIn":                "#1D9E75",
    "Entertainment":           "#F0A500",
    "Rent":                    "#96CEB4",
    "Utilities":               "#96CEB4",
}


# ══════════════════════════════════════════════════════════════════════════════
# CORE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def load_rules():
    for p in [Path(__file__).parent / "merchant_rules.json",
              Path(__file__).parent.parent / "merchant_rules.json"]:
        if p.exists():
            with open(p) as f:
                return json.load(f).get("rules", [])
    return []


def classify(description, rules):
    d = description.upper()
    # Remap old food categories to merged one
    for rule in rules:
        for kw in rule.get("keywords", []):
            if kw.upper() in d:
                g = rule.get("group", "Unknown")
                c = rule.get("category", "Needs Review")
                # Merge Coffee and Matcha + Food / Eat Out → Food / Coffee / Eat Out
                if c in ("Coffee and Matcha", "Food / Eat Out"):
                    c = "Food / Coffee / Eat Out"
                return g, c, rule.get("confidence", "medium")
    return "Unknown", "Needs Review", "low"


def make_id(date, description, amount):
    raw = f"{date}|{description.strip().upper()}|{round(float(amount), 2)}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def save_rule_to_json(description, group, category):
    """Persist a user classification as a keyword rule so future uploads auto-classify it."""
    rules_path = Path(__file__).parent / "merchant_rules.json"
    if not rules_path.exists():
        return
    try:
        with open(rules_path) as f:
            data = json.load(f)
        # Extract keyword: strip trailing codes after '*', take first 4 words
        raw = description.upper().strip()
        keyword = raw.split("*")[0].strip()
        keyword = " ".join(keyword.split()[:4]).strip()
        if not keyword or len(keyword) < 3:
            return
        # If keyword already exists in a rule, update it rather than duplicate
        for rule in data.get("rules", []):
            existing_kws = [k.upper() for k in rule.get("keywords", [])]
            if any(keyword in k or k in keyword for k in existing_kws):
                rule["group"]    = group
                rule["category"] = category
                with open(rules_path, "w") as f:
                    json.dump(data, f, indent=2)
                load_rules.clear()
                return
        # New rule — insert at top so it takes priority
        data["rules"].insert(0, {
            "keywords":   [keyword],
            "group":      group,
            "category":   category,
            "confidence": "high",
            "_note":      f"User-classified {datetime.now().strftime('%Y-%m-%d')}"
        })
        with open(rules_path, "w") as f:
            json.dump(data, f, indent=2)
        load_rules.clear()
    except Exception:
        pass


def parse_chase_csv(file):
    # index_col=False prevents pandas from treating the first column as the index
    # when data rows have a trailing comma (one more field than the header)
    try:    df = pd.read_csv(file, encoding="utf-8-sig", index_col=False)
    except: df = pd.read_csv(file, encoding="latin-1", index_col=False)
    col_map = {}
    for col in df.columns:
        low = col.lower().strip()
        if "posting date" in low and "date" not in col_map.values(): col_map[col] = "date"
        elif "transaction date" in low and "date" not in col_map.values(): col_map[col] = "date"
        elif low == "date" and "date" not in col_map.values(): col_map[col] = "date"
        elif "description" in low: col_map[col] = "description"
        elif low == "amount": col_map[col] = "amount"
        elif low == "balance": col_map[col] = "balance"
    df = df.rename(columns=col_map)
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(
            df["amount"].astype(str).str.replace(",","").str.replace("$","").str.strip(),
            errors="coerce")
    if "balance" in df.columns:
        df["balance"] = pd.to_numeric(
            df["balance"].astype(str).str.replace(",","").str.replace("$","").str.strip(),
            errors="coerce")
    df = df.dropna(subset=["date","description","amount"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["date_sort"] = df["date"]
    df["date"] = df["date"].dt.strftime("%m/%d/%Y")
    keep = ["date","date_sort","description","amount"]
    if "balance" in df.columns: keep.append("balance")
    return df[keep].reset_index(drop=True)


def process_transactions(raw_df, rules):
    rows = []
    for _, row in raw_df.iterrows():
        g, c, conf = classify(str(row["description"]), rules)
        rows.append({
            "id":          make_id(str(row["date"]), str(row["description"]), row["amount"]),
            "date":        row["date"],
            "date_sort":   row.get("date_sort", row["date"]),
            "description": str(row["description"]),
            "amount":      float(row["amount"]),
            "balance":     float(row["balance"]) if "balance" in row and pd.notna(row.get("balance")) else None,
            "direction":   "Inflow" if float(row["amount"]) > 0 else "Outflow",
            "group":       g,
            "category":    c,
            "confidence":  conf,
        })
    return pd.DataFrame(rows)


def get_df(): return st.session_state.get("df")
def set_df(df): st.session_state["df"] = df


def spending_subset(df):
    return df[(df["amount"] < 0) & (~df["category"].isin(EXCLUDE_FROM_SPENDING))].copy()


def fmt(n):    return f"${abs(n):,.0f}"
def fmtd(n):   return f"${abs(n):,.2f}"
def fmtpct(n): return f"{n:.1f}%"


# ══════════════════════════════════════════════════════════════════════════════
# MERCHANT NAME CLEANER
# ══════════════════════════════════════════════════════════════════════════════

def clean_merchant_name(desc):
    """Map raw transaction descriptions to readable merchant names."""
    d = str(desc).upper()
    mapping = [
        ("LINKEDIN",                 "LinkedIn Premium"),
        ("PERPLEXITY",               "Perplexity AI"),
        ("UBER ONE",                 "Uber One"),
        ("UBER*ONE",                 "Uber One"),
        ("UBER* MEMBER",             "Uber One"),
        ("UBER MEMBER",              "Uber One"),
        ("ALLTRAILS",                "AllTrails"),
        ("CHATGPT",                  "ChatGPT Plus"),
        ("OPENAI",                   "ChatGPT Plus"),
        ("CLAUDE",                   "Claude AI"),
        ("ANTHROPIC",                "Claude AI"),
        ("NETFLIX",                  "Netflix"),
        ("SPOTIFY",                  "Spotify"),
        ("AMAZON PRIME",             "Amazon Prime"),
        ("APPLE.COM/BILL",           "Apple Subscriptions"),
        ("ICLOUD",                   "iCloud Storage"),
        ("HULU",                     "Hulu"),
        ("DISNEY",                   "Disney+"),
        ("XFINITY",                  "Xfinity Internet"),
        ("COMCAST",                  "Comcast Internet"),
        ("AMERICAN CAMPUS",          "American Campus (Rent)"),
        ("NOTION",                   "Notion"),
        ("CURSOR",                   "Cursor AI"),
        ("MIDJOURNEY",               "Midjourney"),
        ("YOUTUBE PREMIUM",          "YouTube Premium"),
        ("GOOGLE ONE",               "Google One Storage"),
        ("DROPBOX",                  "Dropbox"),
        ("ADOBE",                    "Adobe Creative Cloud"),
        ("GITHUB",                   "GitHub"),
        ("FIGMA",                    "Figma"),
        ("DUOLINGO",                 "Duolingo"),
        ("CALM",                     "Calm App"),
        ("HEADSPACE",                "Headspace"),
        ("GYM",                      "Gym Membership"),
        ("PLANET FITNESS",           "Planet Fitness"),
        ("ANYTIME FITNESS",          "Anytime Fitness"),
    ]
    for keyword, name in mapping:
        if keyword in d:
            return name
    # Generic: first 3 words, title-cased, strip trailing digits/symbols
    words = desc.strip().split()[:3]
    cleaned = " ".join(w.capitalize() for w in words if not w.isdigit())
    return cleaned[:40]


# Subscription-type keywords for Transportation filtering
SUBSCRIPTION_KEYWORDS = [
    "ONE", "MEMBERSHIP", "SUBSCRIPTION", "MEMBER",
    "PLAN", "PASS", "COVERAGE", "INSURANCE", "ANNUAL",
]


# ══════════════════════════════════════════════════════════════════════════════
# RECURRING DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_recurring(df):
    """Find outflow transactions appearing 2+ times — estimated recurring charges."""
    df2 = df.copy()
    df2["date_parsed"] = pd.to_datetime(df2["date"], errors="coerce")
    outflows = df2[df2["amount"] < 0].copy()

    if outflows.empty:
        return pd.DataFrame()

    grp = outflows.groupby("description").agg(
        count=("amount", "count"),
        avg_amount=("amount", "mean"),
        last_date=("date_parsed", "max"),
        category=("category", "first"),
        group=("group", "first"),
    ).reset_index()

    recurring = grp[grp["count"] >= 2].copy()
    recurring["avg_amount"] = recurring["avg_amount"].abs()

    results = []
    for _, row in recurring.iterrows():
        # Skip excluded groups
        if row["group"] in RECURRING_EXCLUDE_GROUPS:
            continue

        dates = outflows[outflows["description"] == row["description"]]["date_parsed"].dropna().sort_values()
        if len(dates) >= 2:
            gaps = [(dates.iloc[i+1] - dates.iloc[i]).days for i in range(len(dates)-1)]
            avg_gap = sum(gaps) / len(gaps)
        else:
            avg_gap = 30

        if avg_gap < 10:
            freq = "Weekly"
            next_date = row["last_date"] + timedelta(days=7)
            monthly_equiv = row["avg_amount"] * 4.33
        elif avg_gap < 20:
            freq = "Bi-weekly"
            next_date = row["last_date"] + timedelta(days=14)
            monthly_equiv = row["avg_amount"] * 2.17
        elif avg_gap < 45:
            freq = "Monthly"
            next_date = row["last_date"] + timedelta(days=30)
            monthly_equiv = row["avg_amount"]
        elif avg_gap < 100:
            freq = "Bi-monthly"
            next_date = row["last_date"] + timedelta(days=60)
            monthly_equiv = row["avg_amount"] / 2
        else:
            freq = "Per semester"
            next_date = row["last_date"] + timedelta(days=int(avg_gap))
            monthly_equiv = row["avg_amount"] / 5

        # For Transportation: only keep subscription-type items (Uber One etc.)
        if row["group"] == "Transportation":
            desc_up = row["description"].upper()
            is_sub = any(kw in desc_up for kw in SUBSCRIPTION_KEYWORDS)
            # Also exclude variable-spend: weekly Uber trips, gas, parking
            if not is_sub or freq == "Weekly":
                continue

        results.append({
            "description":     row["description"],
            "merchant_name":   clean_merchant_name(row["description"]),
            "category":        row["category"],
            "group":           row["group"],
            "avg_amount":      row["avg_amount"],
            "count":           row["count"],
            "freq":            freq,
            "next_date":       next_date,
            "monthly_equiv":   monthly_equiv,
        })

    return pd.DataFrame(results) if results else pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# MONTHLY INSIGHTS — rule-based, McKinsey top-down
# ══════════════════════════════════════════════════════════════════════════════

def generate_insights(month_df, all_df, month_label):
    sp = spending_subset(month_df)
    sp["abs"] = sp["amount"].abs()
    inc = month_df[month_df["amount"] > 0]

    total_inc   = inc["amount"].sum()
    total_sp    = sp["abs"].sum()
    ratio       = (total_sp / total_inc * 100) if total_inc > 0 else 0

    sav_out = month_df[(month_df["amount"] < 0) & (month_df["category"] == "Money Transfer to Savings Account")]["amount"].abs().sum()
    sav_in  = month_df[(month_df["amount"] > 0) & (month_df["category"].isin(["Money Transfer to Savings Account","Transfer Back from Savings"]))]["amount"].sum()
    net_sav = sav_out - sav_in

    cat_totals = sp.groupby("category")["abs"].sum().sort_values(ascending=False)
    top_cat    = cat_totals.index[0] if len(cat_totals) else "Unknown"
    top_amt    = cat_totals.iloc[0]  if len(cat_totals) else 0

    food_total = sp[sp["category"].isin(["Groceries","Food / Coffee / Eat Out"])]["abs"].sum()
    clothing   = sp[sp["category"] == "Clothing"]["abs"].sum()
    uber       = sp[sp["category"].isin(["Uber","Rideshare"])]["abs"].sum()
    subs       = sp[sp["group"] == "Subscriptions"]["abs"].sum()

    # Compare to other months
    all_df2 = all_df.copy()
    all_df2["month"] = pd.to_datetime(all_df2["date"], errors="coerce").dt.to_period("M").astype(str)
    all_sp   = spending_subset(all_df2)
    all_sp["abs"] = all_sp["amount"].abs()
    monthly_spend = all_sp.groupby("month")["abs"].sum()
    avg_spend = monthly_spend.mean() if len(monthly_spend) > 1 else total_sp
    vs_avg    = ((total_sp - avg_spend) / avg_spend * 100) if avg_spend > 0 else 0

    # Headline
    if ratio < 50:
        headline = f"{month_label} was your most controlled month — spend ratio of {ratio:.0f}% is well within income."
    elif ratio < 80:
        headline = f"{month_label} spending was moderate ({ratio:.0f}% of income) — net positive but room to tighten."
    elif ratio < 100:
        headline = f"{month_label} spending at {ratio:.0f}% of income — approaching break-even, watch closely."
    else:
        headline = f"{month_label} spending exceeded income ({ratio:.0f}%) — a deficit month requiring corrective action."

    bullets = []
    bullets.append(f"<b>Income {fmt(total_inc)} · Spending {fmt(total_sp)} · Net {'+' if total_inc-total_sp>=0 else ''}{fmt(total_inc-total_sp)}</b> — spend ratio {ratio:.0f}%.")

    if net_sav > 0:
        bullets.append(f"<b>True net saved: {fmt(net_sav)}</b> ({fmt(sav_out)} transferred to savings{f', {fmt(sav_in)} pulled back' if sav_in > 0 else ''}).")

    if top_cat and top_amt > 0:
        pct_of_sp = top_amt / total_sp * 100 if total_sp > 0 else 0
        bullets.append(f"<b>Largest category: {top_cat} at {fmt(top_amt)}</b> — {pct_of_sp:.0f}% of all spending this month.")

    if food_total > 0:
        bullets.append(f"Food + coffee combined: <b>{fmt(food_total)}</b> ({food_total/total_inc*100:.1f}% of income). "
                       f"{'Above $400/month average — consider limiting delivery orders.' if food_total > 400 else 'Within a reasonable range.'}")

    if clothing > 200:
        bullets.append(f"<b>Clothing at {fmt(clothing)}</b> — your highest recurring discretionary risk. "
                       f"{'Exceeds food+coffee this month.' if clothing > food_total else 'Second-largest discretionary category.'}")

    if uber > 80:
        bullets.append(f"Uber/transport at <b>{fmt(uber)}</b> — treat this as a fixed cost and budget accordingly.")

    if len(monthly_spend) > 1:
        direction = "above" if vs_avg > 0 else "below"
        bullets.append(f"vs. monthly average: <b>{'+' if vs_avg>0 else ''}{vs_avg:.0f}%</b> {direction} your average spending of {fmt(avg_spend)}.")

    return headline, bullets


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def six_month_trend_html(full_df):
    """Compact 6-month Income / Spending / Spend% / MoM change table."""
    fdf = full_df.copy()
    fdf["date_parsed"] = pd.to_datetime(fdf["date"], errors="coerce")
    fdf["month_str"]   = fdf["date_parsed"].dt.to_period("M").astype(str)
    all_m = sorted(fdf["month_str"].dropna().unique().tolist())
    last6 = all_m[-6:]

    rows_data = []
    prev_sp_val = None
    for m in last6:
        mdf   = fdf[fdf["month_str"] == m]
        m_inc = mdf[mdf["amount"] > 0]["amount"].sum()
        m_sp  = spending_subset(mdf)["amount"].abs().sum()
        m_net = m_inc - m_sp
        sp_r  = m_sp / m_inc * 100 if m_inc > 0 else 0
        chg   = (m_sp - prev_sp_val) / prev_sp_val * 100 if prev_sp_val and prev_sp_val > 0 else None
        rows_data.append((m, m_inc, m_sp, m_net, sp_r, chg))
        prev_sp_val = m_sp

    header = "<tr><th>Month</th><th>Income</th><th>Spending</th><th>Net</th><th>Spend %</th><th>vs prev month</th></tr>"
    body   = ""
    for m, inc, sp, net, sp_r, chg in rows_data:
        net_cls   = "color:#1E8449;font-weight:600" if net >= 0 else "color:#C0392B;font-weight:600"
        ratio_cls = "color:#C0392B;font-weight:600" if sp_r > 85 else "color:#B7770D;font-weight:600" if sp_r > 70 else "color:#1E8449"
        if chg is None:
            chg_html = "<span style='color:#aaa'>—</span>"
        elif chg > 3:
            chg_html = f"<span style='color:#C0392B;font-weight:600'>↑ +{chg:.0f}%</span>"
        elif chg < -3:
            chg_html = f"<span style='color:#1E8449;font-weight:600'>↓ {chg:.0f}%</span>"
        else:
            chg_html = f"<span style='color:#888'>→ {chg:+.0f}%</span>"
        body += (
            f"<tr>"
            f"<td style='font-weight:600'>{m}</td>"
            f"<td style='text-align:right'>{fmt(inc)}</td>"
            f"<td style='text-align:right'>{fmt(sp)}</td>"
            f"<td style='text-align:right;{net_cls}'>{fmt(net)}</td>"
            f"<td style='text-align:right;{ratio_cls}'>{sp_r:.0f}%</td>"
            f"<td style='text-align:right'>{chg_html}</td>"
            f"</tr>"
        )
    return f"<table class='clean'>{header}{body}</table>"


def subscription_table_html(rec_df):
    """Deduplicated subscription table — no Category column, one row per merchant."""
    SHOW = ["Subscriptions", "Housing", "Education", "Transportation", "Other"]
    rdf  = rec_df[rec_df["group"].isin(SHOW)].copy()
    if rdf.empty:
        return "<p style='color:#888;font-size:13px'>No recurring charges detected.</p>"

    # Deduplicate: keep highest-amount row per clean merchant name
    rdf = rdf.sort_values("avg_amount", ascending=False).drop_duplicates(subset=["merchant_name"])
    rdf = rdf.sort_values(["group","avg_amount"], ascending=[True, False])

    monthly_only = rdf[rdf["freq"] != "Per semester"]
    total_mo = monthly_only["monthly_equiv"].sum()

    header = (
        "<tr><th>Merchant</th><th>Monthly cost</th>"
        "<th>Frequency</th><th>Next charge</th><th>Status</th></tr>"
    )
    body = ""
    prev_grp = None
    for _, row in rdf.iterrows():
        if row["group"] != prev_grp:
            body += (
                f"<tr class='group-hdr'><td colspan='5'>{row['group']}</td></tr>"
            )
            prev_grp = row["group"]
        next_str  = row["next_date"].strftime("%b %d") if pd.notna(row["next_date"]) else "—"
        freq_str  = row["freq"]
        if freq_str == "Per semester":
            badge = "<span style='font-size:11px;padding:2px 7px;border-radius:4px;background:#EBF5FB;color:#1A5276;font-weight:500'>Semester</span>"
            cost  = fmtd(row["avg_amount"])
        else:
            badge = "<span style='font-size:11px;padding:2px 7px;border-radius:4px;background:#EAF3DE;color:#3B6D11;font-weight:500'>Active</span>"
            cost  = fmtd(row["avg_amount"])
        body += (
            f"<tr>"
            f"<td style='padding-left:14px;font-weight:500;color:#1a1a1a'>{row['merchant_name']}</td>"
            f"<td style='text-align:right;color:#C0392B;font-weight:600'>{cost}</td>"
            f"<td style='color:#888;font-size:12px'>{freq_str}</td>"
            f"<td style='font-size:12px;color:#5D8AA8;font-weight:500'>{next_str}</td>"
            f"<td>{badge}</td>"
            f"</tr>"
        )
    footer = (
        f"<tr class='footer'><td>Monthly total (est.)</td>"
        f"<td style='text-align:right;color:#C0392B'>{fmt(total_mo)}</td>"
        f"<td colspan='3' style='font-size:12px;font-weight:400;color:#888'>"
        f"semester charges excluded</td></tr>"
    )
    return f"<table class='clean'>{header}{body}{footer}</table>"


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def render_sidebar():
    with st.sidebar:
        st.markdown("### 💰 Finance Tracker")
        st.caption("Kim's personal dashboard")
        st.markdown("---")
        page = st.radio("", [
            "📤  Upload",
            "📊  Dashboard",
            "📅  Monthly",
            "⚠️  Review Queue",
            "📋  Transactions",
            "📥  Export",
        ], label_visibility="collapsed")
        df = get_df()
        if df is not None:
            st.markdown("---")
            total   = len(df)
            flagged = len(df[df["category"] == "Needs Review"])
            st.caption(f"{total} transactions loaded")
            st.progress((total - flagged) / total if total else 0)
            if flagged > 0: st.warning(f"{flagged} need review")
            else:           st.success("Fully classified")
        st.markdown("---")
        st.caption("Built for Kim 💙")
    return page


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def page_upload(rules):
    st.title("Upload Bank Statement")
    st.caption("Drop your Chase CSV — every transaction is classified automatically using your rulebook.")
    st.markdown("---")
    c1, c2 = st.columns([2, 1])
    with c1:
        uploaded = st.file_uploader("Chase CSV", type=["csv","CSV"], label_visibility="collapsed")
        if uploaded:
            with st.spinner("Classifying…"):
                try:
                    raw  = parse_chase_csv(uploaded)
                    if raw.empty:
                        st.error("Could not read transactions — the CSV may be empty or have unexpected column names. Expected columns: Transaction Date (or Posting Date), Description, Amount.")
                        st.stop()
                    proc = process_transactions(raw, rules)
                    if proc.empty or "category" not in proc.columns:
                        st.error("Processing returned no transactions. Check that the file is a Chase checking or credit card CSV export.")
                        st.stop()
                    set_df(proc)
                    st.session_state["filename"] = uploaded.name
                except Exception as e:
                    st.error(f"Could not read file: {e}")
                    with st.expander("Debug — CSV columns found"):
                        try:
                            uploaded.seek(0)
                            import pandas as _pd
                            _df = _pd.read_csv(uploaded, nrows=2)
                            st.write("Columns:", _df.columns.tolist())
                            st.write("First row:", _df.head(1))
                        except Exception:
                            st.write("Could not read file at all.")
                    st.stop()
            df = get_df()
            if df is None or "category" not in df.columns:
                st.error("Something went wrong loading your transactions. Please try uploading again.")
                st.stop()
            flagged = len(df[df["category"] == "Needs Review"])
            ok      = len(df) - flagged
            inc_sum = df[df["amount"] > 0]["amount"].sum()
            sp_sum  = spending_subset(df)["amount"].abs().sum()
            st.success(f"✅  Loaded **{len(df)}** transactions from `{uploaded.name}`")
            st.markdown("---")
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Transactions", len(df))
            m2.metric("Auto-classified", ok)
            m3.metric("Needs Review", flagged)
            m4.metric("Net Cash Flow", fmt(inc_sum - sp_sum))
            st.info("👈  Go to **Dashboard** to see your analysis.")
        elif get_df() is not None:
            st.info(f"Loaded: **{st.session_state.get('filename','')}**  ({len(get_df())} transactions)")
            if st.button("Clear and upload new file"): st.session_state.pop("df",None); st.rerun()
    with c2:
        st.markdown("**How to download from Chase**")
        st.markdown("1. Log into chase.com\n2. Click your checking account\n3. Download → CSV\n4. Upload here")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def page_dashboard():
    st.title("Dashboard")
    df = get_df()
    if df is None: st.warning("Go to **Upload** first."); return

    df = df.copy()
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")

    # ── 6-month trend (always shows all data, no filter) ────────────────────
    st.markdown('<div class="section-label">Last 6 months</div>', unsafe_allow_html=True)
    st.markdown(six_month_trend_html(get_df()), unsafe_allow_html=True)
    st.markdown("---")

    # Month filter
    months = ["All time"] + sorted(
        df["date_parsed"].dt.to_period("M").astype(str).dropna().unique().tolist(), reverse=True
    )
    sel_month = st.selectbox("Period", months, label_visibility="collapsed")
    if sel_month != "All time":
        df = df[df["date_parsed"].dt.to_period("M").astype(str) == sel_month].copy()

    sp  = spending_subset(df); sp["abs"] = sp["amount"].abs()
    inc = df[df["amount"] > 0]

    total_inc  = inc["amount"].sum()
    total_sp   = sp["abs"].sum()
    net        = total_inc - total_sp
    sav_out    = df[(df["amount"] < 0) & (df["category"] == "Money Transfer to Savings Account")]["amount"].abs().sum()
    sav_in     = df[(df["amount"] > 0) & (df["category"].isin(["Money Transfer to Savings Account","Transfer Back from Savings"]))]["amount"].sum()
    net_saved  = sav_out - sav_in
    flagged    = len(df[df["category"] == "Needs Review"])

    # ── Stat cards ──────────────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Balance", fmt(df["balance"].dropna().iloc[0]) if "balance" in df.columns and df["balance"].notna().any() else "—")
    c2.metric("Money In",  fmt(total_inc))
    c3.metric("Money Out", fmt(total_sp),  delta=f"{total_sp/total_inc*100:.0f}% of income" if total_inc else None, delta_color="inverse")
    c4.metric("Net Saved", fmt(net_saved), delta=f"{fmt(sav_out)} in · {fmt(sav_in)} back", delta_color="normal")

    st.markdown("---")

    # ── Previous month data for MoM ─────────────────────────────────────────
    prev_group_totals = {}
    if sel_month != "All time":
        full_df = get_df().copy()
        full_df["date_parsed"] = pd.to_datetime(full_df["date"], errors="coerce")
        full_df["month_str"] = full_df["date_parsed"].dt.to_period("M").astype(str)
        all_months = sorted(full_df["month_str"].dropna().unique().tolist())
        if sel_month in all_months:
            idx = all_months.index(sel_month)
            if idx > 0:
                prev_m   = all_months[idx - 1]
                prev_df  = full_df[full_df["month_str"] == prev_m]
                prev_sp  = spending_subset(prev_df)
                prev_sp["abs"] = prev_sp["amount"].abs()
                prev_group_totals = prev_sp.groupby("group")["abs"].sum().to_dict()

    # ── Row: Spending table + Recreational ──────────────────────────────────
    col_left, col_right = st.columns([1.5, 1])

    with col_left:
        st.markdown('<div class="section-label">Spending by category — click to expand</div>', unsafe_allow_html=True)

        cat_detail = sp.groupby(["group","category"])["abs"].sum().reset_index()
        cat_detail.columns = ["group","category","total"]
        group_totals_cur = cat_detail.groupby("group")["total"].sum().to_dict()

        for group in GROUP_ORDER:
            g_total = group_totals_cur.get(group, 0)
            if g_total == 0:
                continue

            pct_inc = g_total / total_inc * 100 if total_inc > 0 else 0

            # MoM label for group
            prev_g = prev_group_totals.get(group, 0)
            if group in ("Education",) or prev_g == 0:
                mom_tag = ""
            else:
                chg = (g_total - prev_g) / prev_g * 100
                if chg > 3:
                    mom_tag = f"  ·  ↑ +{chg:.0f}%"
                elif chg < -3:
                    mom_tag = f"  ·  ↓ {chg:.0f}%"
                else:
                    mom_tag = ""

            with st.expander(f"{group}  ·  {fmt(g_total)}  ·  {pct_inc:.1f}% of income{mom_tag}"):
                # Budget bar — shown for any category in this group that has a budget
                g_cats_list = cat_detail[cat_detail["group"] == group]
                for _, gc_row in g_cats_list.iterrows():
                    budget = BUDGETS.get(gc_row["category"])
                    if budget:
                        spent    = gc_row["total"]
                        pct_bud  = min(spent / budget * 100, 100)
                        over     = spent > budget
                        bar_color = "#C0392B" if over else "#B7770D" if pct_bud > 80 else "#1E8449"
                        label     = f"{'⚠️ Over' if over else ''} {fmt(spent)} of {fmt(budget)} budget ({pct_bud:.0f}%)"
                        st.markdown(
                            f"<div style='margin-bottom:10px'>"
                            f"<div style='font-size:12px;color:#888;margin-bottom:4px'>"
                            f"{gc_row['category']} budget: {label}</div>"
                            f"<div style='background:#f0f0f0;border-radius:4px;height:6px'>"
                            f"<div style='width:{pct_bud:.0f}%;background:{bar_color};height:6px;border-radius:4px'></div>"
                            f"</div></div>",
                            unsafe_allow_html=True
                        )

                # Category breakdown (if multiple categories in this group)
                g_cats = cat_detail[cat_detail["group"] == group].sort_values("total", ascending=False)
                if len(g_cats) > 1:
                    cat_rows = "".join(
                        f"<tr><td style='padding-left:10px;color:#555'>{r['category']}</td>"
                        f"<td style='text-align:right'>{fmt(r['total'])}</td>"
                        f"<td style='text-align:right;color:#888'>{r['total']/g_total*100:.0f}%</td></tr>"
                        for _, r in g_cats.iterrows()
                    )
                    st.markdown(f"""
                    <table class='clean' style='margin-bottom:10px'>
                    <tr><th>Category</th><th>Amount</th><th>Split</th></tr>
                    {cat_rows}
                    </table>""", unsafe_allow_html=True)

                # Top transactions for this group
                top_tx = sp[sp["group"] == group].nlargest(6, "abs")
                tx_rows = "".join(
                    f"<tr><td>{r['date']}</td>"
                    f"<td>{r['description'][:36]}</td>"
                    f"<td style='color:#888;font-size:12px'>{r['category']}</td>"
                    f"<td style='text-align:right'>{fmtd(r['abs'])}</td></tr>"
                    for _, r in top_tx.iterrows()
                )
                st.markdown(f"""
                <table class='clean'>
                <tr><th>Date</th><th>Merchant</th><th>Category</th><th>Amount</th></tr>
                {tx_rows}
                <tr class='footer'>
                  <td colspan='3'>Group total</td>
                  <td style='text-align:right'>{fmt(g_total)}</td>
                </tr>
                </table>""", unsafe_allow_html=True)

        st.markdown(
            f"<div style='padding:8px 4px;font-size:13px;font-weight:600;"
            f"border-top:2px solid #ddd;margin-top:4px'>"
            f"Total spending: {fmt(total_sp)}</div>",
            unsafe_allow_html=True,
        )

    with col_right:
        # Recreational breakdown
        st.markdown('<div class="section-label">Recreational spending</div>', unsafe_allow_html=True)
        rec_cats  = ["Food / Coffee / Eat Out", "Groceries", "Clothing", "Uber", "Rideshare", "Entertainment", "Grooming"]
        rec_icons = {
            "Food / Coffee / Eat Out": "🍔",
            "Groceries":               "🛒",
            "Clothing":                "👗",
            "Uber":                    "🚗",
            "Rideshare":               "🚗",
            "Entertainment":           "🎭",
            "Grooming":                "💅",
        }
        rec_rows  = []
        for cat in rec_cats:
            amt = sp[sp["category"] == cat]["abs"].sum()
            if amt > 0: rec_rows.append((cat, amt))
        rec_rows.sort(key=lambda x: -x[1])
        rec_total = sum(a for _, a in rec_rows)

        rows_html = "".join(
            f"<tr><td>{rec_icons.get(c,'·')} {c}</td>"
            f"<td style='text-align:right'>{fmt(a)}</td>"
            f"<td style='text-align:right;color:#888'>{a/total_inc*100:.1f}%</td></tr>"
            for c, a in rec_rows
        )
        st.markdown(f"""
        <table class='clean'>
        <tr><th>Category</th><th>Amount</th><th>% income</th></tr>
        {rows_html}
        <tr class='footer'><td>Total</td><td style='text-align:right'>{fmt(rec_total)}</td><td></td></tr>
        </table>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Net savings box
        st.markdown('<div class="section-label">Net savings</div>', unsafe_allow_html=True)
        net_color = "pos" if net_saved > 0 else "neg"
        st.markdown(f"""
        <div class='ice-card' style='padding:12px 16px'>
        <div style='display:flex;justify-content:space-between;font-size:13px;color:#888;padding:3px 0'>
            <span>Transferred to savings</span><span class='pos'>+{fmt(sav_out)}</span>
        </div>
        <div style='display:flex;justify-content:space-between;font-size:13px;color:#888;padding:3px 0;border-bottom:1px solid #D6EAF8;margin-bottom:6px'>
            <span>Pulled back from savings</span><span class='neg'>{'-'+fmt(sav_in) if sav_in > 0 else '—'}</span>
        </div>
        <div style='display:flex;justify-content:space-between;font-size:15px;font-weight:600'>
            <span>True net saved</span><span class='{net_color}'>{fmt(net_saved)}</span>
        </div>
        </div>""", unsafe_allow_html=True)

        # On track — minimal
        if total_inc > 0:
            ratio = total_sp / total_inc * 100
            color = "#C0392B" if ratio > 95 else "#B7770D" if ratio > 80 else "#1E8449"
            label = "Overspending" if ratio > 95 else "Watch it" if ratio > 80 else "On track"
            st.markdown(f"""<div style='margin-top:10px;padding:7px 12px;background:#f8f8f8;border-radius:8px;font-size:12px;color:#888'>
            <span style='color:{color};font-weight:600'>{label}</span> — {ratio:.0f}% of income spent</div>""", unsafe_allow_html=True)

    # ── Recurring Block ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">Recurring charges &amp; subscriptions</div>', unsafe_allow_html=True)
    rec_df = detect_recurring(get_df())
    if rec_df.empty:
        st.caption("No recurring charges detected yet — upload more months of data.")
    else:
        monthly_est = rec_df[rec_df["freq"] != "Per semester"]["monthly_equiv"].sum()
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"padding:10px 14px;background:#F4FAFD;border:1px solid #C9E8F5;"
            f"border-radius:8px;margin-bottom:12px'>"
            f"<span style='font-size:12px;color:#888'>Estimated monthly recurring</span>"
            f"<span style='font-size:15px;font-weight:600'>{fmt(monthly_est)}"
            f"<span style='font-size:12px;font-weight:400;color:#888'>/mo</span>"
            f"&nbsp;·&nbsp;<span style='font-size:12px;color:#888'>{fmt(monthly_est*12)}/yr</span>"
            f"</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown(subscription_table_html(rec_df), unsafe_allow_html=True)

    # ── AI Insight ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="section-label">AI insight</div>', unsafe_allow_html=True)
    full_df2 = get_df()
    headline, bullets = generate_insights(df, full_df2, sel_month)
    bullets_html = "".join(f"<li>{b}</li>" for b in bullets)
    st.markdown(f"""
    <div class="insight-box">
    <p style='font-weight:600;margin-bottom:8px'>{headline}</p>
    <ul>{bullets_html}</ul>
    </div>""", unsafe_allow_html=True)



# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — MONTHLY (enhanced)
# ══════════════════════════════════════════════════════════════════════════════

def page_monthly():
    st.title("Monthly Analysis")
    df = get_df()
    if df is None: st.warning("Go to **Upload** first."); return

    df = df.copy()
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
    df["month"]       = df["date_parsed"].dt.to_period("M").astype(str)

    months = sorted(df["month"].dropna().unique().tolist(), reverse=True)
    if not months: st.info("No data."); return

    sel   = st.selectbox("Select month to analyze", months)
    m_df  = df[df["month"] == sel].copy()
    sp    = spending_subset(m_df); sp["abs"] = sp["amount"].abs()
    inc   = m_df[m_df["amount"] > 0]

    total_inc = inc["amount"].sum()
    total_sp  = sp["abs"].sum()
    sav_out   = m_df[(m_df["amount"] < 0) & (m_df["category"] == "Money Transfer to Savings Account")]["amount"].abs().sum()
    sav_in    = m_df[(m_df["amount"] > 0) & (m_df["category"].isin(["Money Transfer to Savings Account","Transfer Back from Savings"]))]["amount"].sum()
    net_sav   = sav_out - sav_in

    # ── Previous month data for MoM deltas ──────────────────────────────────
    all_months_sorted = sorted(df["month"].dropna().unique().tolist())
    prev_inc, prev_sp_val, prev_net_sav = 0.0, 0.0, 0.0
    if sel in all_months_sorted:
        idx = all_months_sorted.index(sel)
        if idx > 0:
            prev_m   = all_months_sorted[idx - 1]
            prev_mdf = df[df["month"] == prev_m]
            prev_inc = prev_mdf[prev_mdf["amount"] > 0]["amount"].sum()
            p_sp     = spending_subset(prev_mdf); p_sp["abs"] = p_sp["amount"].abs()
            prev_sp_val  = p_sp["abs"].sum()
            p_so  = prev_mdf[(prev_mdf["amount"] < 0) & (prev_mdf["category"] == "Money Transfer to Savings Account")]["amount"].abs().sum()
            p_si  = prev_mdf[(prev_mdf["amount"] > 0) & (prev_mdf["category"].isin(["Money Transfer to Savings Account","Transfer Back from Savings"]))]["amount"].sum()
            prev_net_sav = p_so - p_si
            prev_rec_cats = spending_subset(prev_mdf)
            prev_rec_cats["abs"] = prev_rec_cats["amount"].abs()
            prev_rec_total = prev_rec_cats[prev_rec_cats["category"].isin(
                ["Food / Coffee / Eat Out","Groceries","Clothing","Uber","Rideshare","Entertainment","Grooming"]
            )]["abs"].sum()
        else:
            prev_rec_total = 0.0
    else:
        prev_rec_total = 0.0

    def delta_str(curr, prev):
        if prev == 0: return None
        p = (curr - prev) / prev * 100
        return f"{p:+.0f}%"

    # ── Stat cards with deltas ───────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Income",   fmt(total_inc), delta=delta_str(total_inc, prev_inc))
    c2.metric("Spending", fmt(total_sp),  delta=delta_str(total_sp, prev_sp_val), delta_color="inverse")
    c3.metric("Net Flow", fmt(total_inc - total_sp))
    c4.metric("Net Saved",fmt(net_sav),   delta=delta_str(net_sav, prev_net_sav))
    st.markdown("---")

    # ── Pattern analysis ────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Pattern analysis</div>', unsafe_allow_html=True)
    headline, bullets = generate_insights(m_df, df, sel)
    bullets_html = "".join(f"<li>{b}</li>" for b in bullets)
    st.markdown(f"""
    <div class="insight-box">
    <p style='font-weight:600;margin-bottom:8px'>{headline}</p>
    <ul>{bullets_html}</ul>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Recreational + Net Savings side by side with MoM % ──────────────────
    r_col, s_col = st.columns(2)

    rec_cats  = ["Food / Coffee / Eat Out","Groceries","Clothing","Uber","Rideshare","Entertainment","Grooming"]
    rec_icons = {"Food / Coffee / Eat Out":"🍔","Groceries":"🛒","Clothing":"👗",
                 "Uber":"🚗","Rideshare":"🚗","Entertainment":"🎭","Grooming":"💅"}
    rec_rows_data = [(c, sp[sp["category"]==c]["abs"].sum()) for c in rec_cats if sp[sp["category"]==c]["abs"].sum() > 0]
    rec_rows_data.sort(key=lambda x: -x[1])
    rec_total_cur = sum(a for _,a in rec_rows_data)

    with r_col:
        st.markdown('<div class="section-label">Recreational spending</div>', unsafe_allow_html=True)
        if prev_rec_total > 0:
            rec_chg = (rec_total_cur - prev_rec_total) / prev_rec_total * 100
            chg_color = "#C0392B" if rec_chg > 3 else "#1E8449" if rec_chg < -3 else "#888"
            chg_arrow = "↑" if rec_chg > 3 else "↓" if rec_chg < -3 else "→"
            chg_badge = f"<span style='color:{chg_color};font-weight:600;font-size:13px'>{chg_arrow} {rec_chg:+.0f}% vs last month</span>"
        else:
            chg_badge = ""
        st.markdown(chg_badge, unsafe_allow_html=True)
        rec_body = "".join(
            f"<tr><td>{rec_icons.get(c,'·')} {c}</td>"
            f"<td style='text-align:right'>{fmt(a)}</td>"
            f"<td style='text-align:right;color:#888'>{a/total_inc*100:.1f}%</td></tr>"
            for c, a in rec_rows_data
        )
        st.markdown(f"""
        <table class='clean'>
        <tr><th>Category</th><th>Amount</th><th>% income</th></tr>
        {rec_body}
        <tr class='footer'><td>Total</td><td style='text-align:right'>{fmt(rec_total_cur)}</td><td></td></tr>
        </table>""", unsafe_allow_html=True)

    with s_col:
        st.markdown('<div class="section-label">Net savings</div>', unsafe_allow_html=True)
        if prev_net_sav != 0:
            sav_chg = net_sav - prev_net_sav
            sav_color = "#1E8449" if sav_chg >= 0 else "#C0392B"
            sav_arrow = "↑" if sav_chg >= 0 else "↓"
            sav_badge = f"<span style='color:{sav_color};font-weight:600;font-size:13px'>{sav_arrow} {fmt(abs(sav_chg))} vs last month</span>"
        else:
            sav_badge = ""
        st.markdown(sav_badge, unsafe_allow_html=True)
        net_color = "pos" if net_sav >= 0 else "neg"
        st.markdown(f"""
        <div class='ice-card' style='padding:12px 16px;margin-top:6px'>
        <div style='display:flex;justify-content:space-between;font-size:13px;color:#888;padding:3px 0'>
            <span>Transferred to savings</span><span class='pos'>+{fmt(sav_out)}</span>
        </div>
        <div style='display:flex;justify-content:space-between;font-size:13px;color:#888;padding:3px 0;
                    border-bottom:1px solid #D6EAF8;margin-bottom:6px'>
            <span>Pulled back</span><span class='neg'>{'-'+fmt(sav_in) if sav_in > 0 else '—'}</span>
        </div>
        <div style='display:flex;justify-content:space-between;font-size:15px;font-weight:600'>
            <span>True net saved</span><span class='{net_color}'>{fmt(net_sav)}</span>
        </div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── Subscriptions this month ─────────────────────────────────────────────
    st.markdown('<div class="section-label">Recurring &amp; subscriptions</div>', unsafe_allow_html=True)
    rec_df_m = detect_recurring(get_df())
    st.markdown(subscription_table_html(rec_df_m), unsafe_allow_html=True)

    st.markdown("---")

    # ── Category deep dive ───────────────────────────────────────────────────
    st.markdown('<div class="section-label">Category deep dive</div>', unsafe_allow_html=True)
    cat_totals = sp.groupby("category")["abs"].sum().sort_values(ascending=False)
    for cat, amt in cat_totals.items():
        pct     = amt / total_sp  * 100 if total_sp  > 0 else 0
        pct_inc = amt / total_inc * 100 if total_inc > 0 else 0
        with st.expander(f"{cat}  ·  {fmt(amt)}  ·  {pct:.0f}% of spending  ·  {pct_inc:.1f}% of income"):
            cat_tx = sp[sp["category"] == cat].sort_values("abs", ascending=False)
            tx_rows = "".join(
                f"<tr><td>{r['date']}</td><td>{r['description'][:45]}</td>"
                f"<td style='text-align:right'>{fmtd(r['abs'])}</td></tr>"
                for _, r in cat_tx.iterrows()
            )
            st.markdown(f"""
            <table class='clean'>
            <tr><th>Date</th><th>Merchant</th><th>Amount</th></tr>
            {tx_rows}
            </table>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── All months compared — with MoM spend change ──────────────────────────
    st.markdown('<div class="section-label">All months compared</div>', unsafe_allow_html=True)

    comp_data = []
    prev_out  = None
    for m in all_months_sorted:
        mdf   = df[df["month"] == m]
        m_sp2 = spending_subset(mdf); m_sp2["abs"] = m_sp2["amount"].abs()
        m_inc2 = mdf[mdf["amount"] > 0]["amount"].sum()
        m_out2 = m_sp2["abs"].sum()
        m_so2  = mdf[(mdf["amount"] < 0) & (mdf["category"] == "Money Transfer to Savings Account")]["amount"].abs().sum()
        m_si2  = mdf[(mdf["amount"] > 0) & (mdf["category"].isin(["Money Transfer to Savings Account","Transfer Back from Savings"]))]["amount"].sum()
        m_rat2 = m_out2 / m_inc2 * 100 if m_inc2 > 0 else 0
        net_s2 = m_so2 - m_si2
        spend_chg = (m_out2 - prev_out) / prev_out * 100 if prev_out and prev_out > 0 else None
        comp_data.append({
            "m": m, "inc": m_inc2, "out": m_out2,
            "net": m_inc2 - m_out2, "net_sav": net_s2,
            "rat": m_rat2, "chg": spend_chg, "sel": m == sel,
        })
        prev_out = m_out2

    tbl_rows = ""
    for r in comp_data:
        cls       = "class='highlight'" if r["sel"] else ""
        net_cls   = "pos" if r["net"] >= 0 else "neg"
        rat_color = "#C0392B" if r["rat"] > 85 else "#B7770D" if r["rat"] > 70 else "#1E8449"
        if r["chg"] is None:
            chg_html = "<span style='color:#aaa'>—</span>"
        elif r["chg"] > 3:
            chg_html = f"<span style='color:#C0392B;font-weight:600'>↑ +{r['chg']:.0f}%</span>"
        elif r["chg"] < -3:
            chg_html = f"<span style='color:#1E8449;font-weight:600'>↓ {r['chg']:.0f}%</span>"
        else:
            chg_html = f"<span style='color:#888'>→ {r['chg']:+.0f}%</span>"
        tbl_rows += (
            f"<tr {cls}>"
            f"<td><b>{r['m']}</b></td>"
            f"<td style='text-align:right'>{fmt(r['inc'])}</td>"
            f"<td style='text-align:right'>{fmt(r['out'])}</td>"
            f"<td style='text-align:right' class='{net_cls}'>{fmt(r['net'])}</td>"
            f"<td style='text-align:right;color:{rat_color};font-weight:600'>{r['rat']:.0f}%</td>"
            f"<td style='text-align:right'>{chg_html}</td>"
            f"<td style='text-align:right' class='pos'>{fmt(r['net_sav'])}</td>"
            f"</tr>"
        )
    st.markdown(f"""
    <table class='clean'>
    <tr><th>Month</th><th>Income</th><th>Spending</th><th>Net</th>
        <th>Spend %</th><th>Spend change</th><th>Net saved</th></tr>
    {tbl_rows}
    </table>""", unsafe_allow_html=True)
    st.caption("Highlighted = selected month.  Spend % = spending ÷ income.  Spend change = vs prior month.")

    # ── Trend chart — bars + spend ratio line ────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    months_list = [r["m"]   for r in comp_data]
    inc_list    = [r["inc"] for r in comp_data]
    out_list    = [r["out"] for r in comp_data]
    rat_list    = [r["rat"] for r in comp_data]

    fig = go.Figure()
    fig.add_bar(name="Income",   x=months_list, y=inc_list,
                marker_color="#2196F3", opacity=0.8)
    fig.add_bar(name="Spending", x=months_list, y=out_list,
                marker_color="#E24B4A", opacity=0.8)
    fig.add_scatter(name="Spend %", x=months_list, y=rat_list,
                    mode="lines+markers+text",
                    line=dict(color="#B7770D", width=2, dash="dot"),
                    marker=dict(size=6),
                    text=[f"{v:.0f}%" for v in rat_list],
                    textposition="top center",
                    yaxis="y2")
    fig.update_layout(
        barmode="group", height=300,
        margin=dict(l=0, r=40, t=10, b=0),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(tickprefix="$", tickformat=",.0f", title=""),
        yaxis2=dict(title="Spend %", overlaying="y", side="right",
                    range=[0, max(rat_list) * 1.4 if rat_list else 120],
                    ticksuffix="%", showgrid=False),
        legend=dict(orientation="h", y=-0.2),
        xaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — REVIEW QUEUE (direction-aware, MECE)
# ══════════════════════════════════════════════════════════════════════════════

def page_review_queue():
    st.title("Review Queue")
    st.caption("Classify uncategorized transactions. Categories shown match the transaction direction.")
    df = get_df()
    if df is None: st.warning("Go to **Upload** first."); return

    flagged = df[df["category"] == "Needs Review"].copy()
    if flagged.empty:
        st.success("🎉  All transactions are classified — nothing left to review!"); return

    total    = len(df)
    reviewed = total - len(flagged)
    st.progress(reviewed / total, text=f"{reviewed} of {total} classified  ({reviewed/total*100:.0f}%)")
    st.markdown(f"**{len(flagged)} transactions** need a category.")
    st.markdown("---")

    QUICK_OUT = [
        "Food > Food / Coffee / Eat Out",
        "Food > Groceries",
        "Personal > Clothing",
        "Personal > Entertainment",
        "Personal > Grooming",
        "Transportation > Uber",
        "Transportation > Gas",
        "Transportation > Parking",
        "Subscriptions > Apps",
        "Subscriptions > Streaming",
        "Subscriptions > LinkedIn",
        "Subscriptions > AI Tools",
        "Housing > Rent",
        "Housing > Utilities",
        "Housing > Internet",
        "Education > Tuition",
        "Education > Books",
        "Savings > Money Transfer to Savings Account",
        "Other > Bank Fees",
        "Credit Card > CC Payment - Exclude from Spending",
    ]

    QUICK_IN = [
        "Income > Paycheck",
        "Income > Family Support",
        "Income > Consulting",
        "Income > Refund",
        "Income > Financial Aid",
        "Savings > Transfer Back from Savings",
    ]

    for i, (idx, row) in enumerate(flagged.iterrows()):
        is_out  = row["amount"] < 0
        q_cats  = QUICK_OUT if is_out else QUICK_IN
        all_dir = OUTFLOW_CATS if is_out else INFLOW_CATS
        dir_lbl = "Outflow" if is_out else "Inflow"
        amt_col = "#C0392B" if is_out else "#1E8449"
        sign    = "-" if is_out else "+"

        st.markdown(f"""
        <div class='ice-card'>
        <div style='font-weight:600;font-size:14px;margin-bottom:4px'>{row['description']}</div>
        <span style='color:{amt_col};font-size:16px;font-weight:700'>{sign}{fmtd(abs(row['amount']))}</span>
        &nbsp;&nbsp;<span style='color:#888;font-size:13px'>{row['date']} · {dir_lbl}</span>
        </div>""", unsafe_allow_html=True)

        btn_cols = st.columns(4)
        for j, qcat in enumerate(q_cats):
            cat_label = qcat.split(" > ")[1]
            if btn_cols[j % 4].button(cat_label, key=f"q_{idx}_{j}", use_container_width=True):
                g, c = qcat.split(" > ", 1)
                df.loc[idx, "group"]    = g
                df.loc[idx, "category"] = c
                save_rule_to_json(row["description"], g, c)
                set_df(df); st.rerun()

        c_sel, c_btn = st.columns([3, 1])
        custom = c_sel.selectbox(
            "Or pick any category",
            ["— select —"] + all_dir,
            key=f"sel_{idx}",
            label_visibility="collapsed"
        )
        if c_btn.button("Apply", key=f"apply_{idx}"):
            if custom != "— select —":
                g, c = custom.split(" > ", 1)
                df.loc[idx, "group"]    = g
                df.loc[idx, "category"] = c
                save_rule_to_json(row["description"], g, c)
                set_df(df); st.rerun()

        st.markdown("---")
        if i >= 9:
            st.info(f"Showing first 10. Classify these, then the next batch will appear.")
            break


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — TRANSACTIONS
# ══════════════════════════════════════════════════════════════════════════════

def page_transactions():
    st.title("All Transactions")
    df = get_df()
    if df is None: st.warning("Go to **Upload** first."); return

    fc1,fc2,fc3,fc4 = st.columns([1,1,1,2])
    dir_f = fc1.selectbox("Direction", ["All","Inflow","Outflow"])
    grp_f = fc2.selectbox("Group",    ["All"] + sorted(df["group"].dropna().unique().tolist()))
    cat_f = fc3.selectbox("Category", ["All"] + sorted(df["category"].dropna().unique().tolist()))
    srch  = fc4.text_input("Search description", placeholder="e.g. Starbucks, Uber…")

    filt = df.copy()
    if dir_f != "All": filt = filt[filt["direction"] == dir_f]
    if grp_f != "All": filt = filt[filt["group"] == grp_f]
    if cat_f != "All": filt = filt[filt["category"] == cat_f]
    if srch:           filt = filt[filt["description"].str.contains(srch, case=False, na=False)]
    filt = filt.sort_values("date", ascending=False).reset_index(drop=True)

    st.caption(f"Showing {len(filt):,} of {len(df):,} transactions · {len(df[df['category']=='Needs Review'])} need review")

    dir_cats = OUTFLOW_CATS if dir_f == "Outflow" else INFLOW_CATS if dir_f == "Inflow" else ALL_CATS

    edited = st.data_editor(
        filt[["date","description","amount","direction","group","category","confidence"]],
        use_container_width=True, num_rows="fixed", height=520,
        column_config={
            "date":        st.column_config.TextColumn("Date",        width=100),
            "description": st.column_config.TextColumn("Description", width=280),
            "amount":      st.column_config.NumberColumn("Amount", format="$%.2f", width=100),
            "direction":   st.column_config.TextColumn("In/Out",      width=70),
            "group":       st.column_config.TextColumn("Group",       width=110),
            "category":    st.column_config.SelectboxColumn("Category", width=200, options=dir_cats),
            "confidence":  st.column_config.TextColumn("Confidence",  width=80),
        },
        disabled=["date","description","amount","direction","group","confidence"],
        hide_index=True, key="tx_editor",
    )

    if st.button("Save category changes", type="primary"):
        n = 0
        for i, row in edited.iterrows():
            mask = (df["date"]==row["date"]) & (df["description"]==row["description"]) & (df["amount"]==row["amount"])
            old  = df.loc[mask,"category"].values
            if len(old) > 0 and old[0] != row["category"]:
                new = row["category"]
                if " > " in new:
                    ng, nc = new.split(" > ", 1)
                    df.loc[mask,"group"] = ng; df.loc[mask,"category"] = nc
                else:
                    df.loc[mask,"category"] = new
                n += 1
        set_df(df)
        if n: st.success(f"Saved {n} change(s)."); st.rerun()
        else: st.info("No changes detected.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def page_export():
    st.title("Export")
    df = get_df()
    if df is None: st.warning("Go to **Upload** first."); return

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Excel (.xlsx)**")
        st.caption("Four sheets: All Transactions, Outflows, Inflows, Summary by Category")
        if st.button("Generate Excel", use_container_width=True):
            buf = io.BytesIO()
            sp2  = df[(df["direction"]=="Outflow") & (~df["category"].isin(EXCLUDE_FROM_SPENDING))].copy()
            sp2["amount"] = sp2["amount"].abs()
            inc2 = df[df["direction"]=="Inflow"].copy()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.drop(columns=["date_sort","date_parsed","balance"],errors="ignore").to_excel(w, sheet_name="All Transactions", index=False)
                sp2.drop(columns=["date_sort","date_parsed","balance"],errors="ignore").to_excel(w, sheet_name="Outflows", index=False)
                inc2.drop(columns=["date_sort","date_parsed","balance"],errors="ignore").to_excel(w, sheet_name="Inflows", index=False)
                summ = sp2.groupby(["group","category"])["amount"].agg(Total="sum",Count="count").reset_index().sort_values("Total",ascending=False)
                summ.to_excel(w, sheet_name="Summary by Category", index=False)
            buf.seek(0)
            st.download_button("Download Excel", data=buf,
                file_name=f"finance_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
    with c2:
        st.markdown("**CSV**")
        st.caption("Works in Excel, Numbers, and Google Sheets")
        csv_b = df.drop(columns=["date_sort","date_parsed","balance"],errors="ignore").to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", data=csv_b,
            file_name=f"transactions_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv", use_container_width=True)

    st.markdown("---")
    sp3  = df[(df["amount"]<0) & (~df["category"].isin(EXCLUDE_FROM_SPENDING))]
    inc3 = df[df["amount"]>0]
    snap = pd.DataFrame({
        "Metric":["Total Income","Total Spending","Net Cash Flow","Transactions","Needs Review"],
        "Value": [fmt(inc3["amount"].sum()), fmt(sp3["amount"].abs().sum()),
                  fmt(inc3["amount"].sum()+sp3["amount"].sum()),
                  str(len(df)), str(len(df[df["category"]=="Needs Review"]))]
    })
    st.dataframe(snap, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if "df" not in st.session_state: st.session_state["df"] = None
    rules = load_rules()
    page  = render_sidebar()

    if   page == "📤  Upload":       page_upload(rules)
    elif page == "📊  Dashboard":    page_dashboard()
    elif page == "📅  Monthly":      page_monthly()
    elif page == "⚠️  Review Queue": page_review_queue()
    elif page == "📋  Transactions": page_transactions()
    elif page == "📥  Export":       page_export()

if __name__ == "__main__":
    main()
