import unittest
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from register_chart import register_profile


class RegisterChartTests(unittest.TestCase):
    def setUp(self):
        self.zone=ZoneInfo('UTC')
        self.midnight=int(datetime(2026,11,23,tzinfo=timezone.utc).timestamp()*1000)
        self.tick=600000

    def register(self,minute,value,epoch=0):
        t=self.midnight+minute*60000
        v=Decimal(str(value))
        return (t,v,(v-1,v+1),minute+50,False,(epoch,'photo_anchored_fine_dial','fmt','meter','ft3'),'a'*64)

    def test_modeled_boundary_preserves_observed_gap_and_daily_reset(self):
        rows=[self.register(m,v) for m,v in [(-10,99),(0,100),(10,101),(50,105),(60,106)]]
        a,b=(rows[i][0] for i in (2,3))
        out=register_profile(rows[-1][0],self.zone,rows,[],[],[[a,b]],[],{},1)
        samples={p[0]:p[1] for p in out['points']}
        self.assertTrue(out['reconciled'])
        self.assertEqual(samples[self.midnight+3*self.tick],103)
        self.assertEqual(out['gaps'],[(a,b)])
        self.assertEqual(out['openings'][self.midnight][0],100)

    def test_meter_replacement_is_a_real_source_boundary(self):
        rows=[self.register(0,100),self.register(10,101),self.register(40,5,1),self.register(50,6,1)]
        out=register_profile(rows[-1][0],self.zone,rows,[],[],[],[],{},1)
        self.assertFalse(any(rows[1][0]<p[0]<rows[2][0] for p in out['points']))
        self.assertNotEqual(out['points'][0][4],out['points'][-1][4])

    def test_known_optical_change_survives_missing_intermediate_register(self):
        rows=[self.register(0,100),self.register(60,112)]
        a=self.midnight+self.tick
        leg=dict(start=a,end=a+self.tick,basis='fine_dial',use=5,bounds=[4.9,5.1])
        out=register_profile(rows[-1][0],self.zone,rows,[],[],[],[],{},1,[leg])
        samples={p[0]:p[1] for p in out['points']}
        self.assertAlmostEqual(samples[a+self.tick]-samples[a],5,places=4)
        self.assertEqual(samples[rows[-1][0]],112)

    def test_empty_history_does_not_invent_a_zero(self):
        out=register_profile(self.midnight,self.zone,[],[],[],[],[],{},None)
        self.assertEqual(out['points'],[])
        self.assertEqual(out['openings'],{})
