"""Model-free constructor and build-smoke routing regressions."""
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import reader as reader_module
from reader import Reader,PROFILE,DECODER_CONTRACT
from verify_runtime import verify_model_decoder

class DecoderSmokeTests(unittest.TestCase):
    def test_main_uses_float_and_secondary_preserves_native_bytes(self):
        class Native:
            def __init__(self):self.calls=[]
            def decode(self,scores,ccw):self.calls.append((scores,ccw));return 3.25
        native=Native();main=np.zeros((1,360),np.float32)
        main[0,20]=.4999;main[0,200]=.5001
        self.assertEqual(verify_model_decoder(native,'main',main),float(np.float32(200/36)))
        self.assertEqual(native.calls,[])
        secondary=np.arange(360,dtype=np.int16).astype(np.int8).reshape(1,360)
        self.assertEqual(verify_model_decoder(native,'secondary',secondary),3.25)
        self.assertEqual(native.calls,[(secondary.tobytes(),False)])
    def test_main_smoke_keeps_probability_guard_and_rejects_unknown_route(self):
        class Native:
            def decode(self,*args):raise AssertionError('Bad/main probability must not reach int8 native decoder')
        for value in [np.zeros((1,360),np.float32),np.full((1,360),1e-12,np.float32),np.full((1,360),np.nan,np.float32)]:
            with self.assertRaisesRegex(ValueError,'model_probability_contract:main'):verify_model_decoder(Native(),'main',value)
        with self.assertRaisesRegex(ValueError,'invalid_model_route'):verify_model_decoder(Native(),'unknown',np.zeros((1,360),np.int8))

class PipelineIdentityTests(unittest.TestCase):
    def test_constructor_binds_actual_reader_and_decoder_contract_without_loading_models(self):
        self.assertEqual(Path(reader_module.__file__).resolve().parent,Path(__file__).resolve().parent)
        source_bytes=Path(reader_module.__file__).read_bytes()
        model_bytes={'main-fixture.tflite':b'synthetic-main-model-contract','secondary-fixture.tflite':b'synthetic-secondary-model-contract'}
        models={role:(role+'-fixture.tflite',hashlib.sha256(model_bytes[role+'-fixture.tflite']).hexdigest()) for role in ('main','secondary')}
        native_bytes=b'synthetic-native-contract'
        source_path=Path(reader_module.__file__).resolve()
        def fake_read(path):
            if path.resolve()==source_path:return source_bytes
            if path.name=='native-fixture.so':return native_bytes
            if path.name in model_bytes:return model_bytes[path.name]
            raise AssertionError('Unexpected file read during model-free constructor: '+str(path))
        class FakeInterpreter:
            def __init__(self,model_content,num_threads,**kwargs):
                self.main=model_content==model_bytes['main-fixture.tflite']
                if model_content not in model_bytes.values():raise AssertionError('Not a synthetic model fixture')
                if num_threads!=1:raise AssertionError('Unexpected threads')
            def allocate_tensors(self):pass
            def get_input_details(self):
                return [{'index':0,'shape':np.array([1,384,40]),'dtype':np.float32 if self.main else np.int8,'quantization':(0.,0) if self.main else (reader_module.FEATURE_SCALE,reader_module.FEATURE_ZERO)}]
            def get_output_details(self):
                return [{'index':1,'shape':np.array([1,360]),'dtype':np.float32 if self.main else np.int8,'quantization':(0.,0) if self.main else (1/256,-128)}]
        contract={'profile':PROFILE,'models':{role:item[1] for role,item in models.items()},'native':hashlib.sha256(native_bytes).hexdigest(),
                  'reader':hashlib.sha256(source_bytes).hexdigest(),'litert':'synthetic-version','pillow':'synthetic-version','numpy':np.__version__,
                  'reference_kernels':False,'dial_reuse':'exact-source-region-v1','decoder_contract':dict(DECODER_CONTRACT)}
        def digest(document):return hashlib.sha256(json.dumps(document,sort_keys=True).encode()).hexdigest()
        with patch.object(reader_module,'Native',return_value=object()),patch.object(reader_module,'MODELS',models),patch.object(reader_module,'Interpreter',FakeInterpreter),patch.object(reader_module.Path,'read_bytes',fake_read),patch.object(reader_module.importlib.metadata,'version',return_value='synthetic-version'):
            current=Reader('native-fixture.so','synthetic-fixtures',PROFILE)
            for sparse in (False,True):
                self.assertEqual(current.pipeline_ids[sparse],digest(dict(contract,sparse=sparse)))
                previous={k:v for k,v in contract.items() if k!='decoder_contract'}
                self.assertNotEqual(current.pipeline_ids[sparse],digest(dict(previous,sparse=sparse)))
            self.assertEqual(current.pipeline_id,current.pipeline_ids[False])
            self.assertNotEqual(current.pipeline_ids[False],current.pipeline_ids[True])
            changed=dict(DECODER_CONTRACT,main='synthetic-different-decoder-contract')
            with patch.object(reader_module,'DECODER_CONTRACT',changed):
                other=Reader('native-fixture.so','synthetic-fixtures',PROFILE)
            for sparse in (False,True):self.assertNotEqual(other.pipeline_ids[sparse],current.pipeline_ids[sparse])

if __name__=='__main__':unittest.main()
