"""A paused daily calculation must allow the next capture transaction to commit."""
import json
import sqlite3
import unittest
from uuid import uuid4

from daily_records import daily_records


class DailyLedgerTests(unittest.TestCase):
    def test_writer_commits_between_rows_of_the_same_page(self):
        uri = "file:" + uuid4().hex + "?mode=memory&cache=shared"
        reader = sqlite3.connect(uri, uri=True)
        writer = sqlite3.connect(uri, uri=True, timeout=0)
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        reader.executescript("""
            CREATE TABLE capture_events(event_id INTEGER PRIMARY KEY,camera,frame_id);
            CREATE TABLE frames(camera,frame_id,captured_at,sha256);
            CREATE TABLE capture_clocks(camera,frame_id,clock_id,monotonic_us);
            CREATE TABLE consumption_records(segment_id,event_id,result);
            CREATE TABLE consumption_segment_links(segment_id,prior_segment_id,first_event);
        """)
        for event in (1, 2, 65):
            digest = "a" * 64
            stamp = "2026-11-04T01:00:00Z"
            binding = dict(event_id=event,camera="gas",captured_at=stamp,source_sha256=digest,
                           clock_id="boot",monotonic_us=event,context_id="c",format_id="f")
            record = dict(event_id=event,segment_id="s",source_sha256=digest,format_id="f",
                          through_captured_at=stamp,observation_context="c",observation_accepted=True,
                          observation_current_through_us=event,event_observation=binding)
            reader.execute("INSERT INTO capture_events VALUES (?,?,?)",(event,"gas",event))
            reader.execute("INSERT INTO frames VALUES (?,?,?,?)",("gas",event,stamp,digest))
            reader.execute("INSERT INTO capture_clocks VALUES (?,?,?,?)",("gas",event,"boot",event))
            reader.execute("INSERT INTO consumption_records VALUES (?,?,?)",("s",event,json.dumps(record)))
        reader.commit()
        rows = daily_records(reader,1,65,"s")
        self.assertEqual(next(rows)["event_id"],1)
        with writer:
            writer.execute("INSERT INTO capture_events VALUES (66,'gas',66)")
        self.assertEqual([r["event_id"] for r in rows],[2,65])
