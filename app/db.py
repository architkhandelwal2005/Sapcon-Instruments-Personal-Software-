import atexit
import os

import psycopg
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

load_dotenv()

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # A WhatsApp message holds one connection for its whole background task -
        # transcription, extraction, resolution, then the readback fetch - so a
        # couple of voice notes arriving together can starve the web pages at
        # max_size=5.
        _pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
        atexit.register(_pool.close)
    return _pool


def get_connection() -> psycopg.Connection:
    """Check out a connection from the shared pool instead of cold-connecting
    to the Supabase pooler every time (10-60s on a fresh connect). Every
    caller keeps its existing `conn = get_connection(); ...; release_connection(conn)`
    shape - release_connection() returns the connection to the pool rather
    than closing the socket."""
    return _get_pool().getconn()


def release_connection(conn: psycopg.Connection) -> None:
    """Return a connection to the pool. Most callers never call conn.commit()
    on a read-only path, which leaves the transaction open (psycopg3 has no
    autocommit by default) - roll it back here so the pool doesn't do it
    itself and log a warning on nearly every request."""
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        conn.rollback()
    _get_pool().putconn(conn)
