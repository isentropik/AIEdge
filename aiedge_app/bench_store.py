"""Private bench ledger. A single database belongs to one sensor/configuration context."""
import hashlib
import json
import sqlite3
import secrets

class BurstStore:
    def __init__(self,path,context,*,existing=False):
        self.db=sqlite3.connect(path,uri=existing)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')
        if existing:
            if self.db.execute("PRAGMA user_version").fetchone()!=(3,):
                self.db.close();raise ValueError("unknown bench ledger schema")
        else:self.db.executescript("""
        PRAGMA user_version=3;
        CREATE TABLE IF NOT EXISTS run(
            sequence INTEGER PRIMARY KEY,
            boot TEXT UNIQUE NOT NULL, context TEXT NOT NULL, owner TEXT NOT NULL, result TEXT, retiring INTEGER NOT NULL DEFAULT 0,target INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS frames(
            boot TEXT NOT NULL REFERENCES run(boot), slot INTEGER NOT NULL CHECK(slot BETWEEN 0 AND 4),
            frame_id TEXT NOT NULL, utc TEXT NOT NULL, epoch TEXT NOT NULL, tick INTEGER NOT NULL,
            digest TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(boot,slot), UNIQUE(boot,frame_id));
        """)
        self.context=context

    def close(self):self.db.close()

    def intent(self,boot,ordinary_store):
        # A power failure must leave both the admission intent and its ordinary
        # usage boundary, or neither. SQLite super-journals require disk-backed
        # rollback journals for both files. Reject other configurations.
        path=(ordinary_store.root/'captures.sqlite3').resolve(strict=True)
        self.db.execute("ATTACH DATABASE ? AS ordinary",(str(path),))
        try:
            self.db.execute("PRAGMA ordinary.synchronous=FULL")
            for schema in ("main","ordinary"):
                if self.db.execute(f"PRAGMA {schema}.journal_mode").fetchone()!=("delete",):
                    raise ValueError("multi-database burst journal unavailable")
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                after=self.db.execute("SELECT COALESCE(MAX(event_id),0) FROM ordinary.capture_events").fetchone()[0]
                self.db.execute("INSERT INTO ordinary.buffered_batch_admissions VALUES(?,?,?,?)",(boot,self.context,after,int(self.entry() is None)))
                self.db.execute("INSERT INTO run(boot,context,owner,target) VALUES(?,?,?,?)",(boot,self.context,secrets.token_hex(16),self.final_generation))
        finally:
            self.db.execute("DETACH DATABASE ordinary")

    def verify_boundary(self,boot,ordinary_store,unfinished):
        with ordinary_store.connect() as db:
            row=db.execute("SELECT after_event FROM buffered_batch_admissions WHERE boot=? AND context=?",(boot,self.context)).fetchone()
            admitted=db.execute("""SELECT b.slot,b.event_id,f.frame_id,f.captured_at,c.clock_id,c.monotonic_us,f.sha256,f.bytes
                FROM buffered_slot_events b JOIN capture_events e USING(event_id)
                JOIN frames f USING(camera,frame_id) JOIN capture_clocks c USING(camera,frame_id)
                WHERE b.boot=? ORDER BY b.slot""",(boot,)).fetchall()
            latest=db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]
        staged=self.db.execute("SELECT slot,frame_id,utc,epoch,tick,digest,length(data),data FROM frames WHERE boot=? ORDER BY slot",(boot,)).fetchall()
        if row is None or not len(admitted)<=len(staged)<=len(admitted)+int(unfinished):
            raise ValueError("ordinary ledger does not match staged slots")
        last=row[0]+len(admitted)
        if latest<last or (unfinished and latest!=last):
            raise ValueError("ordinary ledger does not match burst boundary")
        from capture import verified_image
        for offset,(bound,source) in enumerate(zip(admitted,staged),1):
            slot,event,*metadata=bound
            if event!=row[0]+offset or [slot,*metadata]!=list(source[:-1]):
                raise ValueError("buffered event identity changed")
            if verified_image(ordinary_store.root/'images'/(metadata[-2]+'.jpg'),metadata[-2])!=source[-1]:
                raise ValueError("different bytes for staged event")

    def entry(self):
        return self.db.execute('SELECT boot,context,owner,result FROM run ORDER BY sequence DESC LIMIT 1').fetchone()

    def require_open(self,boot):
        if self.db.execute('SELECT boot,context,result FROM run ORDER BY sequence DESC LIMIT 1').fetchall()!=[(boot,self.context,None)]:
            raise ValueError('no matching unfinished burst intent')

    def saved(self,boot):
        self.require_open(boot)
        rows=self.db.execute('SELECT slot,epoch,tick,digest,data FROM frames WHERE boot=? ORDER BY slot',(boot,))
        result={}
        for slot,epoch,tick,digest,data in rows:
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('stored frame digest changed')
            result[slot]=(epoch,tick)
        return result

    def commit(self,boot,slot,frame_id,utc,clock,digest,data):
        self.require_open(boot)
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('frame digest changed')
        values=(boot,slot,frame_id,utc,*clock,digest,data)
        with self.db:
            existing=self.db.execute('SELECT * FROM frames WHERE boot=? AND slot=?',(boot,slot)).fetchone()
            if existing is None:self.db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?,?,?)',values)
            elif existing!=values:raise ValueError('redelivered frame differs from durable copy')

    def finish(self,boot,result):
        self.require_open(boot)
        with self.db:
            self.db.execute('UPDATE run SET result=? WHERE boot=?',(json.dumps(result,sort_keys=True),boot))
