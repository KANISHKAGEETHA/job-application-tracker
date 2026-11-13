# OfferTrail — Job Application Tracker

I built **OfferTrail** to make a job search feel a little more organized and a lot less like a stack of open tabs. It keeps every role, stage, contact, and follow-up in one clear place so I can focus on the next step.

## What I can do with it

- Add, edit, and remove job applications
- Track each application through **Applied → Screening → Interview → Assessment → Offer**, with **Rejected** and **Withdrawn** outcomes
- Save the posting link, location, work setup, salary range, contact, notes, and follow-up date
- Search by company, role, or location, then filter by stage
- See a pipeline snapshot and counts for active applications, interview steps, offers, and responses
- Export my tracker as a CSV file
- Use the JSON REST API to list, create, update, or delete records
- Keep data in a local SQLite database, with no account or external service required

## Built with

Python · Flask · SQLite · HTML · CSS · JSON REST API · Git

## Run it locally

I use Python 3.10 or newer. From PowerShell, run:

```powershell
git clone https://github.com/KANISHKAGEETHA/job-application-tracker.git
cd job-application-tracker
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:5000** in a browser. The app creates `instance/applications.sqlite3` the first time it starts. Stop it with **Ctrl+C** in PowerShell.

If `py -3` is not available, install Python 3.10+ and replace `py -3` with `python` in the virtual-environment command.

## REST API

All API responses use JSON. The server listens on `127.0.0.1` by default.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Check that the app and SQLite database are responding |
| `GET` | `/api/applications` | List applications; optional `q` and `status` query parameters |
| `POST` | `/api/applications` | Create an application |
| `GET` | `/api/applications/<id>` | Read one application |
| `PATCH` | `/api/applications/<id>` | Update fields on an application |
| `DELETE` | `/api/applications/<id>` | Delete an application |

Example PowerShell request to add an application:

```powershell
$application = @{
  company = "Northstar Studio"
  role = "Product Designer"
  status = "Applied"
  applied_date = (Get-Date -Format "yyyy-MM-dd")
  location = "Remote"
  work_mode = "Remote"
  follow_up_date = "2026-11-20"
  notes = "Sent portfolio with application."
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:5000/api/applications" `
  -ContentType "application/json" `
  -Body $application
```

List records with `Invoke-RestMethod http://127.0.0.1:5000/api/applications`. Filter with `?status=Interview` or `?q=Northstar`.

## Data and privacy

Application records stay in the local SQLite database. They are not sent to an external API. The app has no login and is intended for local use; it binds to `127.0.0.1` and runs Flask's development server. I would add authentication and deploy behind a production WSGI server before hosting it for other people.

The pipeline's response percentage counts records that moved beyond **Applied**, including interview stages, offers, and rejections. It is a simple tracker metric, not a measure of hiring success.
