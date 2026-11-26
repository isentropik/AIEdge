"""Synthetic register faces and isolated MQTT-checkpoint regressions."""

import hashlib
from io import BytesIO
import json
import sqlite3
import unittest
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image, ImageDraw

from nominal_register import AbsolutePublisher, photo_projection
from photo_register import bracketed_tip, dark_stroke, hundreds, PhotoRegister
from reading_format import validate
from test_reading_format import document


def dial_faces(upper=0.43, lower=4.43):
    reference = np.full((480, 640), 210, dtype=np.uint8)
    rng = np.random.default_rng(21)
    markers = []
    for x in (130, 300, 470):
        reference[320:348, x : x + 32] = rng.integers(30, 220, size=(28, 32))
        markers.append({"box": [x, 320, 32, 28]})
    image = Image.fromarray(reference)
    draw = ImageDraw.Draw(image)
    faces = [{} for _ in range(4)]
    for index, x, position, direction in ((1, 220, upper, "cw"), (2, 400, lower, "ccw")):
        y, radius = 150, 60
        angle = position * np.pi / 5 * (1 if direction == "cw" else -1)
        point = (x + radius * np.sin(angle), y - radius * np.cos(angle))
        draw.line(((x, y), point), fill=12, width=5)
        faces[index] = dict(
            model="main",
            direction=direction,
            landmarks=dict(
                needle_pivot=[x, y],
                rim_points=[[x, y - radius], [x + radius, y], [x, y + radius], [x - radius, y]],
            ),
        )
    profile = dict(dials=faces, markers=markers)
    doc = {
        "dials": [
            dict(index=i, value_per_revolution=scale, position_error=0.1)
            for i, scale in enumerate((100000, 10000, 1000, 5))
        ]
    }
    return profile, reference.astype("f"), np.asarray(image, dtype="f"), doc


class FaceTests(unittest.TestCase):
    def test_small_disagreement_can_resolve_when_both_pointers_and_index_are_visible(self):
        from reading_bounds import diagnose_inconsistency
        profile, ref, img, doc = dial_faces(.43, 5.01)
        positions = [2.05, .39, 5.10, 1.8]
        self.assertEqual(diagnose_inconsistency(doc, positions)['dial_indices'], [1, 2])
        self.assertIsNone(hundreds(profile, ref, img, doc, positions, [1, 2]))
        for face in (ref, img):
            face[212:219, 399:402] = 12
        proof = hundreds(profile, ref, img, doc, positions, [1, 2])
        self.assertTrue(proof['bands_ft3'])
        self.assertLess(abs(proof['fits'][0]['photo']-positions[1]), .1)
        self.assertTrue(all(float(lo) <= float(hi) for lo, hi in proof['bands_ft3']))

    def test_receipted_original_intersects_the_compact_phase_after_rereading_both_faces(self):
        from threading import Lock
        from types import SimpleNamespace
        from decimal import Decimal
        from original_meter import OriginalMeter
        profile, ref, img, doc = dial_faces(.43, 5.01)
        for face in (ref, img):
            face[212:219, 399:402] = 12
        def encode(face):
            data = BytesIO()
            Image.fromarray(face.astype('uint8')).save(data, format='PNG')
            return data.getvalue()
        reference, blob = encode(ref), encode(img)
        sha = hashlib.sha256(blob).hexdigest()
        profile['reference_sha256'] = hashlib.sha256(reference).hexdigest()
        doc.update(unit='ft3', pipeline_id='a'*64)
        setup = SimpleNamespace(reference=lambda key:reference,
                                status=lambda:dict(calibration=profile,revision='calibrated'))
        store = SimpleNamespace(image=lambda key:blob)
        inference = dict(state='estimated', source_sha256=sha, pipeline_id=doc['pipeline_id'],
                         profile='calibrated', dial_positions=[dict(state='estimated',position=value)
                         for value in (2.05, .39, 5.10, 1.8)])
        reader = SimpleNamespace(read_jpeg=lambda image:inference, pipeline_id=doc['pipeline_id'])
        meter = OriginalMeter(store, SimpleNamespace(lock=Lock(),reader=reader), PhotoRegister(store, setup))
        source = dict(source_sha256=sha)
        self.assertTrue(meter.read_bands(doc, source, (Decimal('.85'), Decimal('.95'))))
        self.assertFalse(meter.read_bands(doc, source, (Decimal('1.8'), Decimal('1.9'))))
        inference['profile'] = 'different'
        self.assertFalse(meter.read_bands(doc, source, (Decimal('.85'), Decimal('.95'))))

    def test_pointer_over_a_division_requires_both_neighboring_marks(self):
        y,x=np.indices((480,640))
        radius=np.hypot(x-320,y-240)/70
        angle=(np.arctan2(x-320,240-y)*5/np.pi)%10
        item=dict(direction='cw',landmarks=dict(needle_pivot=[320,240],
                  rim_points=[[320,170],[390,240],[320,310],[250,240]]))
        reference=np.full(radius.shape,180,dtype=np.float32)
        outer=(radius>1)&(radius<1.11)
        for tick in (5,7):
            reference[outer&(abs(angle-tick)<.045)]=15
        image=reference.copy()
        image[(radius>.80)&(radius<1.10)&(abs(angle-5.94)<.12)]=15
        fit=bracketed_tip(image,reference-image,item,5.91,.1,covered_division=True)
        self.assertAlmostEqual(fit[0],5.94,delta=.04)
        image[outer&(abs(angle-7)<.15)]=180
        self.assertIsNone(bracketed_tip(image,reference-image,item,5.91,.1,covered_division=True))

    def test_two_printed_divisions_bound_the_independent_moving_tip(self):
        y,x=np.indices((480,640))
        radius=np.hypot(x-320,y-240)/70
        angle=(np.arctan2(x-320,240-y)*5/np.pi)%10
        item=dict(direction='cw',landmarks=dict(needle_pivot=[320,240],
                  rim_points=[[320,170],[390,240],[320,310],[250,240]]))
        reference=np.full(radius.shape,180,dtype=np.float32)
        outer=(radius>1.00)&(radius<1.11)
        for tick in (5,6):
            reference[outer&(abs(angle-tick)<.045)]=15
        image=reference.copy()
        image[(radius>.80)&(radius<.96)&(abs(angle-5.45)<.12)]=15
        fit=bracketed_tip(image,reference-image,item,5.38,.1)
        self.assertAlmostEqual(fit[0],5.45,delta=.025)
        self.assertIsNone(bracketed_tip(image,np.zeros_like(image),item,5.38,.1))
        image[outer&(abs(angle-6)<.10)]=180
        self.assertIsNone(bracketed_tip(image,reference-image,item,5.38,.1))

    def test_print_only_ambiguous_or_clipped_strokes_are_not_pointers(self):
        angles = np.linspace(-.5, .5, 201)
        row = np.where(abs(angles) < .11, 30, 150)
        self.assertIsNone(dark_stroke(angles, row, (.1, .36), np.zeros_like(row)))
        self.assertAlmostEqual(dark_stroke(angles, row, (.1, .36), 150-row), 0, delta=.005)
        extra = np.where(abs(angles-.33) < .065, 30, row)
        self.assertIsNone(dark_stroke(angles, extra, (.1,.36), 150-extra))
        clipped = np.where(angles < -.32, 30, 150)
        self.assertIsNone(dark_stroke(angles, clipped, (.1,.36), 150-clipped))

    def test_outer_tip_in_variable_light_requires_two_stationary_divisions(self):
        y,x=np.indices((480,640))
        radius=np.hypot(x-320,y-240)/70
        angle=(np.arctan2(x-320,240-y)*5/np.pi)%10
        item=dict(direction='cw',landmarks=dict(needle_pivot=[320,240],
                  rim_points=[[320,170],[390,240],[320,310],[250,240]]))
        ticks=(radius>1.02)&(radius<1.15)&((abs(angle-5)<.045)|(abs(angle-6)<.045))
        ref=np.where(ticks,95.,210.)
        image=ref.copy()
        image[(radius>.89)&(radius<.98)&(abs(angle-5.45)<.12)]=95
        def fit(reference):
            return bracketed_tip(image,reference-image,item,5.40,.1,outer_tip=True)
        self.assertAlmostEqual(fit(ref)[0],5.45,delta=.03)
        self.assertIsNone(fit(image))
        ref[ticks & (angle>5.5)]=210
        self.assertIsNone(fit(ref))

    def test_same_side_bias_requires_visible_index_and_preserves_hundreds_carry(self):
        profile, ref, img, doc = dial_faces(.51, 5.01)
        pos = [2.05, .13, 4.97, 1.8]
        self.assertIsNone(hundreds(profile, ref, img, doc, pos, [1,2]))
        for face in (ref,img):
            face[212:219,399:402] = 12
        found = hundreds(profile, ref, img, doc, pos, [1,2])
        self.assertNotIn('register_ft3', found)
        self.assertAlmostEqual(found['photo_center_ft3'],20501,delta=3)
        self.assertLess(float(found['bands_ft3'][0][0]),20500)
        self.assertGreater(float(found['bands_ft3'][-1][1]),20500)
        for positions in ([2.05, .13, 7.3, 1.8], [2.05, 3.7, 4.97, 1.8]):
            self.assertIsNone(hundreds(profile, ref, img, doc, positions,[1,2]))

    def test_opposite_dial_directions_and_translation(self):
        profile, ref, image, doc = dial_faces()
        image = np.roll(image, (3, -2), axis=(0, 1))
        found = hundreds(profile, ref, image, doc, [2.04, 9.78, 4.42, 1.8], [1, 2])
        self.assertEqual(found["register_ft3"], 20400)
        self.assertEqual(found["resolution_ft3"], 100)
        for fit, target in zip(found["fits"], (0.43, 4.43)):
            self.assertAlmostEqual(fit["photo"], target, delta=0.06)

    def test_missing_and_displaced_faces(self):
        profile, ref, image, doc = dial_faces()
        pos = [2.04, 9.78, 4.42, 1.8]
        missing = image.copy()
        missing[75:226, 140:296] = ref[75:226, 140:296]
        for frame in (ref, missing, np.roll(image, 14, axis=0)):
            self.assertIsNone(hundreds(profile, ref, frame, doc, pos, [1, 2]))
        profile["markers"] = [profile["markers"][0]] * 3
        self.assertIsNone(hundreds(profile, ref, image, doc, pos, [1, 2]))

    def test_disagreement_or_two_feasible_hundreds_withholds(self):
        profile, ref, img, doc = dial_faces()
        for pos, indices in (
            ([2.04, 3.7, 4.42, 1.8], [1, 2]),
            ([2.04, 9.78, 7.3, 1.8], [1, 2]),
            ([7.24, 9.78, 4.42, 1.8], [1, 2]),
            ([2.04, 9.78, 4.42, 1.8], [0, 1]),
        ):
            self.assertIsNone(hundreds(profile, ref, img, doc, pos, indices))
        profile, ref, img, doc = dial_faces(0.40, 4.00)
        self.assertIsNone(hundreds(profile, ref, img, doc, [2.04, 9.78, 4.00, 1.8], [1, 2]))


class SourceTests(unittest.TestCase):
    def test_only_the_same_complete_saved_event_can_supply_a_photo(self):
        profile, ref, image, _ = dial_faces()

        def png(pixels):
            buffer = BytesIO()
            Image.fromarray(pixels.astype("uint8")).save(buffer, format="PNG")
            return buffer.getvalue()

        image_bytes = png(image)
        digest = hashlib.sha256(image_bytes).hexdigest()
        ref_bytes = png(ref)
        profile["reference_sha256"] = hashlib.sha256(ref_bytes).hexdigest()

        class Saved:
            def image(self, sha):
                return image_bytes

            def status(self):
                return dict(calibration=profile, revision="calibrated")

            def reference(self, sha):
                return ref_bytes

        doc = document([100000, 10000, 1000, 5], errors=[0.1] * 4)
        format_id = validate(doc)[1]
        source = dict(
            source_sha256=digest,
            event_id=24,
            captured_at="2025-03-03T12:00:00Z",
            camera="fixture",
            clock_id="clock",
            monotonic_us=12345,
            context_id="ctx",
            format_id=format_id,
        )
        support = dict(
            schema_version=1,
            source_sha256=digest,
            pipeline_id=doc["pipeline_id"],
            document_observed=[True] * 4,
        )
        decision = dict(
            reason="consumption_positions_contradict_bounds",
            observation_accepted=False,
            format_id=format_id,
            event_observation=source,
            source_sha256=digest,
            event_id=24,
            segment_id="seg",
            observation_context="ctx",
            observation_support=support,
        )
        inference = dict(
            profile="calibrated",
            source_sha256=digest,
            event_observation=source,
            state="estimated",
            pipeline_id=doc["pipeline_id"],
            dial_positions=[dict(position=v, state="estimated") for v in (2.04, 9.78, 4.42, 1.8)],
        )
        snap = dict(
            latest=dict(sha256=digest, captured_at=source["captured_at"]),
            _timing_event_id=24,
            _publication_segment_id="seg",
            consumption=decision,
            format=doc,
            _raw_meter_reading=dict(
                reason="dial_bounds_disagree",
                state="inconsistent",
                format_id=format_id,
                source_sha256=digest,
                consistency=dict(dial_indices=[1, 2]),
            ),
        )
        reader = PhotoRegister(Saved(), Saved())
        original = reader.check(snap, inference)
        self.assertEqual(original["source"], source)
        from threading import Lock
        from types import SimpleNamespace
        from capture import Store
        from original_dials import preserve
        with TemporaryDirectory() as tmp:
            store = Store(tmp)
            recognition = SimpleNamespace(lock=Lock(), reader=SimpleNamespace(
                pipeline_id=doc["pipeline_id"],read_jpeg=lambda image:inference))
            self.assertTrue(preserve(store,recognition,reader,doc,digest,image_bytes))
            with store.connect() as db:
                db.execute("INSERT INTO frames VALUES(?,?,?,?,?,?,0)",("fixture","24",source["captured_at"],
                           source["captured_at"],digest,len(image_bytes)))
                db.execute("INSERT INTO retired_images VALUES(?,0)",(digest,))
            restored = PhotoRegister(Store(tmp), Saved())
            self.assertEqual(restored.check(snap,inference),original)
            changed = deepcopy(inference)
            changed["dial_positions"][1]["position"] += 0.01
            self.assertIsNone(restored.check(snap,changed))
            self.assertIsNone(restored.check(snap,dict(inference,profile="different calibration")))
        for path, value in (
            (("latest", "sha256"), "c" * 64),
            (("latest", "captured_at"), "later"),
            (("_publication_segment_id",), "other"),
            (("_timing_event_id",), 25),
            (("consumption", "observation_accepted"), True),
            (("consumption", "observation_context"), "new"),
            (("consumption", "observation_support", "document_observed"), [False, True, True, True]),
        ):
            copy = deepcopy(snap)
            node = copy
            for name in path[:-1]:
                node = node[name]
            node[path[-1]] = value
            self.assertIsNone(reader.check(copy, inference), path)
        self.assertIsNone(reader.check(snap, dict(inference, profile="new")))
        self.assertIsNone(
            reader.check(snap, dict(inference, event_observation=dict(source, event_id=23)))
        )
        image_bytes = b"wrong archived image"
        self.assertIsNone(reader.check(snap, inference))


class Output:
    base = "fixture"
    config = {"unique_id": "test"}
    interval = 6

    def _publish(self, topic, payload, retain):
        assert topic == "fixture/absolute_nominal" and retain
        self.last = json.loads(payload)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        fine = dict(
            event_id=10,
            source_sha256="a" * 64,
            measured_at=(self.now - timedelta(hours=3)).isoformat(),
            value_ft3="20360.4",
            bands_ft3=[[20360, 20361]],
            status="nominal",
        )
        self.record = dict(
            state=fine,
            source_identity=hashlib.sha256(b"fixture").hexdigest(),
            format_id="fmt",
            clock_id="previous",
            tick=100,
        )
        self.src = dict(
            event_id=21,
            captured_at=self.now.isoformat(),
            source_sha256="b" * 64,
            clock_id="current",
            monotonic_us=100000,
            camera="fixture",
            format_id="fmt",
        )
        self.proof = dict(
            register_ft3=20400, resolution_ft3=100, source=self.src, reference_sha256="e" * 64
        )
        self.snap = dict(
            consumption=dict(event_observation=self.src, unresolved_gap=dict(delta=None)),
            format=dict(maximum_rate_per_second=0.1),
            _photo_register=self.proof,
        )

    def project(self, prior=None):
        return photo_projection(prior, self.record, "no_qualified_reading", self.snap, self.now, 90)

    def test_monotonic_fresh_bound_projection(self):
        coarse, fresh = self.project()
        self.assertTrue(fresh)
        self.assertEqual((coarse["lower_ft3"], coarse["upper_exclusive_ft3"]), (20400, 20500))
        for field, value in (("register_ft3", 20200), ("register_ft3", 23000), ("resolution_ft3", 1)):
            old = self.proof[field]
            self.proof[field] = value
            self.assertEqual(self.project(), (None, False))
            self.proof[field] = old
        for field, value in (
            ("event_id", 8),
            ("camera", "other"),
            ("format_id", "other"),
            ("captured_at", (self.now - timedelta(minutes=3)).isoformat()),
        ):
            original = self.src[field]
            self.src[field] = value
            self.assertEqual(self.project(), (None, False))
            self.src[field] = original
        self.assertTrue(self.project({"photo_register": coarse})[1])
        self.src.update(
            event_id=22, monotonic_us=10, captured_at=(self.now + timedelta(seconds=1)).isoformat()
        )
        self.now += timedelta(seconds=1)
        self.assertEqual(self.project({"photo_register": coarse}), (coarse, False))
        self.assertIsNone(self.snap["consumption"]["unresolved_gap"]["delta"])

    def test_restart_holds_original_photo_time_and_fine_anchor(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.db"
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute(
                    "create table nominal_register(identity text primary key,record text not null)"
                )
                conn.execute(
                    "insert into nominal_register values (?,?)", ("test", json.dumps(self.record))
                )
            output = Output()
            first = AbsolutePublisher(path)
            first.publish(output, None, self.snap)
            self.assertEqual(output.last["status"], "photo_register")
            first_event = output.last["event_id"]
            first_time = output.last["measured_at"]
            restarted = AbsolutePublisher(path)
            restarted.publish(output, None, dict(self.snap, _photo_register=None))
            self.assertEqual(output.last["status"], "held_at_last_reading")
            self.assertEqual(
                (output.last["event_id"], output.last["measured_at"]), (first_event, first_time)
            )
            self.assertEqual(restarted.sent[1]["event_id"], 10)
            self.assertIsNone(self.snap["consumption"]["unresolved_gap"]["delta"])

    def test_new_fine_register_can_take_over_only_when_supported(self):
        coarse, _ = self.project()
        prior = dict(self.record, photo_register=coarse)
        record = deepcopy(self.record)
        record["state"].update(
            event_id=22, measured_at=(self.now + timedelta(seconds=2)).isoformat(), value_ft3="20399.9"
        )
        self.assertEqual(photo_projection(prior, record, None, {}, self.now, 90), (coarse, False))
        record["state"]["value_ft3"] = "20421.3"
        self.assertEqual(photo_projection(prior, record, None, {}, self.now, 90), (None, False))
