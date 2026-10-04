"""Routed server models with shared preprocessing; no training or label inference."""
import hashlib,io,json,threading,time
from pathlib import Path
import importlib.metadata
import numpy as np
from PIL import Image
from ai_edge_litert.interpreter import Interpreter,OpResolverType
from native import Native,Profile

PROFILE='frozen-gas-six-dial-v1'
MODELS={'main':('polar-main-float.tflite','8c0d63fbe8c3cbc7bd854c464d9cd342b46f766a107d2cbd6d93026c49601016'),
        'secondary':('polar-int8.tflite','b039dd72fa6cb2c821f9de2154a44879d5ce9620c862a2129176e2e18db05ed0')}
NAMES=('main.10000k','main.1000k','main.100k','main.10k','main.1k','secondary.5')
FEATURE_SCALE=0.006855103187263012
FEATURE_ZERO=-53

def network_input(features,role):
    """The native ABI still supplies the exact frozen int8 feature tensor."""
    value=np.frombuffer(features,dtype=np.int8).reshape(1,384,40)
    return (value.astype(np.float32)-FEATURE_ZERO)*FEATURE_SCALE if role=='main' else value

def decoder_scores(value,role):
    if role=='main':
        # Preserve the native circular decoder's probability-bin contract.
        # Float weights avoid catastrophic near-tied peaks in the int8 main
        # export; preprocessing, guards and secondary weights stay unchanged.
        if value.dtype!=np.float32 or value.shape!=(1,360) or not np.isfinite(value).all() or np.any(value<0) or np.any(value>1) or abs(float(value.sum())-1)>2e-5:
            raise ValueError('model_probability_contract:main')
        value=np.clip(np.rint(value*256)-128,-128,127).astype(np.int8)
    return value.tobytes()

class Reader:
    def __init__(self,library,models,profile,reference_kernels=False,reuse_unchanged=True,sampling_sparse=False):
        if type(sampling_sparse) is not bool:raise ValueError('invalid_sampling_mode')
        self.sampling_sparse=sampling_sparse
        self.native=Native(library);self.lock=threading.Lock();self.networks={}
        self.runtime=None;self.reuse_unchanged=reuse_unchanged;self.last_dials={}
        if isinstance(profile,dict):
            self.runtime=Profile(self.native,profile)
            self.dials=self.runtime.document['dials'];identity=self.runtime.digest
        elif profile==PROFILE:
            self.dials=[{'name':name,'model':'main' if i<5 else 'secondary','direction':'ccw' if i in (0,2,4) else 'cw'} for i,name in enumerate(NAMES)]
            identity=PROFILE
        else:raise ValueError('unsupported_calibration_profile')
        self.hashes={};self.profile=identity
        for role,(name,expected) in MODELS.items():
            blob=(Path(models)/name).read_bytes();actual=hashlib.sha256(blob).hexdigest()
            if actual!=expected:raise ValueError('model_hash_mismatch:'+role)
            kwargs={'experimental_op_resolver_type':OpResolverType.BUILTIN_REF} if reference_kernels else {}
            net=Interpreter(model_content=blob,num_threads=1,**kwargs);net.allocate_tensors()
            inp,out=net.get_input_details()[0],net.get_output_details()[0]
            dtype=np.float32 if role=='main' else np.int8
            if inp['shape'].tolist()!=[1,384,40] or out['shape'].tolist()!=[1,360] or inp['dtype']!=dtype or out['dtype']!=dtype:raise ValueError('model_tensor_contract:'+role)
            scale,zero=inp['quantization']
            if role=='main':
                if (scale,zero)!=(0.,0) or out['quantization']!=(0.,0):raise ValueError('model_float_contract:'+role)
            else:
                if abs(scale-FEATURE_SCALE)>1e-10 or zero!=FEATURE_ZERO:raise ValueError('model_quantization_contract:'+role)
                if out['quantization']!=(1/256,-128):raise ValueError('model_output_quantization_contract:'+role)
            self.networks[role]=(net,inp,out);self.hashes[role]=actual
        contract={'profile':self.profile,'models':self.hashes,'native':hashlib.sha256(Path(library).read_bytes()).hexdigest(),
                  'reader':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'litert':importlib.metadata.version('ai-edge-litert'),'pillow':importlib.metadata.version('Pillow'),
                  'numpy':np.__version__,'reference_kernels':reference_kernels,
                  'dial_reuse':'exact-source-region-v1' if reuse_unchanged else 'disabled'}
        self.pipeline_ids={mode:hashlib.sha256(json.dumps(dict(contract,sparse=mode),sort_keys=True).encode()).hexdigest()
                           for mode in (False,True)}
        self.pipeline_id=self.pipeline_ids[self.sampling_sparse]
    def _observed(self,observed):
        if observed is None:return None
        if not isinstance(observed,(list,tuple)) or len(observed)!=len(self.dials) or any(type(flag) is not bool for flag in observed) or not any(observed):
            raise ValueError('invalid_reader_observation_mask')
        return list(observed)
    def read_rgb(self,rgb,sparse=None,observed=None):
        mask=self._observed(observed)
        if sparse is None:sparse=self.sampling_sparse
        if type(sparse) is not bool:raise ValueError('invalid_sampling_mode')
        start=time.perf_counter()
        result={'state':'rejected','profile':self.profile,'model_hashes':self.hashes,'dial_positions':[],
                'pipeline_id':self.pipeline_ids[sparse],'sampling':'sparse' if sparse else 'full',
                'accuracy_verified':False,'training_allowed':False,'physical_value':None,
                'work':{'preprocessing_reused':0,'inference_reused':0,'dials':len(self.dials)}}
        if mask is not None:
            # Diagnostic only. JPEG wrapper replaces this with byte-bound provenance.
            result['_observed_mask']=mask
            result['work']['selected_dials']=sum(mask)
        with self.lock:
            if mask is not None:
                for i,flag in enumerate(mask):
                    if not flag:self.last_dials.pop(i,None)
            try:
                prepare=self.runtime.prepare_with_reuse if self.runtime and self.reuse_unchanged else (self.runtime or self.native).prepare
                prepared=prepare(rgb,sparse=sparse)
                if len(prepared)!=len(self.dials):raise ValueError('native_dial_count_mismatch')
            except ValueError as e:
                self.last_dials.clear()
                result['error']=str(e);result['processing_seconds']=time.perf_counter()-start;return result
            for i,row in enumerate(prepared):
                dial=self.dials[i]
                if mask is not None and not mask[i]:
                    result['dial_positions'].append({'name':dial['name'],'state':'unavailable','position':None,'visibility':None,'reason':'dial_not_observed'})
                    continue
                item={'name':dial['name'],'state':row['state'],'position':None,'visibility':row['visibility']}
                if row.get('reused'):result['work']['preprocessing_reused']+=1
                if row['state']=='ok':
                    previous=self.last_dials.get(i)
                    if self.reuse_unchanged and previous and previous[0]==row['features']:
                        item.update(previous[1]);result['work']['inference_reused']+=1
                    else:
                        try:
                            role=dial['model'];net,inp,out=self.networks[role]
                            net.set_tensor(inp['index'],network_input(row['features'],role));net.invoke()
                            scores=decoder_scores(net.get_tensor(out['index']),role)
                            item.update(state='estimated',position=self.native.decode(scores,dial['direction']=='ccw'),scores_sha256=hashlib.sha256(scores).hexdigest())
                        except Exception:
                            # A partial failed frame cannot leave successful dial outputs reusable.
                            self.last_dials.clear()
                            if mask is not None:
                                result['dial_positions']=[];result['error']='selected_model_inference_failed'
                                result['processing_seconds']=time.perf_counter()-start;return result
                            raise
                    if self.reuse_unchanged:self.last_dials[i]=(row['features'],{k:item[k] for k in ('state','position','scores_sha256')})
                else:self.last_dials.pop(i,None)
                result['dial_positions'].append(item)
        selected=[r for i,r in enumerate(result['dial_positions']) if mask is None or mask[i]]
        if all(r['state']=='estimated' for r in selected):result['state']='estimated'
        else:result['error']='one_or_more_dials_rejected'
        result['processing_seconds']=time.perf_counter()-start
        return result
    def read_jpeg(self,blob,observed=None):
        mask=self._observed(observed)
        if len(blob)>4*1024*1024:raise ValueError('image_too_large')
        with Image.open(io.BytesIO(blob)) as image:
            if image.format!='JPEG' or image.size!=(640,480):raise ValueError('image_does_not_match_calibration')
            image.load();rgb=image.convert('RGB').tobytes()
        result=self.read_rgb(rgb,observed=mask);result['source_sha256']=hashlib.sha256(blob).hexdigest()
        result.pop('_observed_mask',None)
        if mask is not None:
            provenance={'schema_version':1,'source_sha256':result['source_sha256'],'pipeline_id':result['pipeline_id']}
            if result['state']=='estimated':result['observation_support']={**provenance,'observed':mask}
            else:result['observation_attempt']={**provenance,'requested_observed':mask}
        return result
