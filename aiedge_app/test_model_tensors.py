"""Native feature units and strict mixed model probability contracts."""
import unittest
import numpy as np
from reader import network_input,decoder_scores,FEATURE_SCALE,FEATURE_ZERO


class ModelTensorTests(unittest.TestCase):
    def test_main_dequantizes_native_units_without_resampling(self):
        quantized=np.resize(np.asarray([-128,-53,0,127],dtype=np.int8),384*40)
        actual=network_input(quantized.tobytes(),'main')
        self.assertEqual(actual.dtype,np.float32)
        self.assertEqual(actual.shape,(1,384,40))
        np.testing.assert_array_equal(actual.reshape(-1)[1::4],np.zeros(3840,np.float32))
        self.assertAlmostEqual(float(actual.reshape(-1)[0]),(-128-FEATURE_ZERO)*FEATURE_SCALE,places=7)
        self.assertAlmostEqual(float(actual.reshape(-1)[3]),(127-FEATURE_ZERO)*FEATURE_SCALE,places=7)

    def test_secondary_preserves_the_native_int8_tensor(self):
        blob=bytes(range(256))*60
        actual=network_input(blob,'secondary')
        self.assertEqual(actual.dtype,np.int8)
        self.assertEqual(actual.shape,(1,384,40))
        self.assertEqual(actual.tobytes(),blob)

    def test_float_probabilities_keep_the_native_decoder_bins(self):
        probability=np.zeros((1,360),np.float32)
        probability[0,0]=.25;probability[0,1]=.75
        actual=np.frombuffer(decoder_scores(probability,'main'),np.int8)
        self.assertEqual(actual[:3].tolist(),[-64,64,-128])

    def test_probability_validation_rejects_corrupt_outputs(self):
        good=np.zeros((1,360),np.float32);good[0,0]=1
        bads=[good.astype(np.float64),good[0],np.zeros((1,360),np.float32),good*2]
        for value in (float('nan'),float('inf'),-.1,1.1):
            bad=good.copy();bad[0,0]=value;bads.append(bad)
        for bad in bads:
            with self.subTest(dtype=str(bad.dtype),shape=bad.shape):
                with self.assertRaisesRegex(ValueError,'model_probability_contract:main'):
                    decoder_scores(bad,'main')

    def test_secondary_output_bytes_are_unchanged(self):
        value=np.arange(360,dtype=np.int16).astype(np.int8).reshape(1,360)
        self.assertEqual(decoder_scores(value,'secondary'),value.tobytes())


if __name__=='__main__':unittest.main()
