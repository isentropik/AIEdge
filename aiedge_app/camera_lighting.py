"""Bounded, explicit lighting transactions against the existing camera handlers.

The original configuration stays in server memory. Only lighting fields reach
the browser. A write intent survives app restart; uncertain activation blocks
new captures until the user loads and explicitly applies the saved settings.
"""
import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from durable_file import sync_directory

LIMIT = 65536  # /config-save JSON embeds both versions within its 160 KiB limit.
PINS = (0, 1, 3, 4, 12, 13)
TYPES = ('WS2812', 'WS2812B', 'SK6812', 'SK6812_RGBW', 'WS2813')
LIGHT_MODES = ('built-in-led', 'external-flash-ws281x')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('camera_lighting_response_invalid')
        result[key] = value
    return result


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('camera_lighting_choice_invalid')
    return value


def capabilities(data):
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('camera_lighting_unsupported')
    pins = data.get('pins')
    if not isinstance(pins, list) or len(pins) != len(PINS):
        raise ValueError('camera_lighting_response_invalid')
    result = []
    for pin in pins:
        if not isinstance(pin, dict) or type(pin.get('pin')) is not int or pin['pin'] not in PINS or type(pin.get('available')) is not bool:
            raise ValueError('camera_lighting_response_invalid')
        # Do not echo arbitrary firmware text or unsolicited fields.
        result.append({'pin': pin['pin'], 'available': pin['available']})
    if {p['pin'] for p in result} != set(PINS) or type(data.get('builtin_pin')) is not int or data['builtin_pin'] not in PINS:
        raise ValueError('camera_lighting_response_invalid')
    return {'builtin_pin': data['builtin_pin'], 'pins': result}


class Config:
    """Edit individual values, preserving every unrelated byte and comment."""
    def __init__(self, raw):
        if not 1 <= len(raw) <= LIMIT or b'\0' in raw:
            raise ValueError('camera_lighting_config_unsupported')
        try:
            self.lines = raw.decode('utf-8').splitlines(keepends=True)
        except UnicodeError:
            raise ValueError('camera_lighting_config_unsupported') from None
        self.raw, self.fields = raw, {}
        self.gpio_end = len(self.lines)
        section = None
        sections = set()
        for index, line in enumerate(self.lines):
            stripped = line.strip()
            if stripped.startswith('[') or stripped.startswith(';['):
                if section == '[GPIO]':
                    self.gpio_end = index
                section = stripped if stripped in ('[GPIO]', '[TakeImage]') else None
                if section:
                    if section in sections:
                        raise ValueError('camera_lighting_config_unsupported')
                    sections.add(section)
                continue
            if not section or stripped.startswith((';', '#')):
                continue
            match = re.fullmatch(r'([ \t]*)([^=\r\n]+?)([ \t]*=[ \t]*)([^\r\n]*)(\r?\n)?', line)
            if not match:
                continue
            key = match[2].strip().upper()
            relevant = key == 'LEDINTENSITY' if section == '[TakeImage]' else key in ('LEDTYPE', 'LEDNUMBERS', 'LEDCOLOR') or key.startswith('IO')
            if not relevant:
                continue
            address = (section, key)
            if address in self.fields:
                raise ValueError('camera_lighting_config_unsupported')
            value = re.split('[;#]', match[4], maxsplit=1)[0].strip()
            self.fields[address] = (index, match, value)
        if sections != {'[GPIO]', '[TakeImage]'}:
            raise ValueError('camera_lighting_config_unsupported')

    def get(self, section, key):
        try:
            return self.fields[(section, key)][2]
        except KeyError:
            raise ValueError('camera_lighting_config_unsupported') from None

    def lighting(self):
        routes = []
        for (section, key), (_, _, value) in self.fields.items():
            if section != '[GPIO]' or not key.startswith('IO'):
                continue
            fields = value.split()
            if fields and fields[0] == 'external-flash-pwm':
                raise ValueError('camera_lighting_config_unsupported')
            if fields and fields[0] in LIGHT_MODES:
                if not key[2:].isascii() or not key[2:].isdecimal() or int(key[2:]) not in PINS or len(fields) < 2 or fields[1] != 'disabled':
                    raise ValueError('camera_lighting_config_unsupported')
                routes.append((int(key[2:]), fields[0]))
        if len(routes) != 1:
            raise ValueError('camera_lighting_config_unsupported')
        try:
            intensity_text = self.get('[TakeImage]', 'LEDINTENSITY')
            if not re.fullmatch('[0-9]{1,3}', intensity_text):
                raise ValueError()
            intensity = integer(int(intensity_text), 0, 100)
            kind = self.get('[GPIO]', 'LEDTYPE')
            count_text = self.get('[GPIO]', 'LEDNUMBERS')
            if not re.fullmatch('[0-9]{1,6}', count_text):
                raise ValueError()
            count = integer(int(count_text), 1, 100000)
            tokens = self.get('[GPIO]', 'LEDCOLOR').split()
            if len(tokens) not in (3, 4) or any(not re.fullmatch('[0-9]{1,3}', t) for t in tokens):
                raise ValueError()
            channels = [integer(int(t), 0, 255) for t in tokens]
            if len(channels) == 3:
                channels.append(0)
            if kind not in TYPES or (kind != 'SK6812_RGBW' and channels[3]):
                raise ValueError()
        except ValueError:
            raise ValueError('camera_lighting_config_unsupported') from None
        return {'source': 'strip' if routes[0][1] == LIGHT_MODES[1] else 'builtin',
                'pin': routes[0][0], 'type': kind, 'count': count,
                'channels': channels, 'intensity': intensity}

    def plan(self, choice, pins):
        before = self.lighting()
        if not isinstance(choice, dict) or set(choice) != set(before):
            raise ValueError('camera_lighting_choice_invalid')
        if choice['source'] not in ('builtin', 'strip') or choice['type'] not in TYPES:
            raise ValueError('camera_lighting_choice_invalid')
        pin = integer(choice['pin'], 0, 39)
        integer(choice['count'], 1, 100000)
        integer(choice['intensity'], 0, 100)
        channels = choice['channels']
        if not isinstance(channels, list) or len(channels) != 4:
            raise ValueError('camera_lighting_choice_invalid')
        for value in channels:
            integer(value, 0, 255)
        if choice['type'] != 'SK6812_RGBW' and channels[3]:
            raise ValueError('camera_lighting_choice_invalid')
        if choice['source'] == 'builtin' and pin != pins['builtin_pin']:
            raise ValueError('camera_lighting_pin_unavailable')
        if not any(p['pin'] == pin and p['available'] for p in pins['pins']):
            raise ValueError('camera_lighting_pin_unavailable')
        if choice == before:
            return self.raw
        changes = {}
        target_key = ('[GPIO]', 'IO' + str(pin))
        target = self.fields[target_key][2].split() if target_key in self.fields else ['disabled','disabled','10','false','false','lighting']
        if not target or target[0] not in ('disabled', *LIGHT_MODES) or len(target) < 2 or target[1] != 'disabled':
            raise ValueError('camera_lighting_pin_unavailable')
        if before['pin'] != pin:
            old = self.get('[GPIO]', 'IO' + str(before['pin'])).split()
            old[0] = 'disabled'
            changes[('[GPIO]', 'IO' + str(before['pin']))] = ' '.join(old)
        if before['source'] != choice['source'] or before['pin'] != pin:
            target[0] = LIGHT_MODES[choice['source'] == 'strip']
            changes[('[GPIO]', 'IO' + str(pin))] = ' '.join(target)
        for key, value in (('LEDTYPE', choice['type']), ('LEDNUMBERS', str(choice['count'])), ('LEDCOLOR', ' '.join(map(str, channels)))):
            if choice[{'LEDTYPE':'type', 'LEDNUMBERS':'count', 'LEDCOLOR':'channels'}[key]] != before[{'LEDTYPE':'type', 'LEDNUMBERS':'count', 'LEDCOLOR':'channels'}[key]]:
                changes[('[GPIO]', key)] = value
        if choice['intensity'] != before['intensity']:
            changes[('[TakeImage]', 'LEDINTENSITY')] = str(choice['intensity'])
        lines = self.lines.copy()
        for key, value in changes.items():
            if key not in self.fields:
                # A free user-selected GPIO may only have a commented example.
                # Keep that example and add one explicit active lighting route.
                ending = '\r\n' if b'\r\n' in self.raw else '\n'
                if self.gpio_end and not lines[self.gpio_end-1].endswith(('\r','\n')):
                    lines[self.gpio_end-1] += ending
                lines.insert(self.gpio_end,key[1]+' = '+value+ending)
                continue
            index, match, old = self.fields[key]
            if old == value:
                continue
            tail = match[4][len(match[4].rstrip()):]
            comment = re.search(r'[ \t]*[;#].*', match[4])
            if comment:
                tail = comment[0]
            lines[index] = match[1] + match[2] + match[3] + value + tail + (match[5] or '')
        raw = ''.join(lines).encode('utf-8')
        if len(raw) > LIMIT or Config(raw).lighting() != choice:
            raise ValueError('camera_lighting_choice_invalid')
        return raw


class CameraLighting:
    def __init__(self, camera, directory):
        self.camera, self.lock = camera, threading.Lock()
        self.path = Path(directory) / 'camera-lighting-operation.json'
        self.pending = None
        self.storage_error = False
        try:
            if self.path.exists():
                with self.path.open('rb') as stream:
                    raw = stream.read(4097)
                data = json.loads(raw)
                if len(raw) > 4096 or set(data) != {'version', 'before', 'after'} or data['version'] != 1 or any(not isinstance(data[k], str) or not re.fullmatch('[0-9a-f]{64}', data[k]) for k in ('before', 'after')):
                    raise ValueError()
                self.pending = data
        except (OSError, ValueError, TypeError, UnicodeError):
            self.storage_error = True

    def require_capture(self):
        with self.lock:
            if self.pending or self.storage_error:
                raise ValueError('camera_lighting_unverified')

    def needs_attention(self):
        with self.lock:
            return bool(self.pending or self.storage_error)

    def _intent(self, before, after):
        data = {'version': 1, 'before': digest(before), 'after': digest(after)}
        # Fail closed even when local intent storage cannot be completed.
        with self.lock:
            self.pending = data
        temp = self.path.with_name(uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('xb') as stream:
                stream.write(json.dumps(data).encode('ascii'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            sync_directory(self.path.parent)
        except OSError:
            self.storage_error = True
            raise ValueError('camera_lighting_storage_unavailable') from None
        finally:
            if temp.exists():
                temp.unlink()

    def _clear(self):
        try:
            self.path.unlink()
            sync_directory(self.path.parent)
        except OSError:
            self.storage_error = True
            raise ValueError('camera_lighting_storage_unavailable') from None
        with self.lock:
            self.pending = None

    def _request(self, path, deadline, data=None, kind='application/json', json_response=True):
        headers = {'Cache-Control': 'no-cache'}
        if self.camera.token:
            headers['Authorization'] = 'Bearer ' + self.camera.token
        elif self.camera.basic:
            headers['Authorization'] = 'Basic ' + self.camera.basic
        if data is not None:
            headers['Content-Type'] = kind
        request = urllib.request.Request(self.camera.origin + path, headers=headers, data=data, method='GET' if data is None else 'POST')
        request.aiedge_deadline = deadline
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            with self.camera.opener.open(request, timeout=min(5, deadline-time.monotonic())) as response:
                if response.status != 200 or (json_response and response.headers.get_content_type() != 'application/json'):
                    raise ValueError('camera_lighting_response_invalid')
                maximum = 4096 if json_response else LIMIT
                lengths = response.headers.get_all('Content-Length') or []
                encodings = response.headers.get_all('Transfer-Encoding') or []
                if len(lengths)>1 or len(encodings)>1 or (lengths and encodings) or (encodings and encodings[0].lower()!='chunked'):
                    raise ValueError('camera_lighting_response_invalid')
                if lengths and (not re.fullmatch('[0-9]{1,6}',lengths[0]) or not 1<=int(lengths[0])<=maximum):
                    raise ValueError('camera_lighting_response_invalid')
                body = response.read(maximum+1)
                if len(body) > maximum or (lengths and len(body)!=int(lengths[0])):
                    raise ValueError('camera_lighting_response_invalid')
                if json_response:
                    return json.loads(body, object_pairs_hook=unique)
                return body
        except urllib.error.HTTPError as error:
            code = {401:'camera_authentication_failed', 403:'camera_authentication_failed',
                    404:'camera_lighting_unsupported', 405:'camera_lighting_unsupported',
                    409:'camera_lighting_conflict', 429:'camera_busy', 503:'camera_busy'}.get(error.code, 'camera_lighting_rejected')
            error.close()
            raise ValueError(code) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise ValueError('camera_lighting_connection_failed') from None
        except (UnicodeError, json.JSONDecodeError, TypeError, RecursionError):
            raise ValueError('camera_lighting_response_invalid') from None

    def load(self):
        deadline = time.monotonic()+15
        pins = capabilities(self._request('/lighting-capabilities', deadline))
        sensor = self._request('/camera_capabilities', deadline)
        if not isinstance(sensor, dict) or sensor.get('model') not in ('OV2640', 'OV3660', 'OV5640', 'unknown'):
            raise ValueError('camera_lighting_response_invalid')
        raw = self._request('/fileserver/config/config.ini', deadline, json_response=False)
        return {'revision': digest(raw), 'lighting': Config(raw).lighting(),
                'capabilities': pins, 'sensor': sensor['model'],
                'needs_activation': self.needs_attention(), 'active_verified': False}

    def apply(self, revision, choice):
        if self.storage_error:
            raise ValueError('camera_lighting_storage_unavailable')
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
            raise ValueError('camera_lighting_choice_invalid')
        deadline = time.monotonic()+20
        pins = capabilities(self._request('/lighting-capabilities', deadline))
        before = self._request('/fileserver/config/config.ini', deadline, json_response=False)
        if digest(before) != revision:
            raise ValueError('camera_lighting_conflict')
        after = Config(before).plan(choice, pins)
        if after == before and not self.needs_attention():
            return {'revision': revision, 'lighting': choice, 'capabilities': pins,
                    'saved': True, 'changed': False, 'active_verified': False,
                    'needs_activation': False}
        if self.camera.readiness().get('state') != 'ready':
            raise ValueError('camera_not_ready')
        payload = json.dumps({'before': before.decode('utf-8'), 'after': after.decode('utf-8')}, ensure_ascii=False).encode('utf-8')
        if len(payload) > 160*1024:
            raise ValueError('camera_lighting_config_unsupported')
        self._intent(before, after)
        if after != before:
            result = self._request('/config-save', deadline, payload)
            if not isinstance(result, dict) or result.get('saved') is not True:
                raise ValueError('camera_lighting_save_unverified')
            if self._request('/fileserver/config/config.ini', deadline, json_response=False) != after:
                raise ValueError('camera_lighting_save_unverified')
        result = self._request('/apply-lighting', deadline, after, 'text/plain; charset=utf-8')
        if not isinstance(result, dict) or result.get('saved') is not True or result.get('active') is not True or result.get('restart_required') is not False:
            raise ValueError('camera_lighting_activation_unverified')
        if self._request('/fileserver/config/config.ini', deadline, json_response=False) != after:
            raise ValueError('camera_lighting_conflict')
        self._clear()
        return {'revision': digest(after), 'lighting': choice, 'capabilities': pins,
                'saved': True, 'changed': after != before, 'active_verified': True,
                'needs_activation': False}
