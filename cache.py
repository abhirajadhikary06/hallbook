"""
Simple thread-safe in-memory cache for frequently accessed read data.
Designed for low-concurrency (20-30 users) on a single free-tier server.
"""
import time
import threading
from functools import wraps

class SimpleCache:
    def __init__(self, default_ttl=60):
        self._store = {}
        self._lock = threading.RLock()
        self.default_ttl = default_ttl

    def get(self, key):
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            value, expires = item
            if expires and time.time() > expires:
                del self._store[key]
                return None
            return value

    def set(self, key, value, ttl=None):
        with self._lock:
            expires = time.time() + (ttl if ttl is not None else self.default_ttl)
            self._store[key] = (value, expires)

    def delete(self, key):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()

    def delete_prefix(self, prefix):
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]

# Global cache instance
cache = SimpleCache(default_ttl=90)

def cached(key_prefix, ttl=60):
    """Decorator for caching function results."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Build a simple key from args (skip self if method)
            key_parts = [key_prefix] + [str(a) for a in args] + [f"{k}={v}" for k, v in sorted(kwargs.items())]
            key = ":".join(key_parts)
            val = cache.get(key)
            if val is not None:
                return val
            result = fn(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator

def invalidate_org_cache():
    cache.delete_prefix("orgs:")
    cache.delete_prefix("halls:")
    cache.delete_prefix("search:")
