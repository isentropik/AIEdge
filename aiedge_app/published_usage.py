"""Read the acknowledged MQTT payloads without recomputing or renewing their time."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import time
from zoneinfo import ZoneInfo


def snapshot(publisher, *, now=None, wall=None):
    now = time.monotonic() if now is None else now
    wall = datetime.now(timezone.utc) if wall is None else wall
    result = {}
    for name, source in (('daily', publisher), ('recent', publisher.recent), ('resumed', getattr(publisher, 'resumed', None))):
        if source is None:
            continue
        saved = source.last_good
        if not isinstance(saved, tuple) or len(saved) < 2:
            continue
        payload, published = saved[:2]
        if not isinstance(payload, dict) or type(published) not in (int, float):
            continue
        try:
            zone = ZoneInfo(payload['timezone'])
            captured = datetime.fromisoformat(payload['through']['captured_at'])
            age = (wall-captured).total_seconds() if captured.tzinfo is not None else -1
            stale = name == 'daily' and payload.get('status') == 'stale'
            if age < 0 or (age >= 660 and not stale):
                continue
            if not 0 <= now-published < 660 or os.environ.get('TZ') != zone.key:
                continue
            if name == 'daily' and payload['day'] != wall.astimezone(zone).date().isoformat():
                continue
            if stale and captured.astimezone(zone).date().isoformat() != payload['day']:
                continue
            result[name] = deepcopy(payload)
        except (KeyError, TypeError, ValueError):
            continue
    return result
