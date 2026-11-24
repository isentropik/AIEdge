"""Photo-conditioned absolute estimates must preserve both turn ambiguity and capture gaps."""

import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import absolute_motion as motion
from nominal_register import AbsolutePublisher

DAY = datetime(2026, 1, 1, tzinfo=timezone.utc)


def source(e, **changes):
    return dict(
        {
            "event_id": e,
            "camera": "meter",
            "format_id": "fmt",
            "clock_id": "epoch",
            "context_id": "ctx",
            "monotonic_us": e * 10000000,
            "captured_at": (DAY + timedelta(seconds=e * 10)).isoformat(),
            "source_sha256": f"{e:064x}",
        },
        **changes,
    )


def options(base):
    return [
        (D(base) + offset, D(base) + offset + D(".1")) for offset in range(0, 30, 5)
    ]


def phase(value):
    return D(value), D(value) + D(".1")


DOC = {"dials": [{"value_per_revolution": 5}], "maximum_rate_per_second": ".2"}


class Store:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "create table capture_failure_boundaries(after_event_id integer)"
        )
        self.db.execute("create table consumption_segment_links(first_event integer)")

    @contextmanager
    def connect(self):
        yield self.db


class AbsoluteMotionTests(unittest.TestCase):
    def test_photo_center_selects_a_reachable_band_without_discarding_uncertainty(self):
        opts = [(D(n),D(n)+D('.1')) for n in ('100','105','110','115')]
        def select(center, floor, limit):
            return motion.start(source(10), opts, D(floor), previous=D('101'),
                                limit=D(limit), photo_center=D(center))
        result=select('111','102','11')
        self.assertEqual(result['level'],'110.05')
        self.assertEqual(result['outer'],['100','115.1'])
        self.assertEqual(select('115','102','8')['level'],'105.05')
        self.assertIsNone(select('100','102','2'))

    def setUp(self):
        self.one = source(1)
        self.t = motion.start(self.one, options("429.64"), 0)
        self.store = Store()
        self.addCleanup(self.store.db.close)

    def test_middle_feasible_band_and_outward_envelope(self):
        state = self.t["display"]
        self.assertEqual(D(state["value_ft3"]), D("439.69"))
        self.assertEqual((state["lower_ft3"], state["upper_ft3"]), ("429.6", "454.8"))
        self.assertEqual(state["anchor_source_sha256"], self.one["source_sha256"])

    def test_bounds_are_independent_of_nominal_movement(self):
        same = motion.advance(self.t, source(2), phase("4.64"), D(5), D(9), None)
        self.assertEqual(same["level"], self.t["level"])
        self.assertGreater(D(same["outer"][1]), D(self.t["outer"][1]))
        narrow = motion.advance(
            same, source(3), phase("4.64"), D(5), D(1), options("439.64")[:1]
        )
        self.assertEqual(narrow["level"], same["level"])
        self.assertLess(D(narrow["outer"][1]), D(same["outer"][1]))

    def test_crossing_zero_and_hundred_advances_only_supported_movement(self):
        t = motion.start(self.one, [phase("499.85")], 0)
        after = motion.advance(t, source(2), phase(".12"), D(5), D(1), None)
        self.assertEqual(D(after["level"]), D("500.12"))
        self.assertEqual(after["display"]["event_id"], 2)
        self.assertIsNone(
            motion.advance(t, source(2), phase(".12"), D(5), D(".01"), None)
        )

    def track(self, t, target, rows, bands=None):
        rows = {t["source"]["event_id"]: (t["source"], phase("0")), **rows}

        def read(db, lo, hi, *_, **__):
            return {k: v for k, v in rows.items() if lo <= k <= hi}

        with patch.object(motion, "phases", read):
            return motion.update(t, self.store, {"format": DOC}, target, bands, 0)

    def test_failure_stops_motion_and_new_photo_establishes_position_only(self):
        self.store.db.execute("insert into capture_failure_boundaries values(1)")
        two = source(2)
        rows = {2: (two, phase(".10"))}
        self.assertEqual(self.track(self.t, two, rows)["display"], self.t["display"])
        new = self.track(self.t, two, rows, options("430.1"))
        self.assertEqual(new["anchor"], two)
        self.assertEqual(D(new["level"]), D("440.1"))
        self.assertLess(D(new["outer"][0]), D(new["level"]))
        self.assertNotIn("delta", new["display"])

    def test_agreeing_dials_only_reanchor_across_a_break_with_reachable_bounds(self):
        two = source(2)
        rows = {1: (self.one, phase("4.64")), 2: (two, phase(".10"))}
        # The current absolute bands permit a further turn, but an unbroken
        # fine-dial track still determines which turn actually occurred.
        def observed(opts):
            with patch.object(motion, "phases", return_value=rows):
                return motion.update(self.t, self.store, {"format": DOC}, two, None, 0, gap_options=opts)
        self.assertEqual(observed(options("445.1"))["anchor"], self.one)
        self.store.db.execute("insert into capture_failure_boundaries values(1)")
        self.assertEqual(observed(options("445.1"))["display"], self.t["display"])
        self.assertEqual(observed(options("440.1"))["anchor"], two)

    def test_missing_phase_before_recorded_break_can_reanchor_only_on_full_photo(self):
        for eid in (4, motion.PAGE + 4):
            with self.subTest(eid=eid):
                head = source(eid)
                rows = {1: (self.one, phase("4.64")), eid: (head, phase(".1"))}
                db = self.store.db
                db.execute("delete from consumption_segment_links")
                def project(bands):
                    def samples(db, lo, hi, *args, **kwargs):
                        return {t: row for t, row in rows.items() if lo <= t <= hi}
                    with patch.object(motion, "phases", samples):
                        return motion.update(self.t, self.store, {"format": DOC}, head, None, 0,
                                             gap_options=bands)
                self.assertEqual(project(options("440.1")), self.t)
                db.execute("insert into consumption_segment_links values(?)", (eid,))
                self.assertEqual(project(None), self.t)
                self.assertEqual(project(options("9999.1")), self.t)
                anchored = project(options("440.1"))
                self.assertEqual((anchored["source"], anchored["anchor"]), (head, head))
                self.assertNotIn("delta", anchored["display"])
                rows[1] = (source(1, source_sha256="wrong"), phase("4.64"))
                self.assertEqual(project(options("440.1")), self.t)

    def test_current_full_photo_and_accounting_must_support_the_same_bounds(self):
        src = self.one
        full = dict(schema_version=1, source_sha256=src["source_sha256"], pipeline_id="pipe",
                    partial=False, reader_observed=[True, True], document_observed=[True, True])
        def absolute(lo, hi):
            return dict(unit="ft3", bounds=dict(state="bounded", wraps_register=False,
                                                ranges=[dict(lower=lo, upper=hi)]))
        raw = dict(absolute(435, 436), state="ambiguous", format_id="fmt", source_sha256=src["source_sha256"])
        doc = dict(pipeline_id="pipe", dials=[dict(value_per_revolution=1000), dict(value_per_revolution=5)])
        c = dict(observation_support=full, observation_accepted=True,
                 absolute=dict(absolute(435.5, 440), provenance="temporal_consumption_bounds"))
        snap = dict(format=doc, consumption=c, _raw_meter_reading=raw)
        self.assertEqual(motion.observed_bands(snap,src), [(D("435.5"), D("436"))])
        for change in [dict(partial=True),dict(document_observed=[True,False]),dict(reader_observed=[1,1]),
                       dict(source_sha256="different"),dict(pipeline_id="old")]:
            c["observation_support"]=dict(full, **change)
            self.assertIsNone(motion.observed_bands(snap,src))
        c["observation_support"]=full
        c["absolute"]=dict(absolute(450,451),provenance="temporal_consumption_bounds")
        self.assertFalse(motion.observed_bands(snap,src))

    def test_mismatched_saved_predecessor_cannot_move_estimate(self):
        rows = {
            1: (source(1, source_sha256="different"), phase("4.64")),
            2: (source(2), phase("4.9")),
        }
        self.assertEqual(self.track(self.t, source(2), rows), self.t)

    def test_missing_sample_wrong_head_and_clock_reset_hold_measurement(self):
        three = source(3)
        for two, rows in [
            (None, {3: (three, phase("1"))}),
            (
                source(2),
                {
                    2: (source(2), phase(".1")),
                    3: (source(3, source_sha256="other"), phase("1")),
                },
            ),
            (
                source(2, clock_id="other"),
                {2: (source(2, clock_id="other"), phase(".1")), 3: (three, phase("1"))},
            ),
        ]:
            with self.subTest(two=two):
                self.assertEqual(
                    self.track(self.t, three, rows)["display"], self.t["display"]
                )

    def test_disagreement_does_not_switch_turn_or_advance_held_time(self):
        two, three = source(2), source(3)
        rows = {2: (two, phase("4.7")), 3: (three, phase("4.8"))}
        conflict = self.track(self.t, two, rows, options("444.7")[:1])
        self.assertEqual(conflict["display"], self.t["display"])
        held = self.track(conflict, three, rows)
        self.assertEqual(held["display"], self.t["display"])
        self.assertTrue(held["needs_confirmation"])

    def test_same_saved_events_in_one_call_or_across_restart(self):
        two, three = source(2), source(3)
        rows = {2: (two, phase("4.8")), 3: (three, phase(".15"))}
        whole = self.track(self.t, three, rows)
        half = self.track(self.t, two, rows)
        restored = json.loads(json.dumps(half))
        self.assertEqual(self.track(restored, three, rows), whole)
        self.assertEqual(D(whole["level"]), D("440.15"))

    def test_photo_only_first_install_and_hold_do_not_create_consumption_checkpoint(
        self,
    ):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint"
            out = SimpleNamespace(
                config={"unique_id": "u"},
                daily=SimpleNamespace(store=self.store),
                interval=5,
                base="test",
                _publish=lambda *args: None,
            )
            proof = {
                "source": self.one,
                "bands_ft3": [list(map(str, b)) for b in options("429.64")],
            }
            snap = {
                "consumption": {"event_observation": self.one},
                "format": DOC,
                "_photo_register": proof,
            }
            with patch.object(motion, "endpoint", return_value=self.one):
                pub = AbsolutePublisher(path)
                pub.publish(out, None, snap)
            self.assertEqual(pub.displayed[1]["value_ft3"], self.t["level"])
            self.assertIsNone(pub.sent)
            with patch.object(motion, "endpoint", return_value=None):
                restarted = AbsolutePublisher(path)
                restarted.publish(out, None, dict(snap, _photo_register=None))
            self.assertEqual(
                restarted.displayed[1]["measured_at"], self.one["captured_at"]
            )
            self.assertEqual(restarted.displayed[1]["status"], "held_at_last_reading")
            self.assertIsNone(restarted.sent)

    def test_migration_rejects_older_or_mismatched_photo_and_uses_same_event(self):
        rec = {
            "format_id": "fmt",
            "source_identity": sha256(b"meter").hexdigest(),
            "state": None,
        }
        src = source(3)
        legacy = {
            "event_id": 3,
            "source_sha256": src["source_sha256"],
            "clock_id": "epoch",
            "monotonic_us": src["monotonic_us"],
            "measured_at": src["captured_at"],
            "value_ft3": "400",
            "upper_exclusive_ft3": 500,
        }
        for s, ok in [
            (source(2), False),
            (source(3, source_sha256="other"), False),
            (src, True),
        ]:
            snap = {
                "format": DOC,
                "_photo_register": {"source": s, "bands_ft3": options("429.64")},
            }
            with patch.object(motion, "endpoint", return_value=s):
                result, current = motion.project(
                    dict(rec, photo_register=legacy),
                    rec,
                    None,
                    snap,
                    None,
                    SimpleNamespace(store=self.store),
                    DAY,
                    90,
                )
            self.assertEqual(current, ok)
            if ok:
                self.assertEqual(result["display"]["event_id"], 3)
