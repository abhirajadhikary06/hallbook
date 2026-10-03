# Hall Booking Platform

A scalable hall / venue booking system built with **Tornado** (async Python), HTML/CSS/JS, Bootstrap (free CDN), and **Neon PostgreSQL** (or SQLite fallback).

## Features

- **Admin side**
  - Create organizations (one admin can own multiple orgs)
  - Add multiple halls under each organization — all visible on a single admin dashboard
  - View pending booking requests across all halls
  - Approve a request (auto-rejects overlapping pending requests for the same slot)
  - Reject a request and optionally suggest an alternative date/time
  - Users receive in-app notifications for approve / reject / suggestion

- **User side**
  - Register / login
  - Search organizations by location or keyword
  - View hall details + approved slots (calendar-style)
  - Request a booking slot (date + start/end time)
  - See booking history and notifications
  - Accept a suggested alternative slot (creates a new pending request)

- **Performance / free-tier friendly**
  - In-memory cache (thread-safe) for search & list pages
  - Bootstrap + Icons loaded from jsDelivr CDN (free)
  - **Neon PostgreSQL** for persistent cloud storage (or SQLite fallback)
  - Single-process Tornado server — deploys on one free Render web service
  - Handles 20–30 concurrent users comfortably

## Database: Neon PostgreSQL (persistent)

1. Create a free project at [neon.tech](https://neon.tech).
2. Copy the connection string (looks like  
   `postgresql://user:password@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`).
3. Set the environment variable (no code changes):

```bash
export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

On Render: add `DATABASE_URL` in the Environment section of your Web Service.

If `DATABASE_URL` is **not** set, the app automatically falls back to a local SQLite file (good for quick demos).

## Demo accounts (seeded on first run)

| Role  | Username   | Password  |
|-------|------------|-----------|
| Admin | `admin`    | `admin123`|
| User  | `demo_user`| `user123` |

Demo data includes two organizations in **New York** with a few halls.

## Local run

```bash
cd hall_booking
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Optional — use Neon instead of SQLite:
# export DATABASE_URL="postgresql://..."

python app.py
```

Open http://localhost:8888

## Deploy on Render (free tier)

1. Push this folder to a GitHub repo.
2. On [Render](https://render.com) → New → Web Service.
3. Connect the repo.
4. Settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
   - **Instance Type**: Free
5. Environment variables:
   - `DATABASE_URL` = your Neon connection string (required for persistence)
   - `COOKIE_SECRET` = any long random string (recommended)
6. Deploy. The free tier sleeps after inactivity; first request may take ~30 s to wake.

## Project layout

```
hall_booking/
├── app.py              # Tornado application & routes
├── database.py         # Neon Postgres + SQLite dual backend
├── cache.py            # Simple in-memory TTL cache
├── requirements.txt
├── templates/          # Jinja2 (Tornado) HTML
├── static/css|js       # Custom styles & client helpers
└── data/               # SQLite fallback (auto-created)
```

## API (JSON)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST   | /api/orgs | Admin | Create organization |
| POST   | /api/halls | Admin | Add hall |
| POST   | /api/bookings | User | Create booking request |
| POST   | /api/bookings/:id/approve | Admin | Approve (+ auto-reject overlaps) |
| POST   | /api/bookings/:id/reject | Admin | Reject + optional suggestion |
| POST   | /api/bookings/:id/accept-suggestion | User | Accept suggested slot |
| GET/POST | /api/notifications | User | List / mark-all-read |
| GET   | /api/halls/:id/bookings?date= | Public | Day view of bookings |

## Possible enhancements

- Real-time WebSocket notifications
- Email / SMS alerts
- Recurring slots & availability templates
- Payment integration
- Postgres + Redis for higher scale
- Full calendar UI (FullCalendar CDN)
- Role: multi-admin per organization
