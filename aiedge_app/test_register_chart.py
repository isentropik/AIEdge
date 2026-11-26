import unittest
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from register_chart import measured_change_bounds, register_profile


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

    def test_disjoint_gap_photo_is_reported_and_other_rate_bounds_survive(self):
        rows=[self.register(10*i,100+i) for i in range(7)]
        t=self.midnight+3*self.tick
        photos={t:[(97.9,98.1)]}
        legs=[dict(start=a[0],end=b[0],basis='fine_dial',use=1,bounds=[.9,1.1]) for a,b in zip(rows,rows[1:])]
        out=register_profile(rows[-1][0],self.zone,rows,[],[],[],[],photos,1,legs)
        self.assertTrue(out['reconciled'])
        self.assertEqual(out['photoConflicts'],[dict(time=t,photo=photos[t],register=[102.,104.])])
        self.assertTrue(out['changeBounds'])
        self.assertEqual(photos[t],[(97.9,98.1)])

    def test_compatible_photo_can_differ_from_the_nominal(self):
        rows=[self.register(10*i,100+i) for i in range(3)]
        t=rows[1][0]
        out=register_profile(rows[-1][0],self.zone,rows,[],[],[],[],{t:[(95,95.1),(101.4,101.5)]},1)
        self.assertTrue(out['reconciled'])
        self.assertEqual(out['photoConflicts'],[])
        point=next(p for p in out['points'] if p[0]==t)
        self.assertLessEqual(101.4,point[1])
        self.assertLessEqual(point[1],101.5)

    def test_hour_and_daily_change_keep_a_shared_offset_and_the_tightest_interval_evidence(self):
        start=self.midnight
        points=[[start+i*self.tick,100+i,90+i,110+i,0] for i in range(7)]
        legs=[[start,start+6*self.tick,0,25],
              *[[a[0],b[0],.9,1.1] for a,b in zip(points,points[1:])]]
        bounds={(a,b):(lo,hi) for a,b,lo,hi in measured_change_bounds(points,{start:[100,90,110,0,False]},legs)}
        self.assertAlmostEqual(bounds[start,points[-1][0]][0],5.4,places=5)
        self.assertAlmostEqual(bounds[start,points[-1][0]][1],6.6,places=5)
        self.assertAlmostEqual(bounds[start,points[3][0]][1],3.3,places=5)

    def test_one_missing_leg_preserves_unknown_usage_and_a_measured_partial_lower_bound(self):
        points=[[self.midnight+i*self.tick,100+i,90+i,110+i,0] for i in range(7)]
        a,b=points[0][0],points[-1][0]
        first=[points[0][0],points[1][0],.75,1.25]
        bounds={(x,y):(l,h) for x,y,l,h in measured_change_bounds(points,{},[first,[a,b,0,25]])}
        self.assertEqual(bounds[a,b],(.75,25))
        self.assertNotIn((points[3][0],points[4][0]),bounds)
        # An unsupported center, an unknown absolute baseline or a rejected
        # measurement cannot establish a relative error bar.
        unknown=[[a,10,None,None,0],[a+self.tick,10,None,None,0]]
        rejected=[[a,a+self.tick,0,1]]
        self.assertEqual(measured_change_bounds(unknown,{},rejected,rejected),[])
        unknown[1][4]=1
        self.assertEqual(measured_change_bounds(unknown,{},rejected),[])
