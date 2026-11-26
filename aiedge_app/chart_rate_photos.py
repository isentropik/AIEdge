"""Read compact chart-rate evidence through the ordinary source-bound recognition ledger."""
from datetime import datetime
from capture_clock import interval
from dial_travel import phases
from optical_rate import solve

GUARD_MS = 120000
PAGE = 64


class ChartRatePhotos:
    def __init__(self):
        self.pages = {}
        self.results = {}

    def read(self, db, document, source, first, last, head):
        samples = {}
        for start in range(first//PAGE*PAGE,last+1,PAGE):
            stop=min(start+PAGE-1,head)
            key=(source['camera'],source['format_id'],start)
            page=self.pages.get(key)
            if page is None:
                slow={}
                fine=phases(db,start,stop,document,source,same_clock=False,slow_phases=slow)
                page={}
                for event,(obs,band) in fine.items():
                    stamp=datetime.fromisoformat(obs['captured_at']).timestamp()*1000
                    center=float(sum(slow[event])/2) if event in slow else None
                    row=(stamp,obs['monotonic_us']/1e6,float(band[0]),float(band[1]),center)
                    page[event]=(obs,row)
                if len(page)==PAGE:
                    if len(self.pages)>=256:
                        self.pages.pop(next(iter(self.pages)))
                    self.pages[key]=page
            samples.update((k,v) for k,v in page.items() if first<=k<=last)
        return samples

    def get(self,db,document,source,allowance,start,end,first,last,head):
        # Adjacent guards constrain the register at a tick when the nearest
        # exposure preceded or followed it. Never step across a failed transfer.
        left=max(1,first-16)
        right=min(head,last+16)
        cuts={r[0]+1 for r in db.execute('SELECT after_event_id FROM capture_failure_boundaries '
                                         'WHERE after_event_id BETWEEN ? AND ?',(left-1,right-1))}
        cuts.update(r[0] for r in db.execute('SELECT first_event FROM consumption_segment_links '
                                             'WHERE first_event BETWEEN ? AND ?',(left,right)))
        key=(source['camera'],source['format_id'],allowance,start,end,first,last,right,tuple(sorted(cuts)))
        if key in self.results:
            return self.results[key]
        if any(first<c<=last for c in cuts):
            return None
        samples=self.read(db,document,source,left,right,head)
        def linked(e):
            if e in cuts or e-1 not in samples or e not in samples:
                return False
            a,b=samples[e-1][0],samples[e][0]
            return (a['context_id']==b['context_id'] and interval(a,b)['state']=='continuous'
                    and b['monotonic_us']-a['monotonic_us']<660000000)
        if first not in samples or any(not linked(e) for e in range(first+1,last+1)):
            return None
        before,after=first,last
        while before>left and linked(before) and samples[before-1][1][0]>=start-GUARD_MS:
            before-=1
        while after<right and linked(after+1) and samples[after+1][1][0]<=end+GUARD_MS:
            after+=1
        rows=[samples[e][1] for e in range(before,after+1)]
        result=solve(rows,start,end,document['maximum_rate_per_second'],5,1000,allowance)
        if result is not None:
            if len(self.results)>=256:
                self.results.pop(next(iter(self.results)))
            self.results[key]=result
        return result


def comparison_allowance(document,revision,policy):
    if not policy or policy.get('format_id')!=revision or policy.get('pipeline_id')!=document.get('pipeline_id'):
        return None
    if [d['value_per_revolution'] for d in document['dials']][-2:] != [1000,5]:
        return None
    allowance=float(policy['slow_allowance_ft3']) if 'slow_allowance_ft3' in policy else None
    return allowance if allowance is not None and 6<=allowance<=100 else None
