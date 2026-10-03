"""
Database layer for Hall Booking Platform.

Supports:
  - Neon / any PostgreSQL via DATABASE_URL (persistent cloud DB)
  - SQLite fallback for local demo when DATABASE_URL is not set

To use Neon: set the environment variable
  DATABASE_URL=postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
(or paste your Neon connection string — no code changes needed).
"""

import os
import re
import uuid
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Optional, List, Dict
from dotenv import load_dotenv
import bcrypt as _bcrypt

load_dotenv()
# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))

# SQLite fallback path
_default_sqlite = os.path.join(os.path.dirname(__file__), "data", "hall_booking.db")
DB_PATH = os.environ.get("DB_PATH", _default_sqlite)

# Neon sometimes gives postgres:// — psycopg2 wants postgresql://
if USE_POSTGRES and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------
if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    def get_connection():
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
        return conn

    def _cursor(conn):
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _ph(sql: str) -> str:
        """Convert SQLite-style ? placeholders to %s for psycopg2."""
        return sql.replace("?", "%s")

    def _last_id(cursor) -> int:
        # Prefer RETURNING when we use it; fallback for older inserts
        if cursor.description:
            row = cursor.fetchone()
            if row is not None:
                # RealDictCursor or tuple
                if isinstance(row, dict):
                    return row.get("id") or list(row.values())[0]
                return row[0]
        return None

else:
    import sqlite3

    def get_connection():
        # Prefer /tmp if project data/ is on a FUSE mount that breaks SQLite
        path = DB_PATH
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            test = sqlite3.connect(path, timeout=2)
            test.execute("SELECT 1")
            test.close()
        except Exception:
            path = "/tmp/hall_booking.db"
        conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        return conn

    def _cursor(conn):
        return conn.cursor()

    def _ph(sql: str) -> str:
        return sql

    def _last_id(cursor) -> int:
        return cursor.lastrowid


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row) -> Optional[Dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def _rows_to_list(rows) -> List[Dict]:
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def init_db():
    with db_session() as conn:
        c = _cursor(conn)

        if USE_POSTGRES:
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS organizations (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL,
                    description TEXT,
                    admin_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS halls (
                    id SERIAL PRIMARY KEY,
                    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    capacity INTEGER DEFAULT 50,
                    amenities TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS booking_requests (
                    id SERIAL PRIMARY KEY,
                    hall_id INTEGER NOT NULL REFERENCES halls(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    booking_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    booking_type TEXT NOT NULL DEFAULT 'request',
                    event_group_id TEXT,
                    message TEXT,
                    admin_note TEXT,
                    suggested_date TEXT,
                    suggested_start TEXT,
                    suggested_end TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    related_booking_id INTEGER REFERENCES booking_requests(id),
                    created_at TEXT NOT NULL
                )
            """)
            # Indexes
            c.execute("CREATE INDEX IF NOT EXISTS idx_org_location ON organizations(location)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_halls_org ON halls(org_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bookings_hall_date ON booking_requests(hall_id, booking_date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status ON booking_requests(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bookings_type ON booking_requests(booking_type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read)")
            
            # Add booking_type column if it doesn't exist (migration)
            try:
                c.execute("""
                    ALTER TABLE booking_requests 
                    ADD COLUMN IF NOT EXISTS booking_type TEXT NOT NULL DEFAULT 'request'
                """)
            except Exception:
                pass  # Column might already exist
        else:
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS organizations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL,
                    description TEXT,
                    admin_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (admin_id) REFERENCES users(id)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS halls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    capacity INTEGER DEFAULT 50,
                    amenities TEXT,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS booking_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hall_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    booking_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    booking_type TEXT NOT NULL DEFAULT 'request',
                    event_group_id TEXT,
                    message TEXT,
                    admin_note TEXT,
                    suggested_date TEXT,
                    suggested_start TEXT,
                    suggested_end TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (hall_id) REFERENCES halls(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    related_booking_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (related_booking_id) REFERENCES booking_requests(id)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_org_location ON organizations(location)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_halls_org ON halls(org_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bookings_hall_date ON booking_requests(hall_id, booking_date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status ON booking_requests(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read)")
            
            # Add booking_type column if it doesn't exist (migration for SQLite)
            try:
                c.execute("ALTER TABLE booking_requests ADD COLUMN booking_type TEXT NOT NULL DEFAULT 'request'")
            except Exception:
                pass  # Column might already exist
            try:
                c.execute("CREATE INDEX IF NOT EXISTS idx_bookings_type ON booking_requests(booking_type)")
            except Exception:
                pass

        # Link each admin-created date-range event so it can be removed as one series.
        if USE_POSTGRES:
            c.execute("ALTER TABLE booking_requests ADD COLUMN IF NOT EXISTS event_group_id TEXT")
        else:
            try:
                c.execute("ALTER TABLE booking_requests ADD COLUMN event_group_id TEXT")
            except Exception:
                pass  # Column might already exist
        c.execute(_ph("CREATE INDEX IF NOT EXISTS idx_bookings_event_group ON booking_requests(event_group_id)"))

        # Older date-range blocks share their creation timestamp and details.
        c.execute(_ph("""
            SELECT id, hall_id, user_id, start_time, end_time, message, admin_note, created_at
            FROM booking_requests
            WHERE booking_type = 'blocked' AND event_group_id IS NULL
            ORDER BY created_at, id
        """))
        legacy_groups = {}
        for row in c.fetchall():
            item = _row_to_dict(row)
            key = tuple(item[field] for field in (
                "hall_id", "user_id", "start_time", "end_time", "message", "admin_note", "created_at"
            ))
            group_id = legacy_groups.setdefault(key, f"legacy-{uuid.uuid4().hex}")
            c.execute(_ph("UPDATE booking_requests SET event_group_id = ? WHERE id = ?"), (group_id, item["id"]))

        # Seed demo data if no admin exists
        c.execute(_ph("SELECT id FROM users WHERE role = ? LIMIT 1"), ("admin",))
        if not c.fetchone():
            now = datetime.utcnow().isoformat()
            pw = hash_password("admin123")
            if USE_POSTGRES:
                c.execute(
                    "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    ("admin", "admin@example.com", pw, "admin", now)
                )
                admin_id = c.fetchone()["id"]
            else:
                c.execute(
                    "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("admin", "admin@example.com", pw, "admin", now)
                )
                admin_id = c.lastrowid

            def _ins_org(name, loc, desc):
                if USE_POSTGRES:
                    c.execute(
                        "INSERT INTO organizations (name, location, description, admin_id, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (name, loc, desc, admin_id, now)
                    )
                    return c.fetchone()["id"]
                else:
                    c.execute(
                        "INSERT INTO organizations (name, location, description, admin_id, created_at) VALUES (?, ?, ?, ?, ?)",
                        (name, loc, desc, admin_id, now)
                    )
                    return c.lastrowid

            def _ins_hall(org_id, name, cap, amen, desc):
                if USE_POSTGRES:
                    c.execute(
                        "INSERT INTO halls (org_id, name, capacity, amenities, description, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                        (org_id, name, cap, amen, desc, now)
                    )
                else:
                    c.execute(
                        "INSERT INTO halls (org_id, name, capacity, amenities, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (org_id, name, cap, amen, desc, now)
                    )

            org_id = _ins_org("City Convention Center", "New York", "Premier event halls in downtown NYC")
            _ins_hall(org_id, "Grand Ballroom", 300, "AV, Stage, Catering", "Elegant ballroom for large events")
            _ins_hall(org_id, "Conference Hall A", 80, "Projector, WiFi, Whiteboard", "Ideal for meetings")
            org2 = _ins_org("Riverside Banquet", "New York", "Scenic riverside venues")
            _ins_hall(org2, "Garden Pavilion", 150, "Outdoor, Lighting, Sound", "Beautiful garden setting")

            pw_user = hash_password("user123")
            if USE_POSTGRES:
                c.execute(
                    "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (%s, %s, %s, %s, %s)",
                    ("demo_user", "user@example.com", pw_user, "user", now)
                )
            else:
                c.execute(
                    "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("demo_user", "user@example.com", pw_user, "user", now)
                )


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------
def create_user(username, email, password, role="user"):
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        if USE_POSTGRES:
            c.execute(
                "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (username, email, hash_password(password), role, now)
            )
            return c.fetchone()["id"]
        else:
            c.execute(
                "INSERT INTO users (username, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, email, hash_password(password), role, now)
            )
            return c.lastrowid


def get_user_by_username(username):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("SELECT * FROM users WHERE username = ?"), (username,))
        return _row_to_dict(c.fetchone())


def get_user_by_id(user_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("SELECT * FROM users WHERE id = ?"), (user_id,))
        return _row_to_dict(c.fetchone())


# ---------------------------------------------------------------------------
# Organization helpers
# ---------------------------------------------------------------------------
def create_organization(name, location, description, admin_id):
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        if USE_POSTGRES:
            c.execute(
                "INSERT INTO organizations (name, location, description, admin_id, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (name, location, description, admin_id, now)
            )
            return c.fetchone()["id"]
        else:
            c.execute(
                "INSERT INTO organizations (name, location, description, admin_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, location, description, admin_id, now)
            )
            return c.lastrowid


def get_organizations_by_admin(admin_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("SELECT * FROM organizations WHERE admin_id = ? ORDER BY name"), (admin_id,))
        return _rows_to_list(c.fetchall())


def get_organization(org_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("SELECT * FROM organizations WHERE id = ?"), (org_id,))
        return _row_to_dict(c.fetchone())


def search_organizations(location=None, query=None):
    with db_session() as conn:
        c = _cursor(conn)
        sql = "SELECT * FROM organizations WHERE 1=1"
        params = []
        if location:
            sql += " AND location LIKE ?"
            params.append(f"%{location}%")
        if query:
            sql += " AND (name LIKE ? OR description LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        sql += " ORDER BY name"
        c.execute(_ph(sql), params)
        return _rows_to_list(c.fetchall())


# ---------------------------------------------------------------------------
# Hall helpers
# ---------------------------------------------------------------------------
def create_hall(org_id, name, capacity, amenities, description):
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        if USE_POSTGRES:
            c.execute(
                "INSERT INTO halls (org_id, name, capacity, amenities, description, created_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (org_id, name, capacity, amenities, description, now)
            )
            return c.fetchone()["id"]
        else:
            c.execute(
                "INSERT INTO halls (org_id, name, capacity, amenities, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (org_id, name, capacity, amenities, description, now)
            )
            return c.lastrowid


def get_halls_by_org(org_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("SELECT * FROM halls WHERE org_id = ? ORDER BY name"), (org_id,))
        return _rows_to_list(c.fetchall())


def get_hall(hall_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT h.*, o.name as org_name, o.location as org_location
            FROM halls h JOIN organizations o ON h.org_id = o.id
            WHERE h.id = ?
        """), (hall_id,))
        return _row_to_dict(c.fetchone())


def get_halls_for_admin(admin_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT h.*, o.name as org_name, o.location as org_location
            FROM halls h
            JOIN organizations o ON h.org_id = o.id
            WHERE o.admin_id = ?
            ORDER BY o.name, h.name
        """), (admin_id,))
        return _rows_to_list(c.fetchall())


def delete_organization(org_id, admin_id):
    """
    Delete an organization if the admin owns it.
    This will cascade delete all halls and bookings due to ON DELETE CASCADE.
    
    Returns:
        (success: bool, message: str)
    """
    with db_session() as conn:
        c = _cursor(conn)
        
        # Verify admin owns this organization
        c.execute(_ph("SELECT id FROM organizations WHERE id = ? AND admin_id = ?"), (org_id, admin_id))
        if not c.fetchone():
            return False, "Organization not found or you don't own it"
        
        # Delete the organization (halls and bookings will cascade delete)
        c.execute(_ph("DELETE FROM organizations WHERE id = ?"), (org_id,))
        
        return True, "Organization deleted successfully"


def delete_hall(hall_id, admin_id):
    """
    Delete a hall if the admin owns its organization.
    This will cascade delete all bookings for this hall.
    
    Returns:
        (success: bool, message: str)
    """
    with db_session() as conn:
        c = _cursor(conn)
        
        # Verify admin owns the organization that owns this hall
        c.execute(_ph("""
            SELECT h.id 
            FROM halls h
            JOIN organizations o ON h.org_id = o.id
            WHERE h.id = ? AND o.admin_id = ?
        """), (hall_id, admin_id))
        
        if not c.fetchone():
            return False, "Hall not found or you don't own it"
        
        # Delete the hall (bookings will cascade delete)
        c.execute(_ph("DELETE FROM halls WHERE id = ?"), (hall_id,))
        
        return True, "Hall deleted successfully"
        return _rows_to_list(c.fetchall())


# ---------------------------------------------------------------------------
# Booking helpers
# ---------------------------------------------------------------------------
def create_booking_request(hall_id, user_id, booking_date, start_time, end_time, message=""):
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        if USE_POSTGRES:
            c.execute("""
                INSERT INTO booking_requests
                (hall_id, user_id, booking_date, start_time, end_time, status, message, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s) RETURNING id
            """, (hall_id, user_id, booking_date, start_time, end_time, message, now, now))
            return c.fetchone()["id"]
        else:
            c.execute("""
                INSERT INTO booking_requests
                (hall_id, user_id, booking_date, start_time, end_time, status, message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (hall_id, user_id, booking_date, start_time, end_time, message, now, now))
            return c.lastrowid


def get_booking(booking_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT b.*, h.name as hall_name, h.org_id, o.name as org_name,
                   u.username as requester_name
            FROM booking_requests b
            JOIN halls h ON b.hall_id = h.id
            JOIN organizations o ON h.org_id = o.id
            JOIN users u ON b.user_id = u.id
            WHERE b.id = ?
        """), (booking_id,))
        return _row_to_dict(c.fetchone())


def get_pending_bookings_for_admin(admin_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT b.*, h.name as hall_name, o.name as org_name, u.username as requester_name
            FROM booking_requests b
            JOIN halls h ON b.hall_id = h.id
            JOIN organizations o ON h.org_id = o.id
            JOIN users u ON b.user_id = u.id
            WHERE o.admin_id = ? AND b.status = 'pending'
            ORDER BY b.booking_date, b.start_time
        """), (admin_id,))
        return _rows_to_list(c.fetchall())


def get_bookings_for_hall_date(hall_id, booking_date):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT b.*, u.username as requester_name
            FROM booking_requests b
            JOIN users u ON b.user_id = u.id
            WHERE b.hall_id = ? AND b.booking_date = ? AND b.status IN ('approved', 'pending')
            ORDER BY b.start_time
        """), (hall_id, booking_date))
        return _rows_to_list(c.fetchall())


def get_user_bookings(user_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT b.*, h.name as hall_name, o.name as org_name, o.location
            FROM booking_requests b
            JOIN halls h ON b.hall_id = h.id
            JOIN organizations o ON h.org_id = o.id
            WHERE b.user_id = ?
            ORDER BY b.created_at DESC
        """), (user_id,))
        return _rows_to_list(c.fetchall())


def approve_booking(booking_id, admin_note=""):
    """Approve one and auto-reject overlapping pending requests for same hall/date/time."""
    booking = get_booking(booking_id)
    if not booking or booking["status"] != "pending":
        return False
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        c.execute(_ph("""
            UPDATE booking_requests SET status='approved', admin_note=?, updated_at=? WHERE id=?
        """), (admin_note, now, booking_id))
        c.execute(_ph("""
            SELECT id, user_id FROM booking_requests
            WHERE hall_id = ? AND booking_date = ? AND status = 'pending' AND id != ?
              AND start_time < ? AND end_time > ?
        """), (booking["hall_id"], booking["booking_date"], booking_id,
              booking["end_time"], booking["start_time"]))
        overlaps = c.fetchall()
        for ov in overlaps:
            ov = _row_to_dict(ov)
            c.execute(_ph("""
                UPDATE booking_requests SET status='rejected', admin_note=?, updated_at=? WHERE id=?
            """), ("Slot taken by another approved booking. Original request conflicted.", now, ov["id"]))
            c.execute(_ph("""
                INSERT INTO notifications (user_id, title, message, related_booking_id, created_at)
                VALUES (?, ?, ?, ?, ?)
            """), (ov["user_id"], "Booking Rejected",
                  f"Your booking request for {booking['hall_name']} on {booking['booking_date']} was rejected because the slot was approved for another user.",
                  ov["id"], now))
        c.execute(_ph("""
            INSERT INTO notifications (user_id, title, message, related_booking_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """), (booking["user_id"], "Booking Approved!",
              f"Your booking for {booking['hall_name']} on {booking['booking_date']} ({booking['start_time']}-{booking['end_time']}) has been approved.",
              booking_id, now))
        return True


def reject_booking_with_suggestion(booking_id, admin_note, suggested_date, suggested_start, suggested_end):
    booking = get_booking(booking_id)
    if not booking or booking["status"] != "pending":
        return False
    
    # Get hall details to find organization
    hall = get_hall(booking["hall_id"])
    if not hall:
        return False
    
    # Find alternative halls if no specific suggestion provided
    alternative_halls = []
    if not suggested_date:  # Admin didn't manually suggest a slot
        # Use the original requested date/time to find alternatives
        alternative_halls = get_available_halls_in_org(
            hall["org_id"],
            booking["booking_date"],
            booking["start_time"],
            booking["end_time"],
            exclude_hall_id=booking["hall_id"]
        )
    
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        c.execute(_ph("""
            UPDATE booking_requests
            SET status='rejected', admin_note=?, suggested_date=?, suggested_start=?, suggested_end=?, updated_at=?
            WHERE id=?
        """), (admin_note, suggested_date, suggested_start, suggested_end, now, booking_id))
        
        # Build notification message
        msg = f"Your booking for {booking['hall_name']} on {booking['booking_date']} was rejected. "
        if suggested_date:
            msg += f"Suggested alternative: {suggested_date} {suggested_start}-{suggested_end}. You can accept it from your dashboard."
        elif alternative_halls:
            msg += f"However, {len(alternative_halls)} other hall(s) in the same organization are available for your requested timeslot: "
            hall_names = [h['name'] for h in alternative_halls[:3]]  # Show up to 3
            msg += ", ".join(hall_names)
            if len(alternative_halls) > 3:
                msg += f" and {len(alternative_halls) - 3} more"
            msg += ". Please visit the organization page to book one of these alternatives."
        
        c.execute(_ph("""
            INSERT INTO notifications (user_id, title, message, related_booking_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """), (booking["user_id"], "Booking Rejected - See Alternatives", msg, booking_id, now))
        return True


def accept_suggested_slot(booking_id, user_id):
    booking = get_booking(booking_id)
    if not booking or booking["user_id"] != user_id or not booking.get("suggested_date"):
        return False
    new_id = create_booking_request(
        booking["hall_id"], user_id,
        booking["suggested_date"], booking["suggested_start"], booking["suggested_end"],
        message=f"Accepted suggestion from previous request #{booking_id}"
    )
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        note = (booking.get("admin_note") or "") + " | User accepted suggestion"
        c.execute(_ph("""
            UPDATE booking_requests SET status='rejected', admin_note=?, updated_at=?
            WHERE id=?
        """), (note, now, booking_id))
    return new_id


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def get_notifications(user_id, unread_only=False):
    with db_session() as conn:
        c = _cursor(conn)
        sql = "SELECT * FROM notifications WHERE user_id = ?"
        params = [user_id]
        if unread_only:
            sql += " AND is_read = 0"
        sql += " ORDER BY created_at DESC LIMIT 50"
        c.execute(_ph(sql), params)
        return _rows_to_list(c.fetchall())


def mark_notification_read(notif_id, user_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?"), (notif_id, user_id))
        return c.rowcount > 0


def mark_all_notifications_read(user_id):
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("UPDATE notifications SET is_read = 1 WHERE user_id = ?"), (user_id,))
        return True


def get_approved_bookings_for_hall(hall_id, from_date=None):
    with db_session() as conn:
        c = _cursor(conn)
        sql = """
            SELECT b.booking_date, b.start_time, b.end_time, b.status, b.booking_type, b.message, u.username as requester_name
            FROM booking_requests b
            JOIN users u ON b.user_id = u.id
            WHERE b.hall_id = ? AND b.status = 'approved'
        """
        params = [hall_id]
        if from_date:
            sql += " AND b.booking_date >= ?"
            params.append(from_date)
        sql += " ORDER BY b.booking_date, b.start_time"
        c.execute(_ph(sql), params)
        return _rows_to_list(c.fetchall())

def get_available_halls_in_org(org_id, booking_date, start_time, end_time, exclude_hall_id=None):
    """
    Find halls in the same organization that have no conflicting bookings
    (approved or pending) for the requested time slot.
    """
    with db_session() as conn:
        c = _cursor(conn)
        # Get all halls in the organization
        sql = """
            SELECT h.id, h.name, h.capacity, h.amenities, h.description
            FROM halls h
            WHERE h.org_id = ?
        """
        params = [org_id]
        if exclude_hall_id:
            sql += " AND h.id != ?"
            params.append(exclude_hall_id)
        c.execute(_ph(sql), params)
        halls = _rows_to_list(c.fetchall())
        
        available_halls = []
        for hall in halls:
            # Check if this hall has any conflicting bookings
            c.execute(_ph("""
                SELECT COUNT(*) as count
                FROM booking_requests
                WHERE hall_id = ? 
                  AND booking_date = ?
                  AND status IN ('approved', 'pending')
                  AND start_time < ? 
                  AND end_time > ?
            """), (hall["id"], booking_date, end_time, start_time))
            result = c.fetchone()
            count = _row_to_dict(result)["count"] if result else 0
            if count == 0:
                available_halls.append(hall)
        
        return available_halls


def get_bookings_for_hall_month(hall_id, year, month):
    """
    Get all approved and pending bookings for a hall for a specific month.
    Returns bookings with requester name and message for calendar display.
    """
    from calendar import monthrange
    
    # Get the number of days in the month
    _, num_days = monthrange(year, month)
    
    # Build date range
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{num_days:02d}"
    
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("""
            SELECT b.*, u.username as requester_name
            FROM booking_requests b
            JOIN users u ON b.user_id = u.id
            WHERE b.hall_id = ? 
              AND b.booking_date >= ? 
              AND b.booking_date <= ?
              AND b.status IN ('approved', 'pending')
            ORDER BY b.booking_date, b.start_time
        """), (hall_id, start_date, end_date))
        return _rows_to_list(c.fetchall())


def create_blocked_bookings(hall_id, admin_id, start_date, end_date, start_time, end_time, message="", requester_name="", day_of_week=None):
    """
    Create multiple blocked bookings for a date range (e.g., Jan-June, 8am-12pm daily).
    These bookings are created by admin and marked as 'blocked' type with 'approved' status.
    They appear as blue on the calendar and are visible to all users.
    
    Args:
        hall_id: The hall to block
        admin_id: The admin creating the block (stored as user_id)
        start_date: First date to block (YYYY-MM-DD)
        end_date: Last date to block (YYYY-MM-DD)
        start_time: Time slot start (HH:MM)
        end_time: Time slot end (HH:MM)
        message: Reason for blocking (e.g., "Reserved for XYZ Corp")
        requester_name: Name to display (e.g., "Admin Block" or requester's name)
        day_of_week: Optional specific day of week (0=Sunday, 1=Monday, ..., 6=Saturday).
                     If None, blocks all consecutive days in range.
                     If specified, only blocks that day of the week.
    
    Returns:
        Number of bookings created
    """
    from datetime import datetime as dt, timedelta
    
    # Parse dates
    start = dt.strptime(start_date, "%Y-%m-%d").date()
    end = dt.strptime(end_date, "%Y-%m-%d").date()
    
    if end < start:
        return 0
    
    created_count = 0
    event_group_id = uuid.uuid4().hex
    current_date = start
    
    with db_session() as conn:
        c = _cursor(conn)
        now = datetime.utcnow().isoformat()
        
        while current_date <= end:
            # Skip if day_of_week is specified and current date doesn't match
            # Python's weekday(): Monday=0, Sunday=6
            # But our selector uses: Sunday=0, Monday=1, ..., Saturday=6
            if day_of_week is not None:
                # Convert Python's weekday (Mon=0) to our format (Sun=0)
                python_weekday = current_date.weekday()  # Mon=0, Tue=1, ..., Sun=6
                our_weekday = (python_weekday + 1) % 7  # Sun=0, Mon=1, ..., Sat=6
                
                if our_weekday != int(day_of_week):
                    current_date += timedelta(days=1)
                    continue
            
            date_str = current_date.strftime("%Y-%m-%d")
            
            # Check if there's already an approved or blocked booking for this slot
            c.execute(_ph("""
                SELECT COUNT(*) as count
                FROM booking_requests
                WHERE hall_id = ? 
                  AND booking_date = ?
                  AND status IN ('approved', 'blocked')
                  AND booking_type IN ('request', 'blocked')
                  AND start_time < ? 
                  AND end_time > ?
            """), (hall_id, date_str, end_time, start_time))
            
            result = c.fetchone()
            conflict_count = _row_to_dict(result)["count"] if result else 0
            
            if conflict_count == 0:
                # Create blocked booking
                c.execute(_ph("""
                    INSERT INTO booking_requests 
                    (hall_id, user_id, booking_date, start_time, end_time, 
                     status, booking_type, event_group_id, message, admin_note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), (
                    hall_id, admin_id, date_str, start_time, end_time,
                    'approved', 'blocked', event_group_id, message, 
                    f"Blocked by admin. Requester: {requester_name or 'N/A'}",
                    now, now
                ))
                created_count += 1
            
            current_date += timedelta(days=1)
    
    return created_count


def delete_blocked_event(event_group_id):
    """Delete every date occurrence belonging to one admin-created blocked event."""
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("DELETE FROM booking_requests WHERE event_group_id = ? AND booking_type = 'blocked'"),
                  (event_group_id,))
        return c.rowcount


def get_blocked_event_hall(event_group_id):
    """Return the hall containing a blocked event series, if it still exists."""
    with db_session() as conn:
        c = _cursor(conn)
        c.execute(_ph("SELECT hall_id FROM booking_requests WHERE event_group_id = ? AND booking_type = 'blocked' LIMIT 1"),
                  (event_group_id,))
        row = c.fetchone()
        item = _row_to_dict(row)
        return item["hall_id"] if item else None


def delete_booking(booking_id, user_id, is_admin=False):
    """
    Delete a booking if:
    1. User is admin who owns the hall, OR
    2. User is the requester and booking hasn't started yet
    
    Returns: (success: bool, message: str)
    """
    from datetime import datetime as dt
    
    booking = get_booking(booking_id)
    if not booking:
        return False, "Booking not found"
    
    # Check authorization
    if not is_admin and booking["user_id"] != user_id:
        return False, "Not authorized to delete this booking"
    
    # Check if booking has already started (only for non-admins)
    if not is_admin:
        now = dt.utcnow()
        booking_datetime_str = f"{booking['booking_date']} {booking['start_time']}"
        try:
            booking_start = dt.strptime(booking_datetime_str, "%Y-%m-%d %H:%M")
            if booking_start <= now:
                return False, "Cannot delete booking that has already started"
        except ValueError:
            pass  # If parsing fails, allow deletion
    
    # Delete the booking
    with db_session() as conn:
        c = _cursor(conn)
        
        # First, delete or update related notifications to avoid foreign key constraint
        c.execute(_ph("DELETE FROM notifications WHERE related_booking_id = ?"), (booking_id,))
        
        # Then delete the booking
        c.execute(_ph("DELETE FROM booking_requests WHERE id = ?"), (booking_id,))
        
        # Create notification for the requester if admin deleted it
        if is_admin and booking["user_id"] != user_id:
            now_iso = datetime.utcnow().isoformat()
            msg = f"Your booking for {booking['hall_name']} on {booking['booking_date']} ({booking['start_time']}-{booking['end_time']}) was cancelled by admin."
            c.execute(_ph("""
                INSERT INTO notifications (user_id, title, message, created_at)
                VALUES (?, ?, ?, ?)
            """), (booking["user_id"], "Booking Cancelled", msg, now_iso))
    
    return True, "Booking deleted successfully"
