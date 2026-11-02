"""Durable capture boundaries and bounded recovery of explicit rejections.

Never retries a request: a terminal freshness rejection permits a later slot.
Pending/unknown attempts hold across process restarts. No gap is consumption.
"""
import hashlib,json,re,sqlite3,uuid
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
    db.execute('CREATE TABLE IF NOT EXISTS capture_continuations(attempt_id TEXT PRIMARY KEY,binding_sha256 TEXT NOT NULL,review_json TEXT NOT NULL,readiness_json TEXT NOT NULL,approval_reference TEXT NOT NULL,accepted_at TEXT NOT NULL,FOREIGN KEY(attempt_id) REFERENCES continuous_capture_attempts(attempt_id))')
    for action in ('UPDATE','DELETE'):
        db.execute("CREATE TRIGGER IF NOT EXISTS capture_continuations_no_"+action.lower()+" BEFORE "+action+" ON capture_continuations BEGIN SELECT RAISE(ABORT,'capture_continuation_immutable'); END")

def boundary(db,event):
    rows=db.execute('SELECT b.failure_id,b.error,b.outcome,f.error FROM capture_failure_boundaries b LEFT JOIN failures f ON f.rowid=b.failure_id WHERE b.after_event_id=? ORDER BY b.failure_id',(event-1,)).fetchall()
    for ident,error,outcome,actual in rows:
        if error!=actual or outcome not in ('rejected','unknown'):raise ValueError('capture_failure_boundary_invalid')
    return bool(rows)

def publication_blocked(db,event,active_attempt=None):
    # A normal in-process capture does not invalidate the previous bounded-age
    # publication. The ephemeral identity is lost on a crash, so its unmatched
    # durable intent blocks publication after restart, before a new POST.
    return boundary(db,event+1) or unresolved(db,active_attempt)

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
            'hold_reason':reason,'attempt_count':total,'failure_count':failed,'last_failure':dict(zip(('at','error'),last)) if last else None,'recent_attempts':[dict(zip(names,r)) for r in reversed(rows)],
            'accepted_unknown_gaps':len(accepted_continuations(db))}

def rejection_streak(db,first,accepted=None):
    # Intent order is durable and independent of wall-clock adjustments. Read at
    # most the limit: three rejections hold even if an older success exists.
    # Across all contexts: changing a floor must never replenish this allowance.
    accepted=accepted_continuations(db) if accepted is None else accepted
    rows=db.execute('SELECT a.after_event_id,o.outcome,o.event_id,o.error,a.attempt_id '
                    'FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) '
                    'ORDER BY a.rowid DESC')
    count=0
    for after,outcome,event,error,ident in rows:
        # Explicit acceptance preserves the unknown outcome and does not replenish
        # the rejection allowance. Only a real committed event resets the streak.
        if outcome=='unknown' and ident in accepted:continue
        if outcome=='committed':
            # A label alone must not replenish the allowance. Require the same
            # event binding that finish_transaction enforces for real commits.
            if type(event) is not int or event!=after+1 or error is not None or not db.execute(
                    'SELECT 1 FROM capture_events WHERE event_id=?',(event,)).fetchone():
                return count,'capture_recovery_ledger_invalid'
            return count,None
        if outcome=='rejected' and event is None and error==FRESHNESS:
            count+=1
            if count>=MAX_REJECTIONS:return count,None
        else:
            return count,'capture_recovery_ledger_invalid'
    return count,None

def readiness(db,first):
    unknown=unresolved(db)
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


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def continuation_binding(db,ident):
    row=db.execute('SELECT a.attempt_id,a.first_event,a.after_event_id,a.started_at,o.outcome,o.event_id,o.error,o.finished_at FROM continuous_capture_attempts a JOIN continuous_capture_outcomes o USING(attempt_id) WHERE a.attempt_id=?',(ident,)).fetchone()
    if not row or row[4:7]!=('unknown',None,'camera_timeout'):
        raise ValueError('continuation_requires_terminal_timeout')
    try:
        start,end=(datetime.fromisoformat(row[i]) for i in (3,7))
        if start.tzinfo is None or end.tzinfo is None or end<start:raise ValueError()
    except (TypeError,ValueError):raise ValueError('continuation_invalid_timestamps') from None
    boundaries=[]
    for b in db.execute('SELECT b.failure_id,b.after_event_id,b.error,b.outcome,f.received_at,f.error FROM capture_failure_boundaries b JOIN failures f ON f.rowid=b.failure_id WHERE b.after_event_id=? AND b.error=? AND b.outcome=?',(row[2],row[6],row[4])):
        try:stamp=datetime.fromisoformat(b[4])
        except (ValueError,TypeError):raise ValueError('continuation_invalid_timestamps') from None
        if stamp.tzinfo is not None and start<=stamp<=end and b[2]==b[5]:boundaries.append(b)
    if len(boundaries)!=1:raise ValueError('continuation_failure_binding_invalid')
    return {'attempt':row,'failure_boundary':boundaries[0]}


def accepted_continuations(db):
    result=set()
    for ident,binding,review,ready,approval,at in db.execute('SELECT * FROM capture_continuations'):
        try:
            saved=json.loads(review);camera=json.loads(ready)
            from camera_status import validate
            if validate(camera)['state']!='ready':raise ValueError()
            if (saved['attempt_id']!=ident or saved['binding_sha256']!=binding
                    or binding!=digest(continuation_binding(db,ident))
                    or not approval or datetime.fromisoformat(at).tzinfo is None):raise ValueError()
        except (KeyError,TypeError,ValueError):raise ValueError('capture_continuation_invalid') from None
        result.add(ident)
    return result


def unresolved(db,active_attempt=None):
    accepted=accepted_continuations(db)
    for ident,outcome in db.execute("SELECT a.attempt_id,o.outcome FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) WHERE o.attempt_id IS NULL OR o.outcome='unknown'"):
        if outcome is None and ident!=active_attempt:return True
        if outcome=='unknown' and ident not in accepted:return True
    return False


def continuation_record(db,ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[0-9a-f]{32}',ident):raise ValueError('continuation_attempt_id_invalid')
    # Validate all saved permissions before reporting one as accepted.
    accepted=accepted_continuations(db)
    if ident not in accepted:return {'state':'not_accepted','attempt_id':ident}
    binding,review,ready,approval,at=db.execute('SELECT binding_sha256,review_json,readiness_json,approval_reference,accepted_at FROM capture_continuations WHERE attempt_id=?',(ident,)).fetchone()
    return {'state':'gap_accepted','attempt_id':ident,'binding_sha256':binding,
            'review_sha256':json.loads(review)['review_sha256'],'approval_reference':approval,
            'accepted_at':at,'unknown_outcome_preserved':True,'gap_delta':None}


def continuation_review(db,first,context):
    """Read all capture ledger metadata; no camera I/O and no database writes.

    A review describes acceptance of an unknown historical gap, never evidence
    of successful capture. The subsequent POST must match this exact snapshot.
    """
    accepted=accepted_continuations(db)
    rows=db.execute('SELECT a.attempt_id,a.first_event,a.after_event_id,o.outcome,o.event_id,o.error FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o USING(attempt_id) ORDER BY a.rowid').fetchall()
    if db.execute('SELECT 1 FROM continuous_capture_outcomes o LEFT JOIN continuous_capture_attempts a USING(attempt_id) WHERE a.attempt_id IS NULL').fetchone():raise ValueError('capture_recovery_ledger_invalid')
    if db.execute('SELECT 1 FROM capture_events e LEFT JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id WHERE f.camera IS NULL').fetchone():raise ValueError('capture_recovery_ledger_invalid')
    if db.execute('SELECT 1 FROM capture_clocks c LEFT JOIN frames f ON f.camera=c.camera AND f.frame_id=c.frame_id WHERE f.camera IS NULL').fetchone():raise ValueError('capture_recovery_ledger_invalid')
    if db.execute('SELECT 1 FROM capture_failure_boundaries b LEFT JOIN failures f ON f.rowid=b.failure_id WHERE f.rowid IS NULL OR b.error!=f.error OR b.outcome NOT IN (\'rejected\',\'unknown\')').fetchone():raise ValueError('capture_recovery_ledger_invalid')
    unknown=[]
    for ident,floor,after,outcome,event,error in rows:
        if type(floor) is not int or floor<1 or type(after) is not int or after<0:raise ValueError('capture_recovery_ledger_invalid')
        if outcome is None:raise ValueError('continuation_pending_attempt')
        if outcome=='committed':
            if type(event) is not int or event!=after+1 or error is not None or not db.execute('SELECT 1 FROM capture_events WHERE event_id=?',(event,)).fetchone():raise ValueError('capture_recovery_ledger_invalid')
        elif outcome=='rejected':
            if event is not None or error!=FRESHNESS:raise ValueError('capture_recovery_ledger_invalid')
        elif outcome=='unknown':
            if event is not None or not isinstance(error,str) or not error:raise ValueError('capture_recovery_ledger_invalid')
            if ident not in accepted:unknown.append(ident)
        else:raise ValueError('capture_recovery_ledger_invalid')
    if len(unknown)!=1 or not rows or rows[-1][0]!=unknown[0]:raise ValueError('continuation_requires_one_latest_unknown')
    ident=unknown[0];binding=continuation_binding(db,ident)
    last=db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]
    if last!=binding['attempt'][2]:raise ValueError('continuation_saved_event_conflict')
    count,invalid=rejection_streak(db,first,accepted|{ident})
    if invalid or count>=MAX_REJECTIONS:raise ValueError(invalid or 'freshness_recovery_exhausted')
    # Hash complete ordered metadata, including all historical contexts and prior
    # acceptances. Changes while a human reviews the action invalidate its token.
    hashes={}
    for table in ('frames','capture_events','capture_clocks','failures','capture_failure_boundaries','continuous_capture_attempts','continuous_capture_outcomes','capture_continuations'):
        hashes[table]=digest(db.execute('SELECT rowid,* FROM '+table+' ORDER BY rowid').fetchall())
    review={'action':'accept-gap-and-continue','attempt_id':ident,'after_event_id':last,
            'first_event':first,'binding_sha256':digest(binding),'ledger_sha256':digest(hashes),
            'context_sha256':digest(context),'unknown_outcome_preserved':True,
            'gap_delta':None,'new_capture_only':True,'consecutive_rejections':count}
    return dict(review,review_sha256=digest(review))


def accept_continuation(db,first,context,request,camera_status):
    # Caller owns the collector and camera operation locks plus BEGIN IMMEDIATE.
    if not isinstance(request,dict) or set(request)!={'action','attempt_id','review_sha256','approval_reference'} or request['action']!='accept-gap-and-continue':raise ValueError('continuation_request_invalid')
    if not isinstance(request['approval_reference'],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,160}',request['approval_reference']):raise ValueError('continuation_approval_reference_required')
    from camera_status import validate
    camera_status=validate(camera_status)
    if camera_status['state']!='ready':raise ValueError('continuation_camera_not_ready')
    review=continuation_review(db,first,context)
    if request['attempt_id']!=review['attempt_id'] or request['review_sha256']!=review['review_sha256']:raise ValueError('continuation_review_changed')
    db.execute('INSERT INTO capture_continuations VALUES(?,?,?,?,?,?)',(review['attempt_id'],review['binding_sha256'],canonical(review),canonical(camera_status),request['approval_reference'],datetime.now(timezone.utc).isoformat()))
    return {'state':'gap_accepted','attempt_id':review['attempt_id'],'review_sha256':review['review_sha256'],'unknown_outcome_preserved':True,'gap_delta':None}
