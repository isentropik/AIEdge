"""Capture-clock provenance; never estimates elapsed time from arrival or frame IDs."""
import re
from datetime import datetime

MAX_TICK=9223372036854775807
CLOCK_HEADER='X-AIEdge-Clock-Id'
TICK_HEADER='X-AIEdge-Capture-Monotonic-Us'

def parse(headers):
    """Optional for recognition, paired and immutable when supplied."""
    values=[]
    for name in (CLOCK_HEADER,TICK_HEADER):
        entries=headers.get_all(name) if hasattr(headers,'get_all') else ([headers[name]] if name in headers else [])
        if entries and len(entries)!=1:raise ValueError('duplicate_capture_clock_header')
        values.append(entries[0] if entries else None)
    clock,tick=values
    if clock is None and tick is None:return None
    if clock is None or tick is None:raise ValueError('incomplete_capture_clock')
    if not isinstance(clock,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',clock):raise ValueError('invalid_capture_clock_id')
    if not isinstance(tick,str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}',tick):raise ValueError('invalid_capture_clock_tick')
    tick=int(tick)
    if tick>MAX_TICK:raise ValueError('invalid_capture_clock_tick')
    return clock,tick

def interval(previous,current):
    """Conservative timing gate only, not proof of complete rotations or accuracy.

    Clock IDs must identify a monotonic-clock epoch and change on every reset.
    UTC agreement allows 250 ms plus 200 ppm of elapsed time for clock slewing.
    A changed clock or excessive UTC step requires a new accounting anchor.
    """
    result={'state':'unavailable','reason':'capture_clock_missing','elapsed_seconds':None}
    if current is None:return result
    if previous is None:return {**result,'reason':'capture_clock_anchor_missing'}
    if previous.get('camera')!=current.get('camera'):return {**result,'reason':'capture_camera_changed'}
    if any(row.get('clock_id') is None or row.get('monotonic_us') is None for row in (previous,current)):return result
    if any(not isinstance(row['clock_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',row['clock_id']) for row in (previous,current)):
        return {**result,'reason':'capture_clock_invalid'}
    if previous['clock_id']!=current['clock_id']:return {**result,'reason':'capture_clock_changed'}
    ticks=[row['monotonic_us'] for row in (previous,current)]
    if any(type(t) is not int or not 0<=t<=MAX_TICK for t in ticks):return {**result,'reason':'capture_clock_invalid'}
    elapsed=ticks[1]-ticks[0]
    if elapsed<=0:return {**result,'reason':'capture_clock_not_increasing'}
    try:
        stamps=[datetime.fromisoformat(row['captured_at'].replace('Z','+00:00')) for row in (previous,current)]
        if any(stamp.tzinfo is None for stamp in stamps):raise ValueError()
        delta=stamps[1]-stamps[0]
        utc_us=(delta.days*86400+delta.seconds)*1000000+delta.microseconds
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return {**result,'reason':'capture_clock_invalid'}
    if utc_us<=0 or abs(utc_us-elapsed)>250000+elapsed//5000:
        return {**result,'reason':'capture_clock_utc_discontinuity'}
    return {'state':'continuous','reason':None,'elapsed_seconds':elapsed/1000000}
