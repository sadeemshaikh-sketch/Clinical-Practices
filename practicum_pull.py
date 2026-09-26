#!/usr/bin/env python3
"""
practicum_pull.py
------------------
Builds `data.json` for the practicum directory page.

WHAT IT NEEDS: one Google Maps API key with "Places API (New)" enabled.
No other accounts, no `pip install` (uses only Python's built-in libraries).

WHERE TO PUT THE KEY (pick one):
  1. Save it in a file called `google_key.txt` in this same folder, OR
  2. Set an environment variable named GOOGLE_API_KEY.

HOW TO RUN:
  python3 practicum_pull.py

WHAT IT DOES EACH RUN:
  1. Asks Google Places for counselling/therapy practices across Alberta and Ontario.
  2. Pulls name, address, phone, website from Google.
  3. Visits each practice's own website for an email + therapy approaches.
  4. Writes everything to data.json (for the website).

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
# Alberta and Ontario: the script searches each of these places separately.
# (Searching a whole province as one lump returns poor results, so we cover
# the main population centres. Add or remove places freely.)
PLACES = [
    # --- Alberta ---
    "Calgary, Alberta",
    "Edmonton, Alberta",
    "Red Deer, Alberta",
    "Lethbridge, Alberta",
    "Medicine Hat, Alberta",
    "St. Albert, Alberta",
    "Sherwood Park, Alberta",
    "Airdrie, Alberta",
    "Grande Prairie, Alberta",
    "Fort McMurray, Alberta",
    "Spruce Grove, Alberta",
    "Okotoks, Alberta",
    "Leduc, Alberta",
    "Camrose, Alberta",
    "Cochrane, Alberta",
    "Lloydminster, Alberta",
    # --- Ontario ---
    "Toronto, Ontario",
    "Ottawa, Ontario",
    "Mississauga, Ontario",
    "Brampton, Ontario",
    "Hamilton, Ontario",
    "London, Ontario",
    "Kitchener, Ontario",
    "Waterloo, Ontario",
    "Windsor, Ontario",
    "Kingston, Ontario",
    "Oshawa, Ontario",
    "Barrie, Ontario",
    "Guelph, Ontario",
    "Sudbury, Ontario",
    "Thunder Bay, Ontario",
    "St. Catharines, Ontario",
    "Markham, Ontario",
    "Vaughan, Ontario",
    "Burlington, Ontario",
    "Oakville, Ontario",
]

SEARCH_TERMS = [
    "counselling",
    "psychotherapist",
    "psychologist",
    "mental health therapist",
    "family therapy",
    "marriage and family therapist",
    "registered social worker therapy",
]

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

PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.nationalPhoneNumber,places.websiteUri,nextPageToken"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
EMAIL_JUNK = ("@sentry", "@example", "@wixpress", ".png", ".jpg", ".gif", "@2x")


# ----------------------------------------------------------------------
def get_api_key():
    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if key:
        return key
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "google_key.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    print(
        "\n  No Google API key found.\n"
        "  Fix: put your key in a file called 'google_key.txt' next to this\n"
        "  script, OR set an environment variable named GOOGLE_API_KEY.\n"
    )
    sys.exit(1)


def places_text_search(query, api_key):
    results = []
    page_token = None
    while True:
        body = {"textQuery": query, "pageSize": 20}
        if page_token:
            body["pageToken"] = page_token
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(PLACES_ENDPOINT, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Goog-Api-Key", api_key)
        req.add_header("X-Goog-FieldMask", FIELD_MASK)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            print(f"  ! Google API error for '{query}': {e.code} {detail[:200]}")
            break
        except Exception as e:
            print(f"  ! Network error for '{query}': {e}")
            break

        results.extend(payload.get("places", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        time.sleep(2)
    return results


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


# ---------- Removal list (excluded.json) ------------------------------
def load_excluded():
    """Practices that have asked to be taken off the directory. Honoured on
    every run, so a removal is never undone by a later refresh."""
    ids, names = set(), set()
    if not os.path.exists(EXCLUDED_FILE):
        return ids, names
    try:
        with open(EXCLUDED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ids = {str(v).strip() for v in data.get("placeIds", []) if str(v).strip()}
        names = {str(v).strip().lower() for v in data.get("names", []) if str(v).strip()}
    except Exception as e:
        print(f"  ! Couldn't read {EXCLUDED_FILE} ({e}).")
        print("    Stopping rather than risk re-publishing a practice that asked to be removed.")
        sys.exit(1)
    return ids, names


def apply_excluded(records, ids, names):
    kept = [r for r in records
            if r.get("placeId", "") not in ids
            and r.get("name", "").strip().lower() not in names]
    return kept, len(records) - len(kept)


# ----------------------------------------------------------------------
def main():
    api_key = get_api_key()
    excl_ids, excl_names = load_excluded()

    print(f"Searching Google across {len(PLACES)} locations in Alberta and Ontario ...")
    print("(This takes a while - it searches each place separately.)\n")
    by_id = {}
    for place in PLACES:
        found_here = 0
        for term in SEARCH_TERMS:
            hits = places_text_search(f"{term} in {place}", api_key)
            for p in hits:
                pid = p.get("id")
                if pid and pid not in by_id:
                    by_id[pid] = p
                    found_here += 1
            time.sleep(0.4)
        print(f"  {place}: {found_here} new practices")

    places = list(by_id.values())
    print(f"\n{len(places)} unique practices found. Reading their websites ...\n")

    records = []
    for i, p in enumerate(places, 1):
        name = (p.get("displayName") or {}).get("text", "").strip()
        website = p.get("websiteUri", "").strip()
        email, modalities = "", []
        if website:
            html, text = fetch_website_text(website)
            if html:
                email = find_email(html)
                modalities = find_modalities(text)
            time.sleep(POLITE_DELAY)
        records.append({
            "name": name,
            "address": p.get("formattedAddress", "").strip(),
            "phone": p.get("nationalPhoneNumber", "").strip(),
            "email": email,
            "website": website,
            "modalities": modalities,
            "placeId": p.get("id", ""),
        })
        print(f"  [{i}/{len(places)}] {name or '(no name)'}"
              f"{'  ·  email found' if email else ''}"
              f"{'  ·  ' + ', '.join(modalities) if modalities else ''}")

    records, dropped = apply_excluded(records, excl_ids, excl_names)
    if dropped:
        print(f"\n{dropped} practice(s) withheld per {EXCLUDED_FILE}.")

    records.sort(key=lambda r: r["name"].lower())
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote {len(records)} practices to {OUTPUT_FILE}.")
    print(f"\nTo update the site: copy {OUTPUT_FILE} into your website folder and re-upload.")


if __name__ == "__main__":
    main()
