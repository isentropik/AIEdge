"""Incremental gap endpoints for photo retention. The capture ledger is authoritative."""
from bisect import bisect_left
from dataclasses import dataclass
import sqlite3

from gap_images import LONG_INTERVAL_US

PAGE = 384
FRAME_EVENT = '(SELECT event_id FROM capture_events WHERE camera={r}.camera AND frame_id={r}.frame_id)'
ATTEMPT_EDGE = '(SELECT after_event_id+1 FROM continuous_capture_attempts WHERE attempt_id={r}.attempt_id)'
INPUTS = {
    'capture_events': '{r}.event_id', 'frames': FRAME_EVENT, 'capture_clocks': FRAME_EVENT,
    'continuous_capture_attempts': '{r}.after_event_id+1', 'continuous_capture_outcomes': ATTEMPT_EDGE,
    'capture_failure_boundaries': '{r}.after_event_id+1', 'consumption_segment_links': '{r}.first_event',
    'consumption_records': '{r}.event_id', 'human_reviews': None, 'retired_images': None,
    'original_receipts': None,
}
RANGE_INDEXES = {
    'continuous_capture_attempts': 'after_event_id', 'capture_failure_boundaries': 'after_event_id',
    'consumption_records': 'event_id', 'consumption_segment_links': 'first_event',
    'retired_images': 'pending',
}
DIGEST_INPUTS = {
    'frames': '{r}.sha256', 'human_reviews': '{r}.sha256', 'retired_images': '{r}.sha256',
    'capture_events': '(SELECT sha256 FROM frames WHERE camera={r}.camera AND frame_id={r}.frame_id)',
    'continuous_capture_outcomes': '(SELECT f.sha256 FROM capture_events e JOIN frames f USING(camera,frame_id) '
                                   'WHERE e.event_id={r}.event_id)',
}


def digest_bucket(image):
    return -3-ord(image[0])*128-ord(image[1])


def version(db):
    return (db.execute('PRAGMA main.schema_version').fetchone()[0],
            db.execute('SELECT revision FROM retention_pages WHERE page=-1').fetchone()[0])


def install(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.execute('CREATE TABLE IF NOT EXISTS retention_pages(page INTEGER PRIMARY KEY, revision INTEGER NOT NULL)')
    db.execute('INSERT OR IGNORE INTO retention_pages VALUES(-1,0)')
    for table, column in RANGE_INDEXES.items():
        if table in tables:
            db.execute(f'CREATE INDEX IF NOT EXISTS retention_{table}_range ON {table}({column})')
    for table, event in INPUTS.items():
        if table not in tables:
            continue
        for action, names in (('INSERT', ('NEW',)), ('UPDATE', ('OLD','NEW')), ('DELETE', ('OLD',))):
            sql = 'UPDATE retention_pages SET revision=revision+1 WHERE page=-1;'
            if event:
                for name in names:
                    edge = event.format(r=name)
                    sql += (f' INSERT INTO retention_pages SELECT max(0,({edge})/{PAGE}),1 WHERE ({edge}) IS NOT NULL'
                            ' ON CONFLICT(page) DO UPDATE SET revision=revision+1;')
            if table in DIGEST_INPUTS:
                for name in names:
                    image = DIGEST_INPUTS[table].format(r=name)
                    sql += (f' INSERT INTO retention_pages SELECT -3-unicode(substr(s,1,1))*128-unicode(substr(s,2,1)),1'
                            f' FROM (SELECT {image} AS s) WHERE length(s)>=2'
                            ' ON CONFLICT(page) DO UPDATE SET revision=revision+1;')
            db.execute(f'CREATE TRIGGER IF NOT EXISTS retention_{table}_{action} AFTER {action} ON {table} BEGIN {sql} END')
        # REPLACE can silently discard a conflicting row without firing DELETE.
        # Invalidate the old position before inserting its replacement.
        if event or table in DIGEST_INPUTS:
            keys = [r[1] for r in db.execute(f'PRAGMA table_info({table})') if r[5]]
            if keys:
                match = ' AND '.join(f't.{key}=NEW.{key}' for key in keys)
                if table == 'capture_events':
                    match += ' OR (t.camera=NEW.camera AND t.frame_id=NEW.frame_id)'
                if table == 'human_reviews':
                    match += ' OR t.revision=NEW.revision'
                db.execute(f'CREATE TRIGGER IF NOT EXISTS retention_{table}_replace BEFORE INSERT ON {table} '
                           f'WHEN EXISTS(SELECT 1 FROM {table} t WHERE {match}) BEGIN '
                           'INSERT INTO retention_pages VALUES(0,1) ON CONFLICT(page) '
                           'DO UPDATE SET revision=revision+1; '
                           'INSERT INTO retention_pages VALUES(-2,1) ON CONFLICT(page) '
                           'DO UPDATE SET revision=revision+1; END')
    return tables


@dataclass
class Block:
    last: tuple
    segments: dict
    gaps: set


class RetentionHistory:
    def __init__(self):
        self.schema = None
        self.versions = {}
        self.blocks = []

    def _edges(self, db, low, high):
        # The right event is the first saved event strictly after a boundary.
        args = (low, high)
        edges = {r[0] for r in db.execute('SELECT after_event_id FROM capture_failure_boundaries '
                                          'WHERE after_event_id>=? AND after_event_id<?', args)}
        edges.update(r[0] for r in db.execute(
            'SELECT a.after_event_id FROM continuous_capture_attempts a LEFT JOIN continuous_capture_outcomes o '
            'USING(attempt_id) WHERE a.after_event_id>=? AND a.after_event_id<? '
            "AND (o.outcome IS NULL OR o.outcome!='committed')", args))
        if 'consumption_segment_links' in self.tables:
            edges.update(r[0]-1 for r in db.execute(
                'SELECT first_event FROM consumption_segment_links WHERE first_event>? AND first_event<=?', args))
        return sorted(edges)

    def _block(self, db, previous, segments, head):
        low = previous[0] if previous else 0
        rows = db.execute('SELECT e.event_id,f.sha256,e.camera,c.clock_id,c.monotonic_us FROM capture_events e '
                          'JOIN frames f USING(camera,frame_id) LEFT JOIN capture_clocks c USING(camera,frame_id) '
                          'WHERE e.event_id>? AND e.event_id<=? ORDER BY e.event_id LIMIT ?', (low,head,PAGE)).fetchall()
        if not rows:
            raise ValueError('retention event missing')
        high = rows[-1][0]
        edges = self._edges(db, low, high)
        observations = {}
        if 'consumption_records' in self.tables:
            records = db.execute(f'SELECT {self.segment_column}, event_id, '
                                 "json_extract(result,'$.observation_accepted'), json_extract(result,'$.state'), "
                                 "json_extract(result,'$.upper_unbounded') FROM consumption_records "
                                 'WHERE event_id>? AND event_id<=? ORDER BY event_id', (low,high)).fetchall()
            for key, event, accepted, state, unbounded in records:
                observations.setdefault(event, []).append((key, accepted, state=='ambiguous' or unbounded==1))
        gaps = set()
        segments = segments.copy()
        for row in rows:
            event, digest, camera, clock, tick = row
            point = (event,digest)
            if previous:
                edge = bisect_left(edges, previous[0])
                if ((edge<len(edges) and edges[edge]<event) or previous[2:4]!=(camera,clock)
                        or clock is None or previous[4] is None or tick is None
                        or not 0<tick-previous[4]<LONG_INTERVAL_US):
                    gaps.add((previous[:2],point))
            for key, accepted, uncertain in observations.pop(event, ()):
                prior, _, ambiguous = segments.get(key,(None,None,False))
                if accepted==1:
                    if prior and (prior != previous[:2] or (uncertain and not ambiguous)):
                        gaps.add((prior,point))
                    prior, ambiguous = point, uncertain
                segments[key] = prior, point, ambiguous
            previous = row
        if observations:
            raise ValueError('retention accounting event missing')
        return Block(previous, segments, gaps)

    def snapshot(self, db):
        schema = db.execute('PRAGMA main.schema_version').fetchone()[0]
        if schema != self.schema:
            db.execute('BEGIN IMMEDIATE')
            self.tables = install(db)
            self.segment_column = ('segment_id' if any(r[1]=='segment_id' for r in
                                   db.execute('PRAGMA table_info(consumption_records)')) else "''")
            self.schema = version(db)[0]
            db.commit()
            self.versions.clear()
            self.blocks.clear()
        db.execute('BEGIN')
        token = version(db)
        if token[0]!=self.schema:
            db.rollback()
            raise sqlite3.OperationalError('retention schema changed during planning')
        revisions = dict(db.execute('SELECT page,revision FROM retention_pages WHERE page>=0'))
        head = db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0]
        db.commit()
        changed = [page for page in revisions if revisions[page]!=self.versions.get(page)]
        if changed:
            first = min(changed)*PAGE
            while self.blocks and self.blocks[-1].last[0]>=first:
                self.blocks.pop()
        self.versions = revisions
        previous = self.blocks[-1].last if self.blocks else None
        segments = self.blocks[-1].segments if self.blocks else {}
        while (previous[0] if previous else 0)<head:
            # Only one bounded page holds a read transaction on the live ledger.
            db.execute('BEGIN')
            try:
                block = self._block(db, previous, segments, head)
            finally:
                db.commit()
            self.blocks.append(block)
            previous, segments = block.last, block.segments
        gaps = set().union(*(block.gaps for block in self.blocks))
        if previous and self._edges(db, head, 2**63-1):
            gaps.add((previous[:2],previous[:2]))
        if 'consumption_records' in self.tables and db.execute(
                'SELECT 1 FROM consumption_records WHERE event_id>? LIMIT 1',(head,)).fetchone():
            raise ValueError('retention accounting event missing')
        for prior,last,_ in segments.values():
            if prior and prior!=last:
                gaps.add((prior,last))
        return token, head, [(a,b,(left,right)) for (a,left),(b,right) in sorted(gaps,reverse=True)]
