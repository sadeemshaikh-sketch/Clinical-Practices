#!/usr/bin/env python3
"""
practicum_pull.py
------------------
Builds `data.json` for the practicum directory page, AND keeps a private
spreadsheet of your notes ("practice_notes.csv") that survives every refresh.

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
  4. Reads your notes file (practice_notes.csv) and marks the practices YOU
     have flagged as "taking students" — your answers are never wiped.
  5. Writes everything to data.json (for the website) and updates
     practice_notes.csv (for you), adding blank rows for any new practices.

YOUR NOTES FILE (practice_notes.csv):
  Open it in Numbers or Excel. To mark a practice as taking students, type
  "yes" in its taking_students column and save. The "notes" column is your
  own private scratchpad (e.g. "emailed Aug 5"). This file stays on your
  computer and is NEVER uploaded to the website.
"""

import os
import re
import sys
import csv
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
    "CBT":          [r"\bcbt\b", "cognitive behav"],
    "DBT":          [r"\bdbt\b", "dialectical behav"],
    "EMDR":         [r"\bemdr\b", "eye movement desensit"],
    "ACT":          ["acceptance and commitment"],
    "EFT":          ["emotionally focused"],
    "Mindfulness":  ["mindfulness"],
    "Trauma":       ["trauma"],
    "Anxiety":      ["anxiety"],
    "Depression":   ["depression"],
    "Couples":      ["couples"],
    "Family":       ["family therap", "family counsel"],
    "Play Therapy": ["play therap"],
    "Child":        ["child therap", "children's mental", "kids therap"],
    "Grief":        ["grief", "bereavement"],
    "Addiction":    ["addiction", "substance use"],
    "ADHD":         [r"\badhd\b"],
    "Assessment":   ["psychoeducational assess", "psychological assess", "psych assessment"],
}

OUTPUT_FILE = "data.json"
NOTES_FILE = "practice_notes.csv"     # your private spreadsheet — never uploaded
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


# ---------- Your private notes (practice_notes.csv) -------------------
def is_yes(val):
    return str(val).strip().lower() in ("yes", "y", "true", "x", "1")


def load_notes():
    """Read practice_notes.csv into a dict keyed by placeId."""
    notes = {}
    if not os.path.exists(NOTES_FILE):
        return notes
    try:
        with open(NOTES_FILE, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                pid = (row.get("placeId") or "").strip()
                if pid:
                    notes[pid] = {
                        "name": (row.get("name") or "").strip(),
                        "taking_students": (row.get("taking_students") or "").strip(),
                        "notes": (row.get("notes") or "").strip(),
                    }
    except Exception as e:
        print(f"  ! Couldn't read {NOTES_FILE} ({e}); continuing without your notes.")
    return notes


def apply_notes(records, notes):
    """Flag practices you've marked 'taking students'. Returns how many."""
    count = 0
    for r in records:
        pid = r.get("placeId", "")
        if pid in notes and is_yes(notes[pid]["taking_students"]):
            r["acceptingStudents"] = True
            count += 1
    return count


def write_notes(records, notes):
    """Rewrite practice_notes.csv: one row per practice, preserving your
    answers, adding blank rows for new practices, and never losing old notes."""
    seen = set()
    rows = []
    for r in sorted(records, key=lambda x: x["name"].lower()):
        pid = r.get("placeId", "")
        seen.add(pid)
        prev = notes.get(pid, {})
        rows.append({
            "name": r["name"],
            "placeId": pid,
            "taking_students": prev.get("taking_students", ""),
            "notes": prev.get("notes", ""),
        })
    for pid, prev in notes.items():   # keep notes for practices not in this pull
        if pid not in seen:
            rows.append({
                "name": prev.get("name", ""),
                "placeId": pid,
                "taking_students": prev.get("taking_students", ""),
                "notes": prev.get("notes", ""),
            })
    with open(NOTES_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "placeId", "taking_students", "notes"])
        writer.writeheader()
        writer.writerows(rows)


# ----------------------------------------------------------------------
def main():
    api_key = get_api_key()

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
            "acceptingStudents": False,   # set from YOUR notes below
            "placeId": p.get("id", ""),
        })
        print(f"  [{i}/{len(places)}] {name or '(no name)'}"
              f"{'  ·  email found' if email else ''}"
              f"{'  ·  ' + ', '.join(modalities) if modalities else ''}")

    # --- merge in your private notes, then keep the notes sheet in sync ---
    notes = load_notes()
    marked = apply_notes(records, notes)
    write_notes(records, notes)

    records.sort(key=lambda r: r["name"].lower())
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote {len(records)} practices to {OUTPUT_FILE}.")
    print(f"{marked} marked as 'taking students' from your notes.")
    print(f"\nYour notes live in {NOTES_FILE} — open it in Numbers or Excel,")
    print("type 'yes' in the taking_students column for any practice that takes")
    print("students, save, and re-run this script to push it live.")
    print(f"KEEP {NOTES_FILE} in this folder — it's private, never upload it.")
    print(f"\nTo update the site: copy {OUTPUT_FILE} into your website folder and re-upload.")


if __name__ == "__main__":
    main()
