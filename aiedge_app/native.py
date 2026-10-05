"""Portable bridge to shared preprocessing and owned runtime calibration profiles."""
import ctypes,base64,threading,weakref
from pathlib import Path

class Native:
    def __init__(self,path):
        self.lib=ctypes.CDLL(str(Path(path).resolve()))
        self.lib.aiedge_abi.restype=ctypes.c_int
        if self.lib.aiedge_abi()!=2:raise ValueError('unsupported_native_abi')
        self.lib.aiedge_prepare.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p]
        self.lib.aiedge_prepare.restype=ctypes.c_int
        self.lib.aiedge_preparation_status.argtypes=[ctypes.c_int];self.lib.aiedge_preparation_status.restype=ctypes.c_char_p
        self.lib.aiedge_decode.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.POINTER(ctypes.c_float)];self.lib.aiedge_decode.restype=ctypes.c_int
    def reading(self,revolutions,positions,errors):
        count=len(revolutions)
        if not 1<=count<=16 or len(positions)!=count or len(errors)!=count:
            raise ValueError('reading_dial_count_mismatch')
        function=self.lib.aiedge_reading
        function.argtypes=[ctypes.POINTER(ctypes.c_double)]*3+[ctypes.c_size_t,ctypes.POINTER(ctypes.c_double)]
        function.restype=ctypes.c_int
        values=ctypes.c_double*count;output=ctypes.c_double()
        status=function(values(*revolutions),values(*positions),values(*errors),count,ctypes.byref(output))
        states={0:'invalid',1:'inconsistent',2:'ambiguous',3:'estimated'}
        if status not in states:raise ValueError('unknown_reading_status')
        return {'state':states[status],'value':output.value if status==3 else None}
    def prepare(self,rgb,sparse=True):
        if len(rgb)!=640*480*3:raise ValueError('frame_dimensions_must_match_profile')
        source=ctypes.create_string_buffer(rgb);out=ctypes.create_string_buffer(6*384*40);states=(ctypes.c_int*6)();visibility=(ctypes.c_double*6)()
        status=self.lib.aiedge_prepare(source,len(rgb),int(sparse),out,6*384*40,states,visibility)
        if status:raise ValueError({-1:'invalid_native_input',-2:'alignment_rejected',-3:'preprocessing_failed'}.get(status,'unknown_native_error'))
        return [{'state':self.lib.aiedge_preparation_status(states[i]).decode(),'visibility':visibility[i],'features':out.raw[i*15360:(i+1)*15360]} for i in range(6)]
    def decode(self,scores,ccw):
        if len(scores)!=360:raise ValueError('invalid_score_count')
        source=ctypes.create_string_buffer(scores);value=ctypes.c_float()
        if self.lib.aiedge_decode(source,len(scores),int(ccw),ctypes.byref(value)):raise ValueError('invalid_scores')
        return value.value

class Marker(ctypes.Structure):
    _fields_=[('pixels',ctypes.c_void_p),('bytes',ctypes.c_size_t),('x',ctypes.c_int),('y',ctypes.c_int),('w',ctypes.c_int),('h',ctypes.c_int),('targetX',ctypes.c_double),('targetY',ctypes.c_double)]
class Dial(ctypes.Structure):
    _fields_=[('x',ctypes.c_int),('y',ctypes.c_int),('w',ctypes.c_int),('h',ctypes.c_int),('anchorX',ctypes.c_int),('anchorY',ctypes.c_int),('inverse',ctypes.c_double*9),('pivot',ctypes.c_double*2)]
class Profile:
    def __init__(self,native,document):
        from calibration import validate
        self.document,self.digest=validate(document);self.native=native;self.lock=threading.Lock()
        lib=native.lib
        lib.aiedge_profile_create.argtypes=[ctypes.POINTER(Marker),ctypes.c_size_t,ctypes.POINTER(Dial),ctypes.c_size_t,ctypes.POINTER(ctypes.c_int)];lib.aiedge_profile_create.restype=ctypes.c_void_p
        lib.aiedge_profile_destroy.argtypes=[ctypes.c_void_p];lib.aiedge_profile_destroy.restype=None
        lib.aiedge_prepare_profile.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t];lib.aiedge_prepare_profile.restype=ctypes.c_int
        self.reuse_function=getattr(lib,'aiedge_prepare_profile_reuse',None)
        if self.reuse_function:
            self.reuse_function.argtypes=lib.aiedge_prepare_profile.argtypes+[ctypes.c_void_p]
            self.reuse_function.restype=ctypes.c_int
        self.masked_function=getattr(lib,'aiedge_prepare_profile_masked',None)
        if self.masked_function:
            self.masked_function.argtypes=lib.aiedge_prepare_profile.argtypes+[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t]
            self.masked_function.restype=ctypes.c_int
        buffers=[];markers=(Marker*3)();count=len(self.document['dials']);dials=(Dial*count)()
        for i,m in enumerate(self.document['markers']):
            b=ctypes.create_string_buffer(base64.b64decode(m['pixels']));buffers.append(b)
            markers[i]=Marker(ctypes.cast(b,ctypes.c_void_p),len(b.raw)-1,*m['box'],*m['target'])
        for i,d in enumerate(self.document['dials']):
            dials[i]=Dial(*d['crop'],*d['sampling_anchor'],(ctypes.c_double*9)(*d['inverse']),(ctypes.c_double*2)(*d['pivot']))
        error=ctypes.c_int();self.handle=lib.aiedge_profile_create(markers,3,dials,count,ctypes.byref(error))
        if not self.handle:raise ValueError('native_calibration_rejected:'+str(error.value))
        self.finalizer=weakref.finalize(self,lib.aiedge_profile_destroy,self.handle)
    def close(self):
        with self.lock:self.finalizer();self.handle=None
    def prepare(self,rgb,sparse=True):
        return self._prepare(rgb,sparse,False)
    def prepare_with_reuse(self,rgb,sparse=True):
        return self._prepare(rgb,sparse,True)
    def prepare_masked(self,rgb,observed,sparse=True):
        if not isinstance(observed,(list,tuple)) or len(observed)!=len(self.document['dials']) or any(type(x) is not bool for x in observed) or not any(observed):raise ValueError('invalid_observation_mask')
        if not self.masked_function:raise ValueError('masked_preparation_unsupported')
        return self._prepare(rgb,sparse,True,observed)
    def _prepare(self,rgb,sparse,reuse,observed=None):
        if len(rgb)!=640*480*3:raise ValueError('frame_dimensions_must_match_profile')
        count=len(self.document['dials']);size=count*384*40
        source=ctypes.create_string_buffer(rgb);out=ctypes.create_string_buffer(size);states=(ctypes.c_int*count)();visibility=(ctypes.c_double*count)()
        reused=(ctypes.c_int*count)()
        with self.lock:
            if not self.handle:raise ValueError('calibration_closed')
            args=(self.handle,source,len(rgb),int(sparse),out,size,states,visibility,count)
            if observed is not None:
                mask=(ctypes.c_uint8*count)(*observed)
                status=self.masked_function(*args,reused,mask,count)
            else:status=self.reuse_function(*args,reused) if reuse and self.reuse_function else self.native.lib.aiedge_prepare_profile(*args)
        if status:raise ValueError({-1:'invalid_native_input',-2:'alignment_rejected',-3:'preprocessing_failed'}.get(status,'unknown_native_error'))
        raw=out.raw
        rows=[({'state':'unavailable','visibility':None,'features':None} if observed is not None and not observed[i] else {'state':self.native.lib.aiedge_preparation_status(states[i]).decode(),'visibility':visibility[i],'features':raw[i*15360:(i+1)*15360]}) for i in range(count)]
        if reuse:
            for i,row in enumerate(rows):row['reused']=bool(reused[i])
        if observed is not None:
            for i,flag in enumerate(observed):
                if not flag:rows[i]={'state':'unavailable','visibility':None,'features':None,'reused':False}
        return rows
