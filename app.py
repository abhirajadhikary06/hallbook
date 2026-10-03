#!/usr/bin/env python3
"""
Hall Booking Platform - Tornado backend
Supports organizations with multiple halls, calendar-style booking requests,
admin approval workflow with suggestions, and in-app notifications.
Optimized for 20-30 concurrent users on a single free-tier server (e.g. Render).
"""

import os
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

import tornado.ioloop
import tornado.web
import tornado.escape
from tornado.options import define, options

from database import (
    init_db, create_user, get_user_by_username, get_user_by_id,
    create_organization, get_organizations_by_admin, get_organization,
    search_organizations, create_hall, get_halls_by_org, get_hall,
    get_halls_for_admin, create_booking_request, get_booking,
    get_pending_bookings_for_admin, get_bookings_for_hall_date,
    get_user_bookings, approve_booking, reject_booking_with_suggestion,
    accept_suggested_slot, get_notifications, mark_notification_read,
    mark_all_notifications_read, get_approved_bookings_for_hall,
    verify_password, hash_password, get_available_halls_in_org,
    get_bookings_for_hall_month, create_blocked_bookings, delete_booking,
    delete_blocked_event, get_blocked_event_hall, delete_organization, delete_hall
)
from cache import cache, invalidate_org_cache

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("hall_booking")

define("port", default=int(os.environ.get("PORT", 8888)), help="Port to listen on")
define("debug", default=os.environ.get("DEBUG", "0") == "1", help="Debug mode")

COOKIE_SECRET = os.environ.get("COOKIE_SECRET", "hall-booking-secret-change-me-in-prod-32chars!")

# ---------------------------------------------------------------------------
# Base handlers
# ---------------------------------------------------------------------------

class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        user_id = self.get_secure_cookie("user_id")
        if not user_id:
            return None
        try:
            uid = int(user_id.decode() if isinstance(user_id, bytes) else user_id)
            return get_user_by_id(uid)
        except Exception:
            return None

    def set_current_user(self, user):
        if user:
            self.set_secure_cookie("user_id", str(user["id"]), expires_days=7)
        else:
            self.clear_cookie("user_id")

    def write_json(self, data, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps(data, default=str))

    def write_error(self, status_code, **kwargs):
        if self.request.path.startswith("/api/"):
            self.write_json({"error": self._reason or "Error"}, status=status_code)
        else:
            super().write_error(status_code, **kwargs)

class AuthRequiredMixin:
    def prepare(self):
        if not self.current_user:
            if self.request.path.startswith("/api/"):
                self.write_json({"error": "Authentication required"}, 401)
                self.finish()
            else:
                self.redirect("/login?next=" + tornado.escape.url_escape(self.request.uri))
                self.finish()

class AdminRequiredMixin(AuthRequiredMixin):
    def prepare(self):
        super().prepare()
        if self._finished:
            return
        if self.current_user.get("role") != "admin":
            if self.request.path.startswith("/api/"):
                self.write_json({"error": "Admin access required"}, 403)
                self.finish()
            else:
                self.redirect("/")
                self.finish()

# ---------------------------------------------------------------------------
# Page handlers
# ---------------------------------------------------------------------------

class IndexHandler(BaseHandler):
    def get(self):
        user = self.current_user
        if user and user["role"] == "admin":
            self.redirect("/admin")
            return
        self.render("index.html", user=user)

class LoginHandler(BaseHandler):
    def get(self):
        if self.current_user:
            self.redirect("/")
            return
        next_url = self.get_argument("next", "/")
        self.render("login.html", user=self.current_user, next_url=next_url, error=None)

    def post(self):
        username = self.get_argument("username", "").strip()
        password = self.get_argument("password", "")
        next_url = self.get_argument("next", "/")
        user = get_user_by_username(username)
        if user and verify_password(password, user["password_hash"]):
            self.set_current_user(user)
            if user["role"] == "admin":
                self.redirect("/admin")
            else:
                self.redirect(next_url or "/")
        else:
            self.render("login.html", user=self.current_user, next_url=next_url, error="Invalid username or password")

class RegisterHandler(BaseHandler):
    def get(self):
        if self.current_user:
            self.redirect("/")
            return
        self.render("register.html", user=self.current_user, error=None)

    def post(self):
        username = self.get_argument("username", "").strip()
        email = self.get_argument("email", "").strip()
        password = self.get_argument("password", "")
        role = self.get_argument("role", "user")
        if role not in ("user", "admin"):
            role = "user"
        if not username or not email or not password:
            self.render("register.html", user=self.current_user, error="All fields are required")
            return
        if len(password) < 6:
            self.render("register.html", user=self.current_user, error="Password must be at least 6 characters")
            return
        existing = get_user_by_username(username)
        if existing:
            self.render("register.html", user=self.current_user, error="Username already taken")
            return
        try:
            uid = create_user(username, email, password, role)
            user = get_user_by_id(uid)
            self.set_current_user(user)
            if role == "admin":
                self.redirect("/admin")
            else:
                self.redirect("/")
        except Exception as e:
            logger.exception("Register failed")
            self.render("register.html", user=self.current_user, error="Registration failed. Email may already be in use.")

class LogoutHandler(BaseHandler):
    def get(self):
        self.set_current_user(None)
        self.redirect("/")

class AdminDashboardHandler(BaseHandler, AdminRequiredMixin):
    def get(self):
        admin = self.current_user
        orgs = get_organizations_by_admin(admin["id"])
        halls = get_halls_for_admin(admin["id"])
        pending = get_pending_bookings_for_admin(admin["id"])
        notifs = get_notifications(admin["id"], unread_only=True)
        self.render("admin_dashboard.html",
                    user=admin, orgs=orgs, halls=halls,
                    pending=pending, notifications=notifs)

class AdminCalendarHandler(BaseHandler, AdminRequiredMixin):
    def get(self):
        admin = self.current_user
        halls = get_halls_for_admin(admin["id"])
        # Get hall_id from query param, default to first hall if available
        hall_id = self.get_argument("hall_id", None)
        if not hall_id and halls:
            hall_id = halls[0]["id"]
        selected_hall = None
        if hall_id:
            hall_id = int(hall_id)
            selected_hall = get_hall(hall_id)
        self.render("admin_calendar.html",
                    user=admin, halls=halls, selected_hall=selected_hall)

class UserDashboardHandler(BaseHandler, AuthRequiredMixin):
    def get(self):
        import json
        user = self.current_user
        bookings = get_user_bookings(user["id"])
        notifs = get_notifications(user["id"])
        
        # Serialize notifications to JSON for the notification system
        notifs_json = json.dumps(notifs)
        
        self.render("user_dashboard.html",
                    user=user, bookings=bookings, notifications=notifs, 
                    notifications_json=notifs_json)

class SearchHandler(BaseHandler):
    def get(self):
        import json
        location = self.get_argument("location", "").strip()
        q = self.get_argument("q", "").strip()
        cache_key = f"search:{location}:{q}"
        orgs = cache.get(cache_key)
        if orgs is None:
            orgs = search_organizations(location=location or None, query=q or None)
            # Attach halls
            for org in orgs:
                org["halls"] = get_halls_by_org(org["id"])
            cache.set(cache_key, orgs, ttl=60)
        
        # Serialize orgs to JSON for the map
        orgs_json = json.dumps(orgs)
        
        self.render("search.html", user=self.current_user, orgs=orgs,
                    orgs_json=orgs_json, location=location, q=q)

class HallDetailHandler(BaseHandler):
    def get(self, hall_id):
        hall = get_hall(int(hall_id))
        if not hall:
            self.set_status(404)
            self.write("Hall not found")
            return
        # Approved bookings for calendar view (next 60 days)
        today = datetime.utcnow().date().isoformat()
        approved = get_approved_bookings_for_hall(hall["id"], from_date=today)
        self.render("hall_detail.html", user=self.current_user, hall=hall, approved=approved)

# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

class ApiCreateOrgHandler(BaseHandler, AdminRequiredMixin):
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            data = {k: self.get_argument(k, "") for k in ("name", "location", "description")}
        name = data.get("name", "").strip()
        location = data.get("location", "").strip()
        description = data.get("description", "").strip()
        if not name or not location:
            self.write_json({"error": "Name and location required"}, 400)
            return
        org_id = create_organization(name, location, description, self.current_user["id"])
        invalidate_org_cache()
        self.write_json({"ok": True, "org_id": org_id})

class ApiCreateHallHandler(BaseHandler, AdminRequiredMixin):
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            data = {k: self.get_argument(k, "") for k in
                    ("org_id", "name", "capacity", "amenities", "description")}
        try:
            org_id = int(data.get("org_id"))
            name = data.get("name", "").strip()
            capacity = int(data.get("capacity") or 50)
            amenities = data.get("amenities", "").strip()
            description = data.get("description", "").strip()
        except (TypeError, ValueError):
            self.write_json({"error": "Invalid input"}, 400)
            return
        org = get_organization(org_id)
        if not org or org["admin_id"] != self.current_user["id"]:
            self.write_json({"error": "Organization not found or not yours"}, 403)
            return
        if not name:
            self.write_json({"error": "Hall name required"}, 400)
            return
        hall_id = create_hall(org_id, name, capacity, amenities, description)
        invalidate_org_cache()
        self.write_json({"ok": True, "hall_id": hall_id})

class ApiDeleteOrgHandler(BaseHandler, AdminRequiredMixin):
    def delete(self, org_id):
        success, message = delete_organization(int(org_id), self.current_user["id"])
        if success:
            invalidate_org_cache()
            self.write_json({"ok": True, "message": message})
        else:
            self.write_json({"error": message}, 403)

class ApiDeleteHallHandler(BaseHandler, AdminRequiredMixin):
    def delete(self, hall_id):
        success, message = delete_hall(int(hall_id), self.current_user["id"])
        if success:
            invalidate_org_cache()
            self.write_json({"ok": True, "message": message})
        else:
            self.write_json({"error": message}, 403)

class ApiCreateBookingHandler(BaseHandler, AuthRequiredMixin):
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            data = {k: self.get_argument(k, "") for k in
                    ("hall_id", "booking_date", "start_time", "end_time", "message")}
        try:
            hall_id = int(data.get("hall_id"))
            booking_date = data.get("booking_date", "").strip()
            start_time = data.get("start_time", "").strip()
            end_time = data.get("end_time", "").strip()
            message = data.get("message", "").strip()
        except (TypeError, ValueError):
            self.write_json({"error": "Invalid input"}, 400)
            return
        if not all([booking_date, start_time, end_time]):
            self.write_json({"error": "Date and times required"}, 400)
            return
        # Basic validation: end > start
        if end_time <= start_time:
            self.write_json({"error": "End time must be after start time"}, 400)
            return
        hall = get_hall(hall_id)
        if not hall:
            self.write_json({"error": "Hall not found"}, 404)
            return
        # Check if already approved slot overlaps
        approved = get_approved_bookings_for_hall(hall_id, from_date=booking_date)
        for a in approved:
            if a["booking_date"] == booking_date and a["start_time"] < end_time and a["end_time"] > start_time:
                # Conflict detected - suggest alternative halls in same organization
                alternatives = get_available_halls_in_org(
                    hall["org_id"], 
                    booking_date, 
                    start_time, 
                    end_time, 
                    exclude_hall_id=hall_id
                )
                self.write_json({
                    "error": "This time slot is already booked (approved). Choose another time or see alternatives below.",
                    "conflict": True,
                    "alternative_halls": alternatives
                }, 409)
                return
        bid = create_booking_request(hall_id, self.current_user["id"], booking_date, start_time, end_time, message)
        self.write_json({"ok": True, "booking_id": bid})

class ApiApproveBookingHandler(BaseHandler, AdminRequiredMixin):
    def post(self, booking_id):
        try:
            data = tornado.escape.json_decode(self.request.body) if self.request.body else {}
        except Exception:
            data = {}
        note = data.get("admin_note", "")
        booking = get_booking(int(booking_id))
        if not booking:
            self.write_json({"error": "Booking not found"}, 404)
            return
        # Verify admin owns the org
        halls = get_halls_for_admin(self.current_user["id"])
        if not any(h["id"] == booking["hall_id"] for h in halls):
            self.write_json({"error": "Not authorized for this hall"}, 403)
            return
        ok = approve_booking(int(booking_id), note)
        if ok:
            self.write_json({"ok": True})
        else:
            self.write_json({"error": "Could not approve (maybe already processed)"}, 400)

class ApiRejectBookingHandler(BaseHandler, AdminRequiredMixin):
    def post(self, booking_id):
        try:
            data = tornado.escape.json_decode(self.request.body) if self.request.body else {}
        except Exception:
            data = {}
        note = data.get("admin_note", "Rejected by admin")
        suggested_date = data.get("suggested_date") or None
        suggested_start = data.get("suggested_start") or None
        suggested_end = data.get("suggested_end") or None
        booking = get_booking(int(booking_id))
        if not booking:
            self.write_json({"error": "Booking not found"}, 404)
            return
        halls = get_halls_for_admin(self.current_user["id"])
        if not any(h["id"] == booking["hall_id"] for h in halls):
            self.write_json({"error": "Not authorized"}, 403)
            return
        ok = reject_booking_with_suggestion(int(booking_id), note, suggested_date, suggested_start, suggested_end)
        if ok:
            self.write_json({"ok": True})
        else:
            self.write_json({"error": "Could not reject"}, 400)

class ApiAcceptSuggestionHandler(BaseHandler, AuthRequiredMixin):
    def post(self, booking_id):
        new_id = accept_suggested_slot(int(booking_id), self.current_user["id"])
        if new_id:
            self.write_json({"ok": True, "new_booking_id": new_id})
        else:
            self.write_json({"error": "Could not accept suggestion"}, 400)

class ApiDeleteBookingHandler(BaseHandler, AuthRequiredMixin):
    """Delete a booking (admin or user before start time)."""
    def delete(self, booking_id):
        is_admin = False
        
        # If admin, verify they own the hall
        if self.current_user.get("role") == "admin":
            booking = get_booking(int(booking_id))
            if not booking:
                self.write_json({"error": "Booking not found"}, 404)
                return
            halls = get_halls_for_admin(self.current_user["id"])
            if not any(h["id"] == booking["hall_id"] for h in halls):
                self.write_json({"error": "Not authorized to delete this booking"}, 403)
                return
            is_admin = True
        
        success, message = delete_booking(
            int(booking_id), 
            self.current_user["id"],
            is_admin
        )
        
        if success:
            self.write_json({"ok": True, "message": message})
        else:
            self.write_json({"error": message}, 400)

class ApiNotificationsHandler(BaseHandler, AuthRequiredMixin):
    def get(self):
        notifs = get_notifications(self.current_user["id"])
        self.write_json({"notifications": notifs})

    def post(self):
        # mark all read
        mark_all_notifications_read(self.current_user["id"])
        self.write_json({"ok": True})

class ApiMarkNotifHandler(BaseHandler, AuthRequiredMixin):
    def post(self, notif_id):
        mark_notification_read(int(notif_id), self.current_user["id"])
        self.write_json({"ok": True})

class ApiHallBookingsHandler(BaseHandler):
    """Return bookings for a hall on a date (for calendar UI)."""
    def get(self, hall_id):
        date = self.get_argument("date", datetime.utcnow().date().isoformat())
        bookings = get_bookings_for_hall_date(int(hall_id), date)
        # Expose booking details with proper permissions
        public = []
        for b in bookings:
            booking_data = {
                "id": b["id"],
                "start_time": b["start_time"],
                "end_time": b["end_time"],
                "status": b["status"],
            }
            # Show requester name and message to authenticated users and admins
            if self.current_user:
                booking_data["requester_name"] = b.get("requester_name", "Unknown")
                booking_data["message"] = b.get("message", "")
            public.append(booking_data)
        self.write_json({"bookings": public})

class ApiGetAlternativeHallsHandler(BaseHandler, AdminRequiredMixin):
    """Get alternative halls for a booking that's being rejected."""
    def get(self, booking_id):
        booking = get_booking(int(booking_id))
        if not booking:
            self.write_json({"error": "Booking not found"}, 404)
            return
        
        # Verify admin owns the org
        halls = get_halls_for_admin(self.current_user["id"])
        if not any(h["id"] == booking["hall_id"] for h in halls):
            self.write_json({"error": "Not authorized"}, 403)
            return
        
        hall = get_hall(booking["hall_id"])
        if not hall:
            self.write_json({"error": "Hall not found"}, 404)
            return
        
        alternatives = get_available_halls_in_org(
            hall["org_id"],
            booking["booking_date"],
            booking["start_time"],
            booking["end_time"],
            exclude_hall_id=booking["hall_id"]
        )
        
        self.write_json({
            "booking": {
                "id": booking["id"],
                "hall_name": booking["hall_name"],
                "date": booking["booking_date"],
                "start_time": booking["start_time"],
                "end_time": booking["end_time"]
            },
            "alternatives": alternatives
        })

class ApiHallMonthBookingsHandler(BaseHandler):
    """Return all bookings for a hall for a specific month (for calendar view)."""
    def get(self, hall_id):
        try:
            year = int(self.get_argument("year", datetime.utcnow().year))
            month = int(self.get_argument("month", datetime.utcnow().month))
        except ValueError:
            self.write_json({"error": "Invalid year or month"}, 400)
            return
        
        if month < 1 or month > 12:
            self.write_json({"error": "Month must be between 1 and 12"}, 400)
            return
        
        bookings = get_bookings_for_hall_month(int(hall_id), year, month)
        can_manage = False
        if self.current_user and self.current_user.get("role") == "admin":
            can_manage = any(h["id"] == int(hall_id) for h in get_halls_for_admin(self.current_user["id"]))
        
        # Include requester name and message for authenticated users
        result = []
        for b in bookings:
            booking_data = {
                "id": b["id"],
                "booking_date": b["booking_date"],
                "start_time": b["start_time"],
                "end_time": b["end_time"],
                "status": b["status"],
                "booking_type": b.get("booking_type", "request"),
            }
            if self.current_user:
                booking_data["requester_name"] = b.get("requester_name", "Unknown")
                booking_data["message"] = b.get("message", "")
            if can_manage:
                booking_data["event_group_id"] = b.get("event_group_id")
                booking_data["can_delete"] = True
            result.append(booking_data)
        
        self.write_json({"bookings": result, "year": year, "month": month})

class ApiCreateBlockedBookingsHandler(BaseHandler, AdminRequiredMixin):
    """Create blocked bookings for a date range (admin only)."""
    def post(self):
        try:
            data = tornado.escape.json_decode(self.request.body)
        except Exception:
            self.write_json({"error": "Invalid JSON"}, 400)
            return
        
        try:
            hall_id = int(data.get("hall_id"))
            start_date = data.get("start_date", "").strip()
            end_date = data.get("end_date", "").strip()
            start_time = data.get("start_time", "").strip()
            end_time = data.get("end_time", "").strip()
            message = data.get("message", "").strip()
            requester_name = data.get("requester_name", "").strip()
            
            # Optional day_of_week parameter (0=Sunday, 1=Monday, ..., 6=Saturday)
            day_of_week_str = data.get("day_of_week", "").strip()
            day_of_week = int(day_of_week_str) if day_of_week_str else None
            
            # Validate day_of_week is in valid range
            if day_of_week is not None and (day_of_week < 0 or day_of_week > 6):
                self.write_json({"error": "day_of_week must be between 0 (Sunday) and 6 (Saturday)"}, 400)
                return
                
        except (TypeError, ValueError):
            self.write_json({"error": "Invalid input"}, 400)
            return
        
        if not all([start_date, end_date, start_time, end_time]):
            self.write_json({"error": "All date and time fields are required"}, 400)
            return
        
        # Validate dates
        try:
            from datetime import datetime as dt
            dt.strptime(start_date, "%Y-%m-%d")
            dt.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            self.write_json({"error": "Invalid date format. Use YYYY-MM-DD"}, 400)
            return
        
        # Check if admin owns this hall
        halls = get_halls_for_admin(self.current_user["id"])
        if not any(h["id"] == hall_id for h in halls):
            self.write_json({"error": "Not authorized for this hall"}, 403)
            return
        
        # Create blocked bookings
        count = create_blocked_bookings(
            hall_id, 
            self.current_user["id"],
            start_date, 
            end_date, 
            start_time, 
            end_time,
            message,
            requester_name,
            day_of_week
        )
        
        day_msg = ""
        if day_of_week is not None:
            day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            day_msg = f" (every {day_names[day_of_week]})"
        
        self.write_json({
            "ok": True, 
            "count": count,
            "message": f"Created {count} blocked booking(s) from {start_date} to {end_date}{day_msg}"
        })


class ApiDeleteBlockedEventHandler(BaseHandler, AdminRequiredMixin):
    """Delete every occurrence in one admin-created date-range event."""
    def delete(self, event_group_id):
        hall_id = get_blocked_event_hall(event_group_id)
        if hall_id is None:
            self.write_json({"error": "Event series not found"}, 404)
            return
        halls = get_halls_for_admin(self.current_user["id"])
        if not any(h["id"] == hall_id for h in halls):
            self.write_json({"error": "Not authorized to delete this event"}, 403)
            return
        deleted_count = delete_blocked_event(event_group_id)
        self.write_json({"ok": True, "deleted_count": deleted_count})

class HealthHandler(BaseHandler):
    def get(self):
        self.write_json({"status": "ok", "time": datetime.utcnow().isoformat()})

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def make_app():
    settings = {
        "cookie_secret": COOKIE_SECRET,
        "template_path": os.path.join(os.path.dirname(__file__), "templates"),
        "static_path": os.path.join(os.path.dirname(__file__), "static"),
        "xsrf_cookies": False,  # simplify for demo; enable in production with forms
        "debug": options.debug,
        "login_url": "/login",
    }
    return tornado.web.Application([
        (r"/", IndexHandler),
        (r"/login", LoginHandler),
        (r"/register", RegisterHandler),
        (r"/logout", LogoutHandler),
        (r"/admin", AdminDashboardHandler),
        (r"/admin/calendar", AdminCalendarHandler),
        (r"/dashboard", UserDashboardHandler),
        (r"/search", SearchHandler),
        (r"/hall/([0-9]+)", HallDetailHandler),
        # APIs
        (r"/api/orgs", ApiCreateOrgHandler),
        (r"/api/orgs/([0-9]+)", ApiDeleteOrgHandler),
        (r"/api/halls", ApiCreateHallHandler),
        (r"/api/halls/([0-9]+)", ApiDeleteHallHandler),
        (r"/api/bookings", ApiCreateBookingHandler),
        (r"/api/bookings/blocked", ApiCreateBlockedBookingsHandler),
        (r"/api/blocked-events/([A-Za-z0-9-]+)/delete", ApiDeleteBlockedEventHandler),
        (r"/api/bookings/([0-9]+)/approve", ApiApproveBookingHandler),
        (r"/api/bookings/([0-9]+)/reject", ApiRejectBookingHandler),
        (r"/api/bookings/([0-9]+)/accept-suggestion", ApiAcceptSuggestionHandler),
        (r"/api/bookings/([0-9]+)/delete", ApiDeleteBookingHandler),
        (r"/api/bookings/([0-9]+)/alternatives", ApiGetAlternativeHallsHandler),
        (r"/api/notifications", ApiNotificationsHandler),
        (r"/api/notifications/([0-9]+)/read", ApiMarkNotifHandler),
        (r"/api/halls/([0-9]+)/bookings", ApiHallBookingsHandler),
        (r"/api/halls/([0-9]+)/bookings/month", ApiHallMonthBookingsHandler),
        (r"/health", HealthHandler),
    ], **settings)

def main():
    tornado.options.parse_command_line()
    from database import USE_POSTGRES, DATABASE_URL
    init_db()
    app = make_app()
    port = options.port
    app.listen(port, address="0.0.0.0")
    logger.info(f"Hall Booking Platform running on http://0.0.0.0:{port}")
    if USE_POSTGRES:
        safe = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "configured"
        logger.info(f"Database: Neon/PostgreSQL ({safe})")
    else:
        logger.info("Database: SQLite fallback (set DATABASE_URL for Neon Postgres)")
    logger.info("Demo admin: admin / admin123")
    logger.info("Demo user:  demo_user / user123")
    tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
