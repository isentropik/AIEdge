"""Invented arrays/labels only; no photo, model construction or training."""
import unittest
import numpy as np
import features_and_batch as f
import foreground_generator as g

class RecipeTests(unittest.TestCase):
    def test_new_main_rows_do_not_corotate(self):
        x=np.arange(4*360*40,dtype=np.float32).reshape(4,360,40)
        y=np.arange(4*360,dtype=np.float32).reshape(4,360)
        bx,by,m=f.batch(np.random.default_rng(921360),x,y,x+1e6,y+1e4,x+2e6,y+2e4)
        self.assertEqual(bx.shape,(32,384,40));self.assertEqual(by.shape,(32,360))
        np.testing.assert_array_equal(bx[-10:,12:-12],(x+2e6)[m['main_indices']])
        np.testing.assert_array_equal(by[-10:],(y+2e4)[m['main_indices']])
        self.assertEqual(m['main_shifts'],[0]*10)
    def test_ccw_target_is_reversed_exactly_once(self):
        rows=[{'dial':'main_1k','label':float(k)} for k in range(10)]
        targets=f.labels(rows)
        self.assertEqual(np.argmax(targets,axis=1).tolist(),[(-k*36)%360 for k in range(10)])
        self.assertEqual((f.SEED,f.EPOCHS,f.STEPS,f.LEARNING_RATE),(921360,35,20,.0005))
    def test_uncertain_contact_pixels_never_supply_color(self):
        a={'image_size':[40,40],'opaque_foreground_core_polygons':[[[8,8],[16,8],[16,16],[8,16]]],
           'uncertain_contact_regions':[[[12,8],[20,8],[20,16],[12,16]]]}
        x=np.full((40,40,3),30,np.uint8);y=x.copy();mask,_=g.effective_core(a);y[~mask]=240
        np.testing.assert_array_equal(g.foreground_color(x,a),g.foreground_color(y,a))
    def test_null_foreground_cannot_encode_target(self):
        bg=np.random.default_rng(1).integers(0,255,(40,40,3),dtype=np.uint8)
        for target in g.TARGETS:
            np.testing.assert_array_equal(g.composite(bg,np.zeros((40,40)),[20,20,20]),bg)
        self.assertEqual(len(g.SEEDS)*len(g.TARGETS),300)
if __name__=='__main__':unittest.main()
