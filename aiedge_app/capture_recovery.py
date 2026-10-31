"""Durable capture boundaries and bounded recovery of explicit rejections.

Never retries a request: a terminal freshness rejection permits a later slot.
Pending/unknown attempts hold across process restarts. No gap is consumption.
"""
import sqlite3,uuid
from datetime import datetime,timezone

# Only consecutive acknowledged freshness rejections consume this allowance.
# Lifetime rejections remain in the immutable ledger and status diagnostics.
MAX_REJECTIONS=3
FRESHNESS='camera_clock_changed'

class FreshnessRejected(ValueError):
    """Only constructed after the exact acknowledged firmware HTTP 503 body."""
    def __init__(self):super().__init__(FRESHNESS)

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS capture_failure_boundaries(failure_id INTEGER PRIMARY KEY,after_event_id INTEGER NOT NULL,error TEXT NOT NULL,outcome TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS continuous_capture_attempts(attempt_id TEXT PRIMARY KEY,first_event INTEGER NOT NULL,after_event_id INTEGER NOT NULL,started_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS continuous_capture_outcomes(attempt_id TEXT PRIMARY KEY,outcome TEXT NOT NULL,event_id INTEGER,error TEXT,finished_at TEXT NOT NULL,FOREIGN KEY(attempt_id) REFERENCES continuous_capture_attempts(attempt_id))')

def boundary(db,event):
    rows=db.execute('SELECT b.failure_id,b.error,b.outcome,f.error FROM capture_failure_boundaries b LEFT JOIN failures f ON f.rowid=b.failure_id WHERE b.after_event_id=? ORDER BY b.failure_id',(event-1,)).fetchall()
    for ident,error,outcome,actual in rows:
        if error!=actual or outcome not in ('rejected','unknown'):raise ValueError('capture_failure_boundary_invalid')
    return bool(rows)

def publication_blocked(db,event,active_attempt=None):
    # A normal in-process capture does not invalidate the previous bounded-age
    # publication. The ephemeral identity is lost on a crash, so its unmatched
    # durable intent blocks publication after restart, before a new POST.
    return boundary(db,event+1) or db.execute("SELECT 1 FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) WHERE (o.attempt_id IS NULL AND a.attempt_id!=?) OR o.outcome='unknown' LIMIT 1",(active_attempt or '',)).fetchone() is not None

def snapshot(db,first):
    reason,count=readiness(db,first)
    consecutive,_=rejection_streak(db,first)
    lifetime=db.execute("SELECT COUNT(*) FROM continuous_capture_outcomes WHERE outcome='rejected'").fetchone()[0]
    rows=db.execute('SELECT a.attempt_id,a.after_event_id,a.started_at,o.outcome,o.event_id,o.error,o.finished_at FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) WHERE a.first_event=? ORDER BY a.rowid DESC LIMIT 10',(first,)).fetchall()
    total=db.execute('SELECT COUNT(*) FROM continuous_capture_attempts WHERE first_event=?',(first,)).fetchone()[0]
    names=('attempt_id','after_event_id','started_at','outcome','event_id','error','finished_at')
    failed=db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]
    last=db.execute('SELECT received_at,error FROM failures ORDER BY rowid DESC LIMIT 1').fetchone()
    return {'first_event':first,'maximum_rejections':MAX_REJECTIONS,'rejections':count,
            'rejection_policy':'consecutive_acknowledged','consecutive_rejections':consecutive,'lifetime_rejections':lifetime,
            'hold_reason':reason,'attempt_count':total,'failure_count':failed,'last_failure':dict(zip(('at','error'),last)) if last else None,'recent_attempts':[dict(zip(names,r)) for r in reversed(rows)]}

def rejection_streak(db,first):
    # Intent order is durable and independent of wall-clock adjustments. Read at
    # most the limit: three rejections hold even if an older success exists.
    # Across all contexts: changing a floor must never replenish this allowance.
    rows=db.execute('SELECT a.after_event_id,o.outcome,o.event_id,o.error '
                    'FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) '
                    'ORDER BY a.rowid DESC LIMIT ?',
                    (MAX_REJECTIONS,)).fetchall()
    count=0
    for after,outcome,event,error in rows:
        if outcome=='committed':
            # A label alone must not replenish the allowance. Require the same
            # event binding that finish_transaction enforces for real commits.
            if type(event) is not int or event!=after+1 or error is not None or not db.execute(
                    'SELECT 1 FROM capture_events WHERE event_id=?',(event,)).fetchone():
                return count,'capture_recovery_ledger_invalid'
            return count,None
        if outcome=='rejected' and event is None and error==FRESHNESS:
            count+=1
        else:
            return count,'capture_recovery_ledger_invalid'
    return count,None

def readiness(db,first):
    unknown=db.execute("SELECT 1 FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) WHERE o.attempt_id IS NULL OR o.outcome='unknown' LIMIT 1").fetchone()
    count=db.execute("SELECT COUNT(*) FROM continuous_capture_attempts a JOIN continuous_capture_outcomes o USING(attempt_id) WHERE a.first_event=? AND o.outcome='rejected'",(first,)).fetchone()[0]
    if unknown:return 'unknown_capture_outcome',count
    consecutive,invalid=rejection_streak(db,first)
    return (invalid or ('freshness_recovery_exhausted' if consecutive>=MAX_REJECTIONS else None)),count

def begin(store,first):
    with store.lock,store.connect() as db:
        db.execute('BEGIN IMMEDIATE');reason,count=readiness(db,first)
        if reason:raise ValueError(reason)
        after=db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]
        ident=uuid.uuid4().hex;db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',(ident,first,after,datetime.now(timezone.utc).isoformat()))
        store.active_capture_attempt=ident
    return ident,after

def finish(store,ident,outcome,event=None,error=None):
    with store.lock,store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        finish_transaction(db,ident,outcome,event,error)

def finish_transaction(db,ident,outcome,event=None,error=None):
    if outcome not in ('committed','rejected','unknown'):raise ValueError('capture_outcome_invalid')
    row=db.execute('SELECT after_event_id FROM continuous_capture_attempts WHERE attempt_id=?',(ident,)).fetchone()
    if not row:raise ValueError('capture_attempt_missing')
    if outcome=='committed':
        if type(event) is not int or event!=row[0]+1 or error is not None or not db.execute('SELECT 1 FROM capture_events WHERE event_id=?',(event,)).fetchone():raise ValueError('capture_commit_binding_invalid')
    elif event is not None or not isinstance(error,str) or not error:raise ValueError('capture_failure_binding_invalid')
    if outcome=='rejected':
        if error!=FRESHNESS or db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]!=row[0]:raise ValueError('capture_rejection_binding_invalid')
    db.execute('INSERT INTO continuous_capture_outcomes VALUES(?,?,?,?,?)',(ident,outcome,event,error,datetime.now(timezone.utc).isoformat()))
