"""Synthetic probability and fake-network routing cases; no images or real model."""
import hashlib,threading,unittest
import numpy as np
from reader import Reader,decoder_scores,decode_main_scores,DECODER_CONTRACT


def probability(rows):
    result=np.zeros((1,360),np.float32)
    for index,value in rows:result[0,index]=value
    return result


def legacy_quantized_decode(value):
    # Retained behavior oracle, used only with synthetic probability arrays.
    weights=np.clip(np.rint(value[0]*256),0,255).astype(np.int64)
    peak=int(np.argmax(weights));offsets=np.arange(-10,11)
    local=weights[(peak+offsets)%360]
    return ((peak+float(np.dot(offsets,local))/int(local.sum()))%360)/36


class FloatDecoderTests(unittest.TestCase):
    def decode(self,value,ccw=False):return decode_main_scores(decoder_scores(value,'main'),ccw)
    def test_sub_lsb_opposite_peaks_keep_strict_float_order(self):
        value=probability([(20,.4999),(200,.5001)])
        self.assertAlmostEqual(self.decode(value),float(np.float32(200/36)),places=7)
        self.assertAlmostEqual(legacy_quantized_decode(value),20/36,places=12)
        self.assertGreater(abs(self.decode(value)-legacy_quantized_decode(value)),4.99)
    def test_exact_tie_keeps_first_bin_convention(self):
        self.assertEqual(self.decode(probability([(20,.5),(200,.5)])),float(np.float32(20/36)))
    def test_broad_smooth_peak_does_not_collapse_to_first_quantized_bin(self):
        # Analytic strictly positive periodic cosine, with a unique sampled maximum.
        angles=np.arange(360,dtype=np.float64)
        value=((1+.5*np.cos(2*np.pi*(angles-100.25)/360))/360).astype(np.float32).reshape(1,360)
        position=self.decode(value)
        self.assertGreater(position,100/36)
        self.assertLess(position,100.25/36)
        self.assertEqual(legacy_quantized_decode(value),0.0)
        self.assertGreater(position,2.7)
    def test_sub_lsb_local_mass_changes_centroid(self):
        value=probability([(100,.5),(110,.0001),(260,.4999)])
        expected=(100+10*float(value[0,110])/(float(value[0,100])+float(value[0,110])))/36
        self.assertEqual(self.decode(value),float(np.float32(expected)))
        self.assertEqual(legacy_quantized_decode(value),100/36)
        self.assertGreater(self.decode(value),float(np.float32(100/36)))
    def test_window_excludes_offset_eleven(self):
        self.assertEqual(self.decode(probability([(50,.8),(61,.2)])),float(np.float32(50/36)))
    def test_wrapped_centroid_and_ccw(self):
        value=probability([(359,.2),(0,.5),(1,.3)])
        expected=((float(value[0,1])-float(value[0,359]))/sum(float(x) for x in value[0]))/36
        self.assertEqual(self.decode(value),float(np.float32(expected)))
        self.assertEqual(self.decode(value,True),float(np.float32(10-expected)))
        self.assertEqual(self.decode(probability([(0,1)]),True),0.0)
    def test_ccw_applied_once(self):
        value=probability([(20,.75),(21,.25)])
        self.assertEqual(self.decode(value),.5625)
        self.assertEqual(self.decode(value,True),9.4375)
    def test_rounding_guard_keeps_position_below_ten(self):
        value=probability([(359,1e-8),(0,1-1e-8)])
        self.assertEqual(self.decode(value),0.0)
    def test_bad_and_degenerate_payloads_are_rejected(self):
        good=probability([(0,1)])
        bads=[b'',bytes(360),bytes(1440),np.full((1,360),1e-12,np.float32).tobytes()]
        for number in (float('nan'),float('inf'),-.1,1.1):
            bad=good.copy();bad[0,0]=number;bads.append(bad.tobytes())
        for blob in bads:
            with self.subTest(size=len(blob)):
                with self.assertRaisesRegex(ValueError,'model_probability_contract:main'):decode_main_scores(blob,False)
    def test_hash_binds_actual_float_bytes_when_legacy_quantization_collides(self):
        a=probability([(20,.4999),(200,.5001)]);b=probability([(20,.5001),(200,.4999)])
        np.testing.assert_array_equal(np.rint(a*256),np.rint(b*256))
        self.assertNotEqual(hashlib.sha256(decoder_scores(a,'main')).hexdigest(),hashlib.sha256(decoder_scores(b,'main')).hexdigest())
        self.assertNotEqual(self.decode(a),self.decode(b))


class FakeNet:
    def __init__(self,output):self.output=output;self.invocations=0
    def set_tensor(self,index,value):pass
    def invoke(self):self.invocations+=1
    def get_tensor(self,index):return self.output

class FakeNative:
    def __init__(self):self.decoded=[]
    def prepare(self,rgb,sparse=False):
        return [{'state':'ok','visibility':1.,'features':bytes(384*40)} for _ in range(2)]
    def decode(self,scores,ccw):self.decoded.append((scores,ccw));return 4.25

class ReaderRoutingTests(unittest.TestCase):
    def make_reader(self):
        reader=Reader.__new__(Reader)
        reader.native=FakeNative();reader.lock=threading.Lock();reader.runtime=None
        reader.reuse_unchanged=True;reader.last_dials={};reader.sampling_sparse=False
        reader.dials=[{'name':'main','model':'main','direction':'cw'},{'name':'secondary','model':'secondary','direction':'ccw'}]
        reader.profile='synthetic';reader.hashes={};reader.pipeline_ids={False:'synthetic-only',True:'synthetic-sparse-only'}
        self.main=probability([(20,.4999),(200,.5001)])
        self.secondary=np.arange(360,dtype=np.int16).astype(np.int8).reshape(1,360)
        reader.networks={'main':(FakeNet(self.main),{'index':0},{'index':1}),'secondary':(FakeNet(self.secondary),{'index':0},{'index':1})}
        return reader
    def test_main_float_and_secondary_native_bytes_are_routed_and_bound(self):
        reader=self.make_reader();result=reader.read_rgb(b'fake-no-image')
        self.assertEqual(result['state'],'estimated')
        self.assertEqual(result['decoder_contract'],DECODER_CONTRACT)
        self.assertEqual(reader.native.decoded,[(self.secondary.tobytes(),True)])
        row=result['dial_positions'][0]
        self.assertEqual(row['position'],float(np.float32(200/36)))
        self.assertEqual(row['scores_sha256'],hashlib.sha256(self.main.astype('<f4').tobytes()).hexdigest())
        self.assertEqual(result['dial_positions'][1]['scores_sha256'],hashlib.sha256(self.secondary.tobytes()).hexdigest())
    def test_cache_reuses_bound_position_and_hash_then_mask_discards_hidden_dial(self):
        reader=self.make_reader();first=reader.read_rgb(b'fake-no-image')
        second=reader.read_rgb(b'fake-no-image')
        self.assertEqual(second['dial_positions'],first['dial_positions'])
        self.assertEqual(second['work']['inference_reused'],2)
        self.assertEqual([entry[0].invocations for entry in reader.networks.values()],[1,1])
        masked=reader.read_rgb(b'fake-no-image',observed=[True,False])
        self.assertEqual(masked['dial_positions'][1]['state'],'unavailable')
        self.assertNotIn(1,reader.last_dials)
        restored=reader.read_rgb(b'fake-no-image')
        self.assertEqual(restored['dial_positions'],first['dial_positions'])
        self.assertEqual([entry[0].invocations for entry in reader.networks.values()],[1,2])

if __name__=='__main__':unittest.main()
