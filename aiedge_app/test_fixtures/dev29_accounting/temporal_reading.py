"""Conservative absolute-offset refinement using existing consumption bounds.

The anchor is one register revolution. Cumulative consumption comes exclusively
from the existing accounting tracker. Interval unions retain possible offsets;
they do not guess missing turns or treat model estimates as verified labels.
No observation requests or device writes occur here.
"""
import json
from decimal import Decimal,localcontext,ROUND_CEILING,ROUND_FLOOR
from reading_bounds import feasible_ranges,format_bounds,MAX_RANGES,MAX_INTERSECTIONS
from reading_format import validate,finite_number,display_reading


class RangeLimit(Exception):pass
MAX_OUTPUT_BYTES=32768


def union(intervals):
    merged=[]
    for lower,upper in sorted(intervals):
        if merged and lower<=merged[-1][1]:merged[-1]=(merged[-1][0],max(upper,merged[-1][1]))
        else:
            merged.append((lower,upper))
            if len(merged)>MAX_RANGES:raise RangeLimit()
    return merged


def intersect(left,right):
    pieces=[];i=j=0
    while i<len(left) and j<len(right):
        lo=max(left[i][0],right[j][0]);hi=min(left[i][1],right[j][1])
        if lo<=hi:pieces.append((lo,hi))
        if left[i][1]<right[j][1]:i+=1
        else:j+=1
    return union(pieces)


class TemporalReading:
    def __init__(self,document):
        self.document,self.identity=validate(document)
        self.period=Decimal(str(self.document['dials'][0]['value_per_revolution']))
        self.anchor=None;self.observations=0

    def _snapshot(self,positions):
        dials=self.document['dials']
        return feasible_ranges([d['value_per_revolution'] for d in dials],positions,
                               [d['position_error'] for d in dials])

    def _lift(self,snapshot,predicted):
        pieces=[];work=0
        for lo,hi in predicted:
            for lower,upper in snapshot:
                first=int(((lo-upper)/self.period).to_integral_value(rounding=ROUND_CEILING))
                last=int(((hi-lower)/self.period).to_integral_value(rounding=ROUND_FLOOR))
                count=max(0,last-first+1)
                work+=count
                if work>MAX_INTERSECTIONS:raise RangeLimit()
                for turn in range(first,last+1):
                    offset=self.period*turn
                    pieces.append((max(lo,lower+offset),min(hi,upper+offset)))
        return union(pieces)

    def _modulo(self,intervals):
        pieces=[]
        for lo,hi in intervals:
            first=int((lo/self.period).to_integral_value(rounding=ROUND_FLOOR))
            last=int((hi/self.period).to_integral_value(rounding=ROUND_FLOOR))
            if last-first>1:raise RangeLimit()
            for turn in range(first,last+1):
                offset=self.period*turn
                lower=max(lo,offset)-offset;upper=min(hi,offset+self.period)-offset
                if lower<self.period:pieces.append((lower,upper))
        return union(pieces)

    def _result(self,intervals,provenance,refined=False):
        wraps=len(intervals)>1 and intervals[0][0]==0 and intervals[-1][1]==self.period
        bounds=format_bounds(self.document,{'state':'bounded','intervals':intervals,'wraps_register':wraps})
        result={'state':'ambiguous','value':None,'unit':self.document['unit'],'bounds':bounds,
                'provenance':provenance,'anchor_refined':refined,'observations':self.observations,
                'accuracy_verified':False,'training_allowed':False}
        # A single narrow band permits an estimate under the supplied tolerance.
        # It does not establish model accuracy, nor resolve total register turns.
        if len(intervals)==1:
            lo,hi=intervals[0];lowest=self.document['dials'][-1]
            resolution=max(Decimal(str(lowest['value_per_revolution']))/360,
                           Decimal(str(lowest['value_per_revolution']))*Decimal(str(lowest['position_error']))/10)
            slack=Decimal(str(lowest['value_per_revolution']))*Decimal('2e-12')
            if hi-lo<=2*resolution+slack:
                estimate=float((lo+hi)/2)
                if finite_number(estimate):
                    result.update(state='estimated',value=estimate,text=display_reading(estimate,self.document))
        # Leave room for the outer durable accounting record. A legal but very
        # large number format must not block the worker with an oversized row.
        if len(json.dumps(result,separators=(',',':'),allow_nan=False).encode())>MAX_OUTPUT_BYTES:
            return {'state':'unavailable','value':None,'reason':'temporal_result_limit',
                    'accuracy_verified':False,'training_allowed':False}
        return result

    def observe(self,positions,consumption):
        # This layer is internal to validated format/inference admission. Still
        # reject malformed values at its boundary rather than accepting zip loss.
        if len(positions)!=len(self.document['dials']) or any(not finite_number(p) or not 0<=p<10 for p in positions):
            raise ValueError('invalid_temporal_positions')
        minimum,maximum=consumption.get('minimum'),consumption.get('maximum')
        if not finite_number(minimum) or minimum<0 or (maximum is not None and (not finite_number(maximum) or maximum<minimum)):
            raise ValueError('invalid_temporal_consumption')
        if maximum is None and consumption.get('upper_unbounded') is not True:
            raise ValueError('invalid_temporal_consumption')
        with localcontext() as context:
            context.prec=340
            snapshot=self._snapshot(positions)
            if snapshot['state']!='bounded':
                return {'state':'unavailable','value':None,'reason':snapshot['reason'],
                        'accuracy_verified':False,'training_allowed':False}
            bands=snapshot['intervals']
            if self.anchor is None:
                if minimum!=0 or maximum!=0:
                    return {'state':'unavailable','value':None,'reason':'temporal_anchor_unavailable',
                            'accuracy_verified':False,'training_allowed':False}
                self.anchor=bands;self.observations=1
                return self._result(bands,'single_image')
            if maximum is None:
                # Arbitrarily many full register revolutions make every anchor
                # alias reachable. Do not claim history narrows the offset.
                self.observations+=1
                return self._result(bands,'single_image_unbounded_consumption')
            low,high=Decimal(str(minimum)),Decimal(str(maximum))
            candidate=self.anchor
            try:
                predicted=union([(lo+low,hi+high) for lo,hi in candidate])
                current=self._lift(bands,predicted)
                if not current:
                    return {'state':'unavailable','value':None,'reason':'temporal_bounds_disagree',
                            'accuracy_verified':False,'training_allowed':False}
                possible_anchor=union([(lo-high,hi-low) for lo,hi in current])
                narrowed=intersect(candidate,possible_anchor)
                if not narrowed:raise ValueError('temporal_anchor_inconsistent')
                # Recompute from the narrowed anchor. This remains a conservative
                # envelope; no independence assumption sharpens the bound.
                current=self._lift(bands,union([(lo+low,hi+high) for lo,hi in narrowed]))
                modulo=self._modulo(current)
                result=self._result(modulo,'temporal_consumption_bounds',narrowed!=candidate)
            except RangeLimit:
                return {'state':'unavailable','value':None,'reason':'temporal_range_limit',
                        'accuracy_verified':False,'training_allowed':False}
            self.anchor=narrowed;self.observations+=1;result['observations']=self.observations
            return result
