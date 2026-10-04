# CLAUDE.md — Clinical-Practices

Practicum directory for counselling psychology students in Alberta and Ontario, served by GitHub Pages at www.practicumcounsellingpsychology.online. `practicum_pull.py` rebuilds `data.json` weekly via `.github/workflows/update-data.yml`.

## Open issues

- [x] **Google sourcing — RESOLVED 3 Oct 2026.** Practice data switched from the Google Places API to Overture Maps open places data. Licence texts are in `licenses/`, attribution and modification notice are in the `index.html` footer, and the Privacy Policy and Terms of Service are updated to match.
- [ ] **One clean manual workflow run** of `update-data.yml` (Actions → Run workflow) before the weekly schedule is trusted.
- [ ] **Delete the Google API key in Google Cloud**, then Sadeem deletes the `GOOGLE_API_KEY` repository secret. Nothing reads it any more.
