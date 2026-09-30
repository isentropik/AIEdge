"""Separate accounting ABI; does not change recognition/calibration fingerprints."""
import ctypes,hashlib,math,threading,weakref
from reading_format import finite_number,validate
from pathlib import Path

STATES={0:'invalid',1:'review',2:'ambiguous',3:'within_noise',4:'bounded',5:'estimated'}
class Result(ctypes.Structure):
    _fields_=[('available',ctypes.c_int),('current',ctypes.c_int),('status',ctypes.c_int),('accepted',ctypes.c_int),
              ('anchor_us',ctypes.c_int64),('through_us',ctypes.c_int64),('minimum',ctypes.c_double),('maximum',ctypes.c_double),('estimate',ctypes.c_double)]

class AccountingNative:
    def __init__(self,path):
        path=Path(path).resolve();self.identity=hashlib.sha256(path.read_bytes()).hexdigest();self.lib=ctypes.CDLL(str(path))
        self.lib.aiedge_accounting_abi.restype=ctypes.c_int
        if self.lib.aiedge_accounting_abi()!=1:raise ValueError('unsupported_accounting_abi')
        self.lib.aiedge_accounting_create.argtypes=[ctypes.POINTER(ctypes.c_double)]*2+[ctypes.c_size_t,ctypes.c_int,ctypes.c_double]
        self.lib.aiedge_accounting_create.restype=ctypes.c_void_p
        self.lib.aiedge_accounting_destroy.argtypes=[ctypes.c_void_p];self.lib.aiedge_accounting_destroy.restype=None
        self.lib.aiedge_accounting_observe.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_double),ctypes.c_size_t,ctypes.c_int64,ctypes.c_char_p,ctypes.c_size_t,ctypes.POINTER(Result)]
        self.lib.aiedge_accounting_observe.restype=ctypes.c_int
        self.lib.aiedge_accounting_stale.argtypes=[ctypes.c_void_p];self.lib.aiedge_accounting_stale.restype=ctypes.c_int
    def tracker(self,document):return Tracker(self,document)

class Tracker:
    def __init__(self,native,document):
        document,_=validate(document)
        self.native=native;self.lock=threading.Lock();dials=document['dials'];self.count=len(dials)
        vector=ctypes.c_double*self.count;rate=document.get('maximum_rate_per_second')
        self.handle=native.lib.aiedge_accounting_create(vector(*(d['value_per_revolution'] for d in dials)),vector(*(d['position_error'] for d in dials)),self.count,int(rate is not None),rate or 0)
        if not self.handle:raise ValueError('accounting_format_rejected')
        self.finalizer=weakref.finalize(self,native.lib.aiedge_accounting_destroy,self.handle)
    def close(self):
        with self.lock:self.finalizer();self.handle=None
    def stale(self):
        with self.lock:
            if self.handle:self.native.lib.aiedge_accounting_stale(self.handle)
    def observe(self,positions,tick,clock):
        if len(positions)!=self.count or type(tick) is not int or not 0<=tick<=9223372036854775807:
            raise ValueError('invalid_accounting_observation')
        if any(not finite_number(p) or not 0<=p<10 for p in positions):raise ValueError('invalid_accounting_positions')
        if not isinstance(clock,str) or not clock.isascii() or not 1<=len(clock)<=128:raise ValueError('invalid_accounting_clock')
        raw=clock.encode('ascii');vector=ctypes.c_double*self.count;output=Result()
        with self.lock:
            if not self.handle:raise ValueError('accounting_tracker_closed')
            status=self.native.lib.aiedge_accounting_observe(self.handle,vector(*positions),self.count,tick,raw,len(raw),ctypes.byref(output))
        if status:raise ValueError('accounting_native_failed')
        if output.status not in STATES:raise ValueError('unknown_accounting_status')
        # Infinity is explicit unboundedness; it never enters JSON as a number.
        return {'available':bool(output.available),'current':bool(output.current),'accepted':bool(output.accepted),
                'state':STATES[output.status],'anchor_us':output.anchor_us,'through_us':output.through_us,
                'minimum':output.minimum if output.available else None,
                'maximum':output.maximum if output.available and math.isfinite(output.maximum) else None,
                'value':output.estimate if output.current and math.isfinite(output.estimate) else None,
                'upper_unbounded':bool(output.available and math.isinf(output.maximum))}
