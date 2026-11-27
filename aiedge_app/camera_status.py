"""Strict passive camera admission snapshot. Does not acquire a frame."""
import errno,http.client,json,re,ssl,time,urllib.error,urllib.request

READINESS_IO_SECONDS = 10
FAST_HEADER_SECONDS = 2

class ReadinessTransportError(ValueError):
    """A failed passive GET; no capture request was admitted by this probe."""
    def __init__(self, stage=None, cause=None):
        super().__init__('camera_connection_failed')
        self.stage = stage
        self.cause = type(cause).__name__
        self.os_error = getattr(cause,'errno',None)
        self.header_timeout = stage=='connect_or_headers' and isinstance(cause,TimeoutError)

def transient_transport(error):
    reason=error.reason if isinstance(error,urllib.error.URLError) else error
    if isinstance(reason,ssl.SSLError):return False
    return isinstance(reason,(TimeoutError,ConnectionError)) or (
        isinstance(reason,OSError) and reason.errno in (
            errno.ETIMEDOUT,errno.ECONNREFUSED,errno.ECONNRESET,
            errno.ECONNABORTED,errno.ENETUNREACH,errno.EHOSTUNREACH,errno.EPIPE))

FIELDS=('protocol_version','mode','state','camera_available','settings_ready',
        'clock_synchronized','capture_path','capture_method','capture_clock_metadata','image_sha256')
STATES={'ready','busy','camera_unavailable','settings_unavailable','clock_unsynchronized','demo_mode','startup_recovery'}

def unique_object(entries):
    result={}
    for key,value in entries:
        if key in result:raise ValueError('camera_status_invalid')
        result[key]=value
    return result

def validate(payload):
    if not isinstance(payload,dict) or not set(FIELDS)<=payload.keys():raise ValueError('camera_status_invalid')
    if type(payload['protocol_version']) is not int or payload['protocol_version']!=1:
        raise ValueError('camera_protocol_unsupported')
    if type(payload['mode']) is not str or type(payload['state']) is not str or payload['mode'] not in ('remote-camera','full-reader') or payload['state'] not in STATES:
        raise ValueError('camera_status_invalid')
    if payload['capture_path']!='/api/v1/capture' or payload['capture_method']!='POST':
        raise ValueError('camera_protocol_unsupported')
    if any(type(payload[k]) is not bool for k in ('settings_ready','clock_synchronized','capture_clock_metadata','image_sha256')):
        raise ValueError('camera_status_invalid')
    if not payload['capture_clock_metadata'] or not payload['image_sha256']:raise ValueError('camera_protocol_unsupported')
    available=payload['camera_available']
    if available is not None and type(available) is not bool:raise ValueError('camera_status_invalid')
    if available is None and payload['state']!='busy':raise ValueError('camera_status_invalid')
    if payload['state']=='ready' and not (available and payload['settings_ready'] and payload['clock_synchronized']):
        raise ValueError('camera_status_invalid')
    # Never echo unsolicited fields, device addresses or credential-like payloads.
    result={k:payload[k] for k in FIELDS}
    profile = payload.get('q25_profile')
    if payload.get('q25') is True and isinstance(profile,str) and re.fullmatch('[0-9a-f]{64}',profile):
        result.update(q25=True,q25_profile=profile)
    return result

def probe(camera,*,deadline=None,scheduled_stop=None):
    from capture import io_deadline
    from lifecycle import lifecycle_event
    absolute = io_deadline(READINESS_IO_SECONDS,deadline)
    fast = scheduled_stop is not None and camera.fast_readiness
    attempts = 3 if fast else 1
    for attempt in range(1,attempts+1):
        started = time.monotonic()
        header_deadline = min(absolute,started+FAST_HEADER_SECONDS) if attempt<attempts else absolute
        try:
            result = _get_status(camera,header_deadline,absolute)
        except ReadinessTransportError as error:
            retry = (attempt<attempts and error.header_timeout and
                     time.monotonic()<absolute and not scheduled_stop.is_set())
            event = 'camera_readiness_retry' if retry else 'camera_readiness_transport'
            lifecycle_event(event,stage=error.stage,cause=error.cause,os_error=error.os_error,attempt=attempt)
            if retry:
                continue
            if scheduled_stop is not None:
                # Give a persistently slow camera an uninterrupted full window next time.
                camera.fast_readiness = False
            raise
        if scheduled_stop is not None:
            camera.fast_readiness = result['state']=='ready' and time.monotonic()-started < FAST_HEADER_SECONDS
        return result

def _get_status(camera,header_deadline,absolute):
    from capture import camera_header
    headers={}
    if camera.token:headers['Authorization']='Bearer '+camera.token
    elif camera.basic:headers['Authorization']='Basic '+camera.basic
    request=urllib.request.Request(camera.origin+'/api/v1/camera',headers=headers,method='GET')
    request.aiedge_deadline=header_deadline
    stage='connect_or_headers'
    try:
        remaining=header_deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('camera_readiness_deadline')
        with camera.opener.open(request,timeout=remaining) as response:
            stage='status_body'
            if header_deadline<absolute:response.set_body_deadline(absolute)
            camera_header(response.headers,'Content-Type')
            raw_length=camera_header(response.headers,'Content-Length')
            if response.status!=200 or response.headers.get_content_type()!='application/json':raise ValueError('camera_status_invalid')
            if not 1<=len(raw_length)<=4 or not raw_length.isascii() or not raw_length.isdecimal() or not 1<=int(raw_length)<=4096 or response.headers.get_all('Transfer-Encoding'):
                raise ValueError('camera_status_invalid')
            body=response.read(int(raw_length))
            if len(body)!=int(raw_length):raise ValueError('camera_status_invalid')
            return validate(json.loads(body,object_pairs_hook=unique_object))
    except urllib.error.HTTPError as exc:
        code={401:'camera_authentication_failed',403:'camera_authentication_failed',
              404:'camera_api_unavailable',405:'camera_api_unavailable'}.get(exc.code,'camera_http_error')
        exc.close();raise ValueError(code) from None
    except (urllib.error.URLError,OSError) as error:
        if transient_transport(error):
            cause=error.reason if isinstance(error,urllib.error.URLError) else error
            raise ReadinessTransportError(stage,cause) from None
        raise ValueError('camera_connection_failed') from None
    except (UnicodeError,json.JSONDecodeError,TypeError,RecursionError,http.client.HTTPException):raise ValueError('camera_status_invalid') from None
