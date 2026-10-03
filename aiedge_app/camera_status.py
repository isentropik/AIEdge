"""Strict passive camera admission snapshot. Does not acquire a frame."""
import http.client,json,time,urllib.error,urllib.request

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
    return {k:payload[k] for k in FIELDS}

def probe(camera,*,deadline=None):
    from capture import camera_header,io_deadline
    absolute=io_deadline(5,deadline)
    headers={}
    if camera.token:headers['Authorization']='Bearer '+camera.token
    elif camera.basic:headers['Authorization']='Basic '+camera.basic
    request=urllib.request.Request(camera.origin+'/api/v1/camera',headers=headers,method='GET')
    request.aiedge_deadline=absolute
    try:
        with camera.opener.open(request,timeout=5) as response:
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
    except (urllib.error.URLError,OSError):raise ValueError('camera_connection_failed') from None
    except (UnicodeError,json.JSONDecodeError,TypeError,RecursionError,http.client.HTTPException):raise ValueError('camera_status_invalid') from None
