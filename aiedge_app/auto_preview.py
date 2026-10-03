"""Temporary-capture wire contract; require advertised support before use.

Pure validation only. No HTTP, setting changes, SD writes or automatic retries.
The client must reject an unsupported contract before taking any shot,
and block other captures after an uncertain restore until recovery is verified.
"""
import hashlib, json, re

from auto_capture import Choice
from capture import camera_header


def capabilities(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1 \
            or value.get('model') != 'OV2640' or value.get('mode') != 'remote-camera' \
            or value.get('path') != '/api/v1/capture/temporary' or value.get('method') != 'POST' \
            or type(value.get('frame_size')) is not list or value['frame_size'] != [640, 480] \
            or any(type(v) is not int for v in value['frame_size']) \
            or value.get('temporary_controls') is not True or value.get('restore_before_response') is not True \
            or type(value.get('sd_writes')) is not int or value['sd_writes'] != 0 \
            or type(value.get('max_capture_seconds')) is not int or value['max_capture_seconds'] != 20:
        raise ValueError('auto_contract_unsupported')
    return {key: value[key] for key in ('version', 'model', 'mode', 'path', 'method', 'frame_size',
                                       'temporary_controls', 'restore_before_response', 'sd_writes',
                                       'max_capture_seconds')}


def request(choice, orientation, revision, request_id):
    if not isinstance(choice, Choice) or not isinstance(revision, str) or not re.fullmatch('[a-f0-9]{64}', revision) \
            or not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
        raise ValueError('auto_choice_invalid')
    value = dict(version=1, base_revision=revision, request_id=request_id,
                 intensity=choice.intensity, controls=choice.controls(orientation))
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def receipt(headers, body, revision):
    """Every reply must bind the exact request and prove saved-state restoration.

    Image hash, capture time/clock and orientation are validated separately by
    auto_capture. A transport error or missing restoration receipt is uncertain;
    callers cannot infer success from a later ping or blindly retry the shot.
    """
    if not isinstance(body, bytes) or len(body) > 2048 or not isinstance(revision, str) \
            or not re.fullmatch('[a-f0-9]{64}', revision):
        raise ValueError('auto_receipt_unverified')
    try:
        if camera_header(headers, 'X-AIEdge-Temporary-Request-SHA256') != hashlib.sha256(body).hexdigest():
            raise ValueError('auto_receipt_unverified')
        if camera_header(headers, 'X-AIEdge-Saved-Revision') != revision:
            raise ValueError('auto_config_conflict')
        if camera_header(headers, 'X-AIEdge-Restored-Revision') != revision \
                or camera_header(headers, 'X-AIEdge-Settings-Restored') != 'true' \
                or camera_header(headers, 'X-AIEdge-Light-Off') != 'true' \
                or camera_header(headers, 'X-AIEdge-Temporary-SD-Writes') != '0':
            raise ValueError('auto_restore_unverified')
    except ValueError as error:
        if str(error) in ('duplicate_camera_header', 'invalid_camera_header'):
            raise ValueError('auto_receipt_unverified') from None
        raise
