"""Publish a calendar-day range with the original measurement time and endpoint identities."""
import json
import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from daily_records import daily_records
from daily_range import daily_range
from mqtt_consumption import fresh_range


class DailyPublisher:
    def __init__(self, store):
        self.store = store
        self.reset()

    def reset(self):
        self.configured = False
        self.key = None
        self.next_refresh = 0
        self.last_good = None

    def _retain_pending(self, snapshot, today, zone, now):
        previous = self.last_good
        if not previous or snapshot.get("_daily_publication_pending") is not True:
            return False
        payload, published_at, document = previous
        # Keep the original label/time only. Never republish it to renew HA expiry,
        # borrow a newer timestamp, or bridge a failed/unclassified capture.
        return (0 <= now - published_at < 660 and payload["day"] == today.isoformat()
                and payload["timezone"] == zone.key and snapshot.get("format") == document
                and snapshot.get("_publication_segment_id") == payload["segment_id"])

    def publish(self, output, snapshot):
        if (snapshot.get("format") or {}).get("unit") != "ft3":
            if self.last_good:
                output._publish(output.base + "/daily_range", "{}")
                self.reset()
            return
        topic = output.base + "/daily_range"
        if not self.configured:
            uid = output.config["unique_id"] + "_daily_range"
            config = dict(name="Gas used today", unique_id=uid, device=output.config["device"],
                          state_topic=topic, json_attributes_topic=topic, expire_after=660,
                          value_template="{{ value_json.label | default('unknown') }}",
                          availability_topic=topic,
                          availability_template="{{ 'online' if value_json.label is defined else 'offline' }}")
            output._publish("homeassistant/sensor/" + uid + "/config", json.dumps(config), True)
            self.configured = True
        obs = fresh_range(snapshot, max(90, output.interval * 3))
        payload = {}
        now = time.monotonic()
        key = None
        try:
            zone = ZoneInfo(os.environ["TZ"])
            today = datetime.now(zone).date()
            if obs is None and self._retain_pending(snapshot, today, zone, now):
                return
            if obs and datetime.fromisoformat(obs["captured_at"]).astimezone(zone).date() == today:
                key = (today, zone.key, obs["format_id"], obs["segment_id"])
                if self.key in (key, ("offline", key)) and now < self.next_refresh:
                    return
                event = obs["event_id"]
                with self.store.connect() as db:
                    contexts = {context: (pipeline, format_id, first_event)
                                for context, pipeline, format_id, first_event in db.execute(
                                    "SELECT context,pipeline,format_id,first_event FROM event_selection_contexts")}
                    rows = daily_records(db, max(1, event - 32768), event, obs["segment_id"])
                    result = daily_range(rows, today, zone, snapshot["format"], obs["format_id"], contexts)
                end = result["through"]
                if any(end[k] != obs[k] for k in ("event_id", "source_sha256", "captured_at", "format_id")):
                    raise ValueError("daily endpoint changed")
                if result["segment_id"] != obs["segment_id"]:
                    raise ValueError("daily endpoint segment changed")
                payload = dict(result, timezone=zone.key,
                               label=result["lower"] + "–" + result["upper"] + " ft³")
        except (ValueError, ArithmeticError, KeyError, TypeError, sqlite3.Error, ZoneInfoNotFoundError):
            pass
        if not payload and self.key == ("offline", key) and now < self.next_refresh:
            return
        output._publish(topic, json.dumps(payload, allow_nan=False))
        from copy import deepcopy
        self.last_good = (deepcopy(payload), now, deepcopy(snapshot["format"])) if payload else None
        self.key = key if payload else ("offline", key)
        self.next_refresh = now + (300 if payload else 30)


