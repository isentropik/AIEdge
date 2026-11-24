"""Read Supervisor-owned options without rewriting them or exposing secrets."""
import json
from pathlib import Path
from capture import Camera

MAX_OPTIONS = 65536
MIN_CAPTURE_INTERVAL_SECONDS = 10
DEFAULTS = dict(camera_url='', camera_token='', camera_username='', camera_password='',
                capture_enabled=False, mqtt_enabled=False, mqtt_output_mode='reading', interval_seconds=30,
                recognition_mode='FULL',event_selection_policy={},daily_evidence_policy={},
                meter_history_entity='sensor.aiedge_gas_meter_reading',
                nominal_history_entity='sensor.aiedge_gas_used_today_nominal_estimate',
                daily_history_entity='sensor.aiedge_gas_used_today',recent_history_entity='sensor.aiedge_gas_used_last_hour')

class InvalidOptions(ValueError):
    def __init__(self, code, field=None):
        self.code, self.field = code, field
        super().__init__(code)

def split_capture_schedule(options):
    """Use a separate photo interval without changing the reader or in-flight photo identity."""
    source_options = options.copy()
    fallback = max(MIN_CAPTURE_INTERVAL_SECONDS, source_options['interval_seconds'])
    interval = source_options.pop('capture_interval_seconds', fallback)
    return interval, source_options


def validate(document):
    if not isinstance(document, dict):
        raise InvalidOptions('options_invalid')
    if any(key not in DEFAULTS and key != 'capture_interval_seconds' for key in document):
        raise InvalidOptions('options_unknown_field')
    options = DEFAULTS | document
    from daily_empirical import validate as validate_daily_policy
    try: validate_daily_policy(options['daily_evidence_policy'])
    except (ValueError, TypeError, ArithmeticError): raise InvalidOptions('options_daily_policy_invalid') from None
    for field in ('capture_enabled', 'mqtt_enabled'):
        if type(options[field]) is not bool:
            raise InvalidOptions('options_invalid_field', field)
    from mqtt_consumption import MODES
    if options['mqtt_output_mode'] not in MODES:
        raise InvalidOptions('options_invalid_field', 'mqtt_output_mode')
    interval = options['interval_seconds']
    if type(interval) is not int or not 6 <= interval <= 3600:
        raise InvalidOptions('options_invalid_field', 'interval_seconds')
    if 'capture_interval_seconds' in options:
        scheduled = options['capture_interval_seconds']
        if type(scheduled) is not int or not MIN_CAPTURE_INTERVAL_SECONDS <= scheduled <= 3600:
            raise InvalidOptions('options_invalid_field', 'capture_interval_seconds')
    from event_mode import validate_options
    try:validate_options(options['recognition_mode'],options['event_selection_policy'],interval)
    except (ValueError,TypeError):raise InvalidOptions('options_event_policy_invalid') from None
    for field in ('camera_url', 'camera_token', 'camera_username', 'camera_password'):
        value = options[field]
        if not isinstance(value, str) or len(value) > 4096:
            raise InvalidOptions('options_invalid_field', field)
    if options['capture_enabled'] and not options['camera_url']:
        raise InvalidOptions('options_camera_address_required', 'camera_url')
    # Validate before starting either outbound worker, even if capture is disabled.
    try:
        Camera(options['camera_url'] or 'http://localhost', options['camera_token'],
               options['camera_username'], options['camera_password'])
    except (ValueError, TypeError, UnicodeError):
        raise InvalidOptions('options_camera_invalid') from None
    return options


def load(directory):
    path = Path(directory) / 'options.json'
    try:
        try:
            with path.open('rb') as stream:
                body = stream.read(MAX_OPTIONS + 1)
        except FileNotFoundError:
            return DEFAULTS.copy(), {'state': 'ready'}
        if len(body) > MAX_OPTIONS:
            raise InvalidOptions('options_too_large')
        def unique_pairs(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    from event_mode import FIELDS
                    if key in FIELDS|{'recognition_mode','event_selection_policy'}:raise InvalidOptions('options_event_policy_invalid')
                    raise InvalidOptions('options_duplicate_field')
                value[key] = item
            return value
        document = json.loads(body, object_pairs_hook=unique_pairs)
        return validate(document), {'state': 'ready'}
    except InvalidOptions as exc:
        state = {'state': 'invalid', 'code': exc.code}
        if exc.field:
            state['field'] = exc.field
    except (ValueError, UnicodeError, RecursionError):
        state = {'state': 'invalid', 'code': 'options_invalid'}
    except OSError:
        state = {'state': 'invalid', 'code': 'options_unreadable'}
    # Never persist defaults over an invalid file, nor publish part of its contents.
    return DEFAULTS.copy(), state
