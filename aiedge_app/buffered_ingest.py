"""Admit a validated burst slot to the ordinary image and event ledger before ACK."""
import capture_clock
from capture import validate, verified_image

def cursor(db,boot,context):
    boundary=db.execute("SELECT after_event FROM buffered_batch_admissions WHERE boot=? AND context=?",(boot,context)).fetchone()
    if boundary is None:
        raise ValueError("missing buffered capture boundary")
    rows=db.execute("SELECT slot,event_id FROM buffered_slot_events WHERE boot=? ORDER BY slot",(boot,)).fetchall()
    ids=[event for _,event in rows]
    if ids!=list(range(boundary[0]+1,boundary[0]+1+len(rows))):
        raise ValueError("non-contiguous buffered event IDs")
    latest=db.execute("SELECT COALESCE(MAX(event_id),0) FROM capture_events").fetchone()[0]
    if latest!=boundary[0]+len(rows):
        raise ValueError("another collector advanced during buffered acquisition")
    return latest,dict(rows)

def commit_slot(store,camera,boot,context,slot,blob,headers,state):
    frame,stamp,digest=validate(blob,headers)
    clock=capture_clock.parse(headers)
    if not clock:raise ValueError("buffered capture requires a clock")
    with store.lock,store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        last,admitted=cursor(db,boot,context)
        if slot in admitted:
            previous=db.execute("""SELECT f.camera,f.frame_id,f.captured_at,f.sha256,f.bytes,c.clock_id,c.monotonic_us
                FROM capture_events e JOIN frames f USING(camera,frame_id) JOIN capture_clocks c USING(camera,frame_id)
                WHERE e.event_id=?""",(admitted[slot],)).fetchone()
            if slot!=max(admitted) or previous!=(camera,frame,stamp,digest,len(blob),*clock):
                raise ValueError("redelivered slot identity conflict")
            verified_image(store.root/'images'/(digest+'.jpg'),digest)
            return
        first_missing=max(admitted,default=-1)+1
        if slot<first_missing:raise ValueError("slot order conflict")
        mask=state['failed_mask']
        if mask & (1<<slot) or any(not mask & (1<<i) for i in range(first_missing,slot)):
            raise ValueError("camera did not attest missing slots")
        for i in range(first_missing,slot):
            db.execute("INSERT INTO buffered_omissions VALUES(?,?,?)",(boot,i,last))
        event=store._insert_frame(db,camera,blob,frame,stamp,digest,clock)
        if event!=last+1:raise ValueError("buffered frame already owned")
        db.execute("INSERT INTO buffered_slot_events VALUES(?,?,?)",(boot,slot,event))
    store.performance.admit(event,digest,None)

def finish_slots(store,boot,context,committed,omitted):
    with store.lock,store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        last,admitted=cursor(db,boot,context)
        if set(admitted)!=committed:raise ValueError("incomplete ordinary buffered events")
        for slot in range(max(admitted,default=-1)+1,5):
            if slot not in omitted:raise ValueError("unexplained trailing slot")
            db.execute("INSERT OR IGNORE INTO buffered_omissions VALUES(?,?,?)",(boot,slot,last))
        absent=db.execute("SELECT slot,after_event FROM buffered_omissions WHERE boot=?",(boot,)).fetchall()
        expected={(i,last-sum(slot>i for slot in admitted)) for i in omitted}
        if set(absent)!=expected:raise ValueError("omission ledger mismatch")
