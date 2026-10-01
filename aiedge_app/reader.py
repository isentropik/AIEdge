"""Current routed int8 models with shared preprocessing; no training or label inference."""
import hashlib,io,json,threading,time
from pathlib import Path
import importlib.metadata
import numpy as np
from PIL import Image
from ai_edge_litert.interpreter import Interpreter,OpResolverType
from native import Native,Profile

PROFILE='frozen-gas-six-dial-v1'
MODELS={'main':('polar-main-int8.tflite','9c145e67e9008bf1e17567cd69baa48ce54af3b1d6b7fa0e1aeeb6b5ce9ec6a5'),
        'secondary':('polar-int8.tflite','b039dd72fa6cb2c821f9de2154a44879d5ce9620c862a2129176e2e18db05ed0')}
NAMES=('main.10000k','main.1000k','main.100k','main.10k','main.1k','secondary.5')

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
            if inp['shape'].tolist()!=[1,384,40] or out['shape'].tolist()!=[1,360] or inp['dtype']!=np.int8 or out['dtype']!=np.int8:raise ValueError('model_tensor_contract:'+role)
            scale,zero=inp['quantization']
            if abs(scale-0.006855103187263012)>1e-10 or zero!=-53:raise ValueError('model_quantization_contract:'+role)
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
    def read_rgb(self,rgb,sparse=None):
        if sparse is None:sparse=self.sampling_sparse
        if type(sparse) is not bool:raise ValueError('invalid_sampling_mode')
        start=time.perf_counter()
        result={'state':'rejected','profile':self.profile,'model_hashes':self.hashes,'dial_positions':[],
                'pipeline_id':self.pipeline_ids[sparse],'sampling':'sparse' if sparse else 'full',
                'accuracy_verified':False,'training_allowed':False,'physical_value':None,
                'work':{'preprocessing_reused':0,'inference_reused':0,'dials':len(self.dials)}}
        with self.lock:
            try:
                prepare=self.runtime.prepare_with_reuse if self.runtime and self.reuse_unchanged else (self.runtime or self.native).prepare
                prepared=prepare(rgb,sparse=sparse)
            except ValueError as e:
                self.last_dials.clear()
                result['error']=str(e);result['processing_seconds']=time.perf_counter()-start;return result
            for i,row in enumerate(prepared):
                dial=self.dials[i]
                item={'name':dial['name'],'state':row['state'],'position':None,'visibility':row['visibility']}
                if row.get('reused'):result['work']['preprocessing_reused']+=1
                if row['state']=='ok':
                    previous=self.last_dials.get(i)
                    if self.reuse_unchanged and previous and previous[0]==row['features']:
                        item.update(previous[1]);result['work']['inference_reused']+=1
                    else:
                        try:
                            role=dial['model'];net,inp,out=self.networks[role]
                            net.set_tensor(inp['index'],np.frombuffer(row['features'],dtype=np.int8).reshape(1,384,40));net.invoke()
                            scores=net.get_tensor(out['index']).tobytes()
                            item.update(state='estimated',position=self.native.decode(scores,dial['direction']=='ccw'),scores_sha256=hashlib.sha256(scores).hexdigest())
                        except Exception:
                            # A partial failed frame cannot leave successful dial outputs reusable.
                            self.last_dials.clear();raise
                    if self.reuse_unchanged:self.last_dials[i]=(row['features'],{k:item[k] for k in ('state','position','scores_sha256')})
                else:self.last_dials.pop(i,None)
                result['dial_positions'].append(item)
        if all(r['state']=='estimated' for r in result['dial_positions']):result['state']='estimated'
        else:result['error']='one_or_more_dials_rejected'
        result['processing_seconds']=time.perf_counter()-start
        return result
    def read_jpeg(self,blob):
        if len(blob)>4*1024*1024:raise ValueError('image_too_large')
        with Image.open(io.BytesIO(blob)) as image:
            if image.format!='JPEG' or image.size!=(640,480):raise ValueError('image_does_not_match_calibration')
            image.load();rgb=image.convert('RGB').tobytes()
        result=self.read_rgb(rgb);result['source_sha256']=hashlib.sha256(blob).hexdigest();return result
