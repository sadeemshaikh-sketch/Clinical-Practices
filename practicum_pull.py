#!/usr/bin/env python3
"""
practicum_pull.py
------------------
Builds `data.json` for the practicum directory page.

WHAT IT NEEDS: Python 3 and the `duckdb` package (`pip install duckdb`).
No accounts and no API keys: the practice list comes from the Overture Maps
Foundation's open places dataset, read straight from its public release.

HOW TO RUN:
  python3 practicum_pull.py

WHAT IT DOES EACH RUN:
  1. Finds the latest Overture Maps release and reads the counselling,
     psychotherapy and psychology practices in Alberta and Ontario from it.
  2. Takes name, address, phone and website from that data.
  3. Visits each practice's own website for an email + therapy approaches.
  4. Writes everything to data.json (for the website).

Overture places data is licensed CDLA Permissive 2.0 (Meta, Microsoft and
others), Apache 2.0 (Foursquare) and CC0 1.0 (AllThePlaces). The licence
texts and the Foursquare notice are in the `licenses/` folder, and the
attribution is in the footer of index.html. Keep both if you change this.

The site is a directory only. It does not track, record or publish whether a
practice is accepting practicum students — that is asked of the practice
directly.
"""

import os
import re
import sys
import json
import time
import urllib.request
import urllib.error

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
# Overture Maps publishes a new release roughly monthly and deletes old ones,
# so the script looks up the newest release each run. Set OVERTURE_RELEASE
# (e.g. "2026-09-23.1") to pin one instead.
OVERTURE_S3 = "s3://overturemaps-us-west-2/release"

# Overture place categories (the `taxonomy.primary` field) that count as a
# counselling / psychotherapy / psychology practice. These were read off the
# actual data for Alberta and Ontario, not guessed. All of them sit under
# health_care > outpatient_care_facility > behavioral_or_mental_health_clinic.
# Deliberately left out: psychiatry (medical), hypnotherapy, behavior_analysis,
# addiction treatment centres, life coaches, career and credit counselling.
CATEGORIES = (
    "counseling",
    "psychotherapy",
    "psychology",
    "behavioral_or_mental_health_clinic",
    "family_counseling",
    "marriage_or_relationship_counseling",
    "sex_therapy",
    "sports_psychology",
)

# Postal codes starting with these letters are in Alberta (T) or Ontario
# (K, L, M, N, P). Used when a record has no province.
POSTCODE_PROVINCE = {"T": "AB", "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON"}
PROVINCE_CODES = {"AB": "AB", "ALBERTA": "AB", "ON": "ON", "ONTARIO": "ON"}
# A box around both provinces, so the query only reads the parts of the
# release that can contain them.
BBOX = {"xmin": -120.1, "xmax": -74.3, "ymin": 41.6, "ymax": 60.1}

# Stop without writing if a run finds fewer than this share of the practices
# currently in data.json. Overture renamed its categories once already
# (Aug -> Sep 2026); a silent rename would otherwise publish a thinner site.
# Set ALLOW_SHRINK=1 to accept a smaller list on purpose.
MIN_KEEP_RATIO = 0.75

MODALITIES = {
    # --- Therapy approaches ---
    "CBT":                 [r"\bcbt\b", "cognitive behav"],
    "DBT":                 [r"\bdbt\b", "dialectical behav"],
    "EMDR":                [r"\bemdr\b", "eye movement desensit"],
    "ACT":                 ["acceptance and commitment"],
    "EFT":                 ["emotionally focused"],
    "Narrative Therapy":   ["narrative therap"],
    "Psychodynamic":       ["psychodynamic", "psychoanaly"],
    "Solution-Focused":    ["solution-focused", "solution focused"],
    "Somatic":             ["somatic experiencing", "somatic therap"],
    "Mindfulness":         ["mindfulness"],
    "Play Therapy":        ["play therap"],
    "Art Therapy":         ["art therap"],
    "Music Therapy":       ["music therap"],
    "Group Therapy":       ["group therap"],
    # --- Presenting issues ---
    "Anxiety":             ["anxiety"],
    "Depression":          ["depression"],
    "Trauma & PTSD":       ["trauma", r"\bptsd\b"],
    "Grief":               ["grief", "bereavement"],
    "Stress":              ["stress management", "burnout"],
    "Anger Management":    ["anger management"],
    "Self Esteem":         ["self-esteem", "self esteem"],
    "OCD":                 [r"\bocd\b", "obsessive-compulsive", "obsessive compulsive"],
    "Eating Disorders":    ["eating disorder", "disordered eating"],
    "Addiction":           ["addiction", "substance use", "substance abuse"],
    "Alcohol Use":         ["alcohol use", "alcoholism"],
    "Bipolar":             ["bipolar"],
    "Borderline (BPD)":    [r"\bbpd\b", "borderline personality"],
    "Sleep":               ["insomnia", "sleep issues", "sleep problems"],
    "Chronic Pain":        ["chronic pain", "chronic illness"],
    "Body Image":          ["body image"],
    # --- Populations ---
    "Child":               ["child therap", "children's mental", "kids therap"],
    "Teen":                ["teen", "adolescent"],
    "Couples":             ["couples"],
    "Family":              ["family therap", "family counsel"],
    "Marriage":            ["marriage counsel", "marital therap"],
    "Seniors":             ["seniors", "older adults", "geriatric"],
    "Men's Issues":        ["men's issues", "men's mental health"],
    "Women's Issues":      ["women's issues", "women's mental health"],
    "Perinatal":           ["postpartum", "perinatal", "maternal mental"],
    "LGBTQ+":              ["lgbtq", "2slgbtq", "gender identity", "gender-affirming"],
    "Indigenous":          ["indigenous", "first nations", "m\u00e9tis"],
    "Newcomers":           ["newcomer", "immigrant", "refugee"],
    "Veterans & First Responders": ["veteran", "first responder"],
    "Students":            ["university students", "college students", "student mental health"],
    # --- Neurodevelopmental & assessment ---
    "ADHD":                [r"\badhd\b", r"\badd\b"],
    "Autism":              ["autism", r"\basd\b", "neurodivergent", "neurodiversity"],
    "Assessment":          ["psychoeducational assess", "psychological assess", "psych assessment"],
    # --- Relationship & life ---
    "Relationship Issues": ["relationship issues", "relationship difficulties"],
    "Divorce":             ["divorce", "separation"],
    "Parenting":           ["parenting"],
    "Career":              ["career counsel", "career guidance"],
    "Domestic Abuse":      ["domestic abuse", "domestic violence", "intimate partner violence"],
    "Sexual Abuse":        ["sexual abuse", "sexual assault"],
    "Sex Therapy":         ["sex therap", "sexual health therap"],
    "Spirituality":        ["spirituality", "faith-based", "faith based"],
    # --- Format ---
    "Online / Virtual":    ["virtual therap", "online therap", "telehealth", "online counsel"],
}


OUTPUT_FILE = "data.json"
EXCLUDED_FILE = "excluded.json"       # practices that asked to be removed
POLITE_DELAY = 0.6
WEBSITE_TIMEOUT = 12
UA = "Mozilla/5.0 (PracticumDirectory/1.0; personal research tool)"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
EMAIL_JUNK = ("@sentry", "@example", "@wixpress", ".png", ".jpg", ".gif", "@2x")



# ----------------------------------------------------------------------

def fetch_website_text(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=WEBSITE_TIMEOUT) as resp:
            raw = resp.read(600_000)
        html = raw.decode("utf-8", "ignore")
        text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return html, text
    except Exception:
        return "", ""


def find_email(html):
    for m in EMAIL_RE.findall(html):
        low = m.lower()
        if any(j in low for j in EMAIL_JUNK):
            continue
        return m
    return ""


def find_modalities(text):
    low = text.lower()
    found = []
    for name, patterns in MODALITIES.items():
        for p in patterns:
            hit = re.search(p, low) if "\\" in p else (p in low)
            if hit:
                found.append(name)
                break
    return found



# ---------- Overture Maps places --------------------------------------
def latest_release(con):
    pinned = os.environ.get("OVERTURE_RELEASE", "").strip()
    if pinned:
        return pinned
    rows = con.execute(
        f"SELECT DISTINCT regexp_extract(file, 'release/([^/]+)/', 1) "
        f"FROM glob('{OVERTURE_S3}/*/theme=places/type=place/*.parquet')"
    ).fetchall()
    releases = sorted(r[0] for r in rows if r[0])
    if not releases:
        print("  ! Couldn't find any Overture Maps release.")
        sys.exit(1)
    return releases[-1]


def overture_places():
    """Every place in the chosen categories in Alberta or Ontario, as dicts."""
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL parquet; LOAD parquet;")
    con.execute("SET s3_region='us-west-2';")
    release = latest_release(con)
    print(f"Reading Overture Maps release {release} ...")
    path = f"{OVERTURE_S3}/{release}/theme=places/type=place/*"
    cats = ", ".join(f"'{c}'" for c in CATEGORIES)
    rows = con.execute(f"""
        SELECT id, names.primary, taxonomy.primary, confidence, phones, websites,
               addresses[1].freeform, addresses[1].locality,
               addresses[1].region, addresses[1].postcode
        FROM read_parquet('{path}')
        WHERE bbox.xmin BETWEEN {BBOX['xmin']} AND {BBOX['xmax']}
          AND bbox.ymin BETWEEN {BBOX['ymin']} AND {BBOX['ymax']}
          AND len(addresses) > 0 AND addresses[1].country = 'CA'
          AND taxonomy.primary IN ({cats})
    """).fetchall()
    out = []
    for (pid, name, cat, conf, phones, websites,
         street, locality, region, postcode) in rows:
        prov = PROVINCE_CODES.get((region or "").strip().upper())
        if not prov and not (region or "").strip():
            prov = POSTCODE_PROVINCE.get((postcode or "").strip()[:1].upper())
        if prov not in ("AB", "ON"):
            continue
        out.append({
            "id": pid, "name": (name or "").strip(), "category": cat,
            "confidence": conf or 0.0,
            "phone": next((p.strip() for p in phones or [] if p and p.strip()), ""),
            "website": next((w.strip() for w in websites or [] if w and w.strip()), ""),
            "street": (street or "").strip(), "locality": (locality or "").strip(),
            "province": prov, "postcode": (postcode or "").strip(),
        })
    return release, out


def phone_digits(phone):
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def format_phone(phone):
    """'+14165551234' -> '(416) 555-1234', the format the site already shows."""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    if len(d) == 10:
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    return (phone or "").strip()


# Overture sometimes names the municipality where the site's area filter
# expects the postal community ("Wood Buffalo" for Fort McMurray). Keyed on the
# first three characters of the postal code, so outlying hamlets keep theirs.
LOCALITY_BY_FSA = {
    "Strathcona County": ("Sherwood Park", {"T8A", "T8B", "T8C", "T8G", "T8H"}),
    "Wood Buffalo":      ("Fort McMurray", {"T9H", "T9J", "T9K"}),
}


def normalize_locality(locality, postcode):
    """Match the spelling the site's area filter expects."""
    loc = re.sub(r"^(St|Ste)\s+", r"\1. ", locality)      # "St Albert" -> "St. Albert"
    if loc in LOCALITY_BY_FSA:
        name, fsas = LOCALITY_BY_FSA[loc]
        if postcode[:3] in fsas:
            loc = name
    return loc


def format_address(p):
    """'998 Ridge Valley Dr, Oshawa, ON L1K 2G3, Canada' — the shape the
    site's province/area filter parses."""
    pc = re.sub(r"\s+", "", p["postcode"]).upper()
    locality = normalize_locality(p["locality"], pc)
    if re.fullmatch(r"[A-Z]\d[A-Z]\d[A-Z]\d", pc):
        pc = f"{pc[:3]} {pc[3:]}"
    prov = f"{p['province']} {pc}".strip()
    parts = [x for x in (p["street"], locality, prov, "Canada") if x]
    return ", ".join(parts)


def website_host(url):
    m = re.match(r"^(?:[a-z]+://)?([^/?#:]+)", (url or "").strip().lower())
    host = m.group(1) if m else ""
    return host[4:] if host.startswith("www.") else host


def merge_duplicates(places):
    """Overture sometimes holds the same practice twice (same name, same
    phone). Keep one record per practice, but remember every id so the
    removal list matches whichever id a practice was delisted under."""
    groups = {}
    for p in places:
        key = (re.sub(r"[^a-z0-9]", "", p["name"].lower()),
               phone_digits(p["phone"]) or p["id"])
        groups.setdefault(key, []).append(p)
    merged = []
    for group in groups.values():
        group.sort(key=lambda p: (-p["confidence"], p["id"]))
        best = dict(group[0])
        best["all_ids"] = {p["id"] for p in group}
        merged.append(best)
    return merged


def previous_count():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return 0


# ---------- Removal list (excluded.json) ------------------------------
# Overture ids are stable release to release, but not guaranteed: a practice
# that renames or moves can come back under a new id. So a removal can also be
# recorded by phone number and website, which survive an id change.
def load_excluded():
    """Practices that have asked to be taken off the directory. Honoured on
    every run, so a removal is never undone by a later refresh."""
    ids, names, phones, hosts = set(), set(), set(), set()
    if not os.path.exists(EXCLUDED_FILE):
        return ids, names, phones, hosts
    try:
        with open(EXCLUDED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ids = {str(v).strip() for v in data.get("placeIds", []) if str(v).strip()}
        names = {str(v).strip().lower() for v in data.get("names", []) if str(v).strip()}
        phones = {phone_digits(str(v)) for v in data.get("phones", [])} - {""}
        hosts = {website_host(str(v)) for v in data.get("websites", [])} - {""}
    except Exception as e:
        print(f"  ! Couldn't read {EXCLUDED_FILE} ({e}).")
        print("    Stopping rather than risk re-publishing a practice that asked to be removed.")
        sys.exit(1)
    return ids, names, phones, hosts


def apply_excluded(records, ids, names, phones=(), hosts=()):
    def removed(r):
        return (bool(({r.get("placeId", "")} | set(r.get("all_ids", ()))) & ids)
                or r.get("name", "").strip().lower() in names
                or phone_digits(r.get("phone", "")) in phones
                or website_host(r.get("website", "")) in hosts)
    kept = [r for r in records if not removed(r)]
    return kept, len(records) - len(kept)


# ----------------------------------------------------------------------
def main():
    excl = load_excluded()

    release, places = overture_places()
    by_cat = {}
    for p in places:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    for cat in CATEGORIES:
        print(f"  {cat}: {by_cat.get(cat, 0)}")
    places = merge_duplicates(places)
    places.sort(key=lambda p: p["id"])

    # Drop removed practices before visiting any websites.
    records = [{
        "name": p["name"],
        "address": format_address(p),
        "phone": format_phone(p["phone"]),
        "website": p["website"],
        "placeId": p["id"],
        "all_ids": p["all_ids"],
    } for p in places if p["name"]]
    records, dropped = apply_excluded(records, *excl)
    if dropped:
        print(f"\n{dropped} practice(s) withheld per {EXCLUDED_FILE}.")

    before = previous_count()
    if (before and len(records) < before * MIN_KEEP_RATIO
            and os.environ.get("ALLOW_SHRINK") != "1"):
        print(f"\n  ! Found {len(records)} practices; {OUTPUT_FILE} has {before}.")
        print("    Stopping without writing. If the smaller list is intended,")
        print("    run again with ALLOW_SHRINK=1.")
        sys.exit(1)

    print(f"\n{len(records)} unique practices found. Reading their websites ...\n")

    seen = {}   # the same site listed for several branches is read once
    for i, r in enumerate(records, 1):
        website = r["website"]
        email, modalities = "", []
        if website:
            if website not in seen:
                html, text = fetch_website_text(website)
                seen[website] = (find_email(html), find_modalities(text)) if html else ("", [])
                time.sleep(POLITE_DELAY)
            email, modalities = seen[website]
        r["email"] = email
        r["modalities"] = list(modalities)
        print(f"  [{i}/{len(records)}] {r['name']}"
              f"{'  ·  email found' if email else ''}"
              f"{'  ·  ' + ', '.join(modalities) if modalities else ''}")

    keys = ("name", "address", "phone", "email", "website", "modalities", "placeId")
    records = [{k: r[k] for k in keys} for r in records]
    records.sort(key=lambda r: r["name"].lower())
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote {len(records)} practices to {OUTPUT_FILE}"
          f" (Overture Maps release {release}).")


if __name__ == "__main__":
    main()
