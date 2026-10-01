"""Container build smoke test; does not activate the frozen profile or capture images."""
import argparse
import numpy as np
from pathlib import Path
from package_assets import verify
from reader import Reader,PROFILE

def main():
    p=argparse.ArgumentParser();p.add_argument('--library',required=True);p.add_argument('--accounting-library');a=p.parse_args()
    assets=Path(__file__).parent/'assets';verify(assets)
    reader=Reader(a.library,assets/'models',PROFILE)
    if reader.sampling_sparse or reader.pipeline_id!=reader.pipeline_ids[False] or reader.pipeline_ids[False]==reader.pipeline_ids[True]:
        raise ValueError('full_sampling_identity_contract')
    if not hasattr(reader.native.lib,'aiedge_prepare_profile_reuse'):raise ValueError('changed_dial_runtime_missing')
    assert len(reader.networks)==2
    for net,inp,out in reader.networks.values():
        net.set_tensor(inp["index"],np.zeros((1,384,40),dtype=np.int8));net.invoke()
        assert net.get_tensor(out["index"]).shape==(1,360)
    reading=reader.native.reading([1000,100,10],[1.234,2.34,3.4],[.01,.01,.01])
    if reading['state']!='estimated' or abs(reading['value']-123.4)>1e-8:raise ValueError('reading_runtime_contract')
    from reading_format import ReadingFormat
    ambiguity_document={'version':1,'pipeline_id':'a'*64,'unit':'ft3','dials':[
        {'index':0,'value_per_revolution':1000,'position_error':.1},
        {'index':1,'value_per_revolution':5,'position_error':.01}]}
    ambiguity=ReadingFormat(reader.native,ambiguity_document).evaluate({'state':'estimated','pipeline_id':'a'*64,
        'dial_positions':[{'state':'estimated','position':1.1},{'state':'estimated','position':9}]})
    if ambiguity['state']!='ambiguous' or ambiguity['value'] is not None or len(ambiguity['bounds']['ranges'])!=4:
        raise ValueError('reading_ambiguity_runtime_contract')
    inconsistent_document={**ambiguity_document,'dials':[
        {'index':0,'value_per_revolution':10000,'position_error':.01},
        {'index':1,'value_per_revolution':1000,'position_error':.1},
        {'index':2,'value_per_revolution':5,'position_error':.01}]}
    inconsistent=ReadingFormat(reader.native,inconsistent_document).evaluate({'state':'estimated','pipeline_id':'a'*64,
        'dial_positions':[{'state':'estimated','position':p} for p in (9,1,0)]})
    if inconsistent['state']!='inconsistent' or not inconsistent['consistency']['dial_indices'] or inconsistent['value'] is not None:
        raise ValueError('reading_consistency_runtime_contract')
    if a.accounting_library:
        from accounting_native import AccountingNative
        document={'version':1,'pipeline_id':'a'*64,'unit':'ft3','dials':[{'index':0,'value_per_revolution':1000,'position_error':.1},{'index':1,'value_per_revolution':5,'position_error':.1}],'maximum_rate_per_second':.05}
        tracker=AccountingNative(a.accounting_library).tracker(document)
        try:
            assert tracker.observe([0,0],1000000,'runtime-check')['accepted']
            value=tracker.observe([.01,2],31000000,'runtime-check')
            if value['state']!='estimated' or abs(value['value']-1)>1e-8:raise ValueError('accounting_runtime_contract')
        finally:tracker.close()
    from temporal_reading import TemporalReading
    temporal=TemporalReading(ambiguity_document)
    temporal.observe([1.194,9],{'minimum':0,'maximum':0,'upper_unbounded':False})
    resolved=temporal.observe([1.006,1],{'minimum':.99,'maximum':1.01,'upper_unbounded':False})
    if resolved['state']!='estimated' or abs(resolved['value']-110.5)>1e-8:
        raise ValueError('temporal_reading_runtime_contract')
    print('Native ABI, physical calculation, ambiguity ranges and both pinned model tensor contracts loaded successfully.')
if __name__=='__main__':main()
