"""Pure event decisions from immutable acquisitions and durable feedback."""
import hashlib,json
import capture_clock
from wheel_capture_policy import recommend

def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def decide(current,previous,previous_request,feedback,last_full,restart,document,configuration,capabilities,observed_phase_speed=None,observation_eligibility=None):
    timing=capture_clock.interval(previous,current)
    prior_recommendation=previous_request.get('recommendation') if previous_request else None
    deadline_missed=bool(prior_recommendation and timing['state']=='continuous' and timing['elapsed_seconds']>prior_recommendation['supported_interval_seconds'])
    age=0;refresh_uncertain=False
    if last_full:
        full_timing=capture_clock.interval(last_full,current)
        if full_timing['state']=='continuous':age=full_timing['elapsed_seconds']
        else:refresh_uncertain=True
    state=feedback.get('state') if feedback else None
    global_uncertain=state in ('ambiguous','bounded','unavailable','pending','recovering','rejected','inconsistent')
    relaxed=bool(observation_eligibility and observation_eligibility.get('relaxation_eligible') is True)
    fine_uncertain=observation_eligibility is not None and observation_eligibility.get('fine_observation_eligible') is not True
    flags={'first':previous is None or last_full is None,'restart':restart,'gap':previous is not None and timing['state']!='continuous',
           'quality_uncertain':state in ('unavailable','rejected','inconsistent'),'phase_ambiguous':global_uncertain and not (state=='ambiguous' and relaxed),
           'fine_observation_uncertain':fine_uncertain,'full_refresh_uncertain':refresh_uncertain,
           'accounting_uncertain':global_uncertain,'observation_only':relaxed,
           'backpressure':deadline_missed,'full_age_seconds':age,'observed_phase_speed':observed_phase_speed,
           'phase_interval_width':2*document['dials'][-1]['position_error']}
    recommendation=recommend(flags,capabilities,configuration)
    mask=[True]*len(document['dials'])
    if recommendation['requested_mode']=='LAST_TWO':
        mask=[False]*len(mask)
        for dial in document['dials'][-2:]:mask[dial['index']]=True
    return {'reader_observed':mask,'recommendation':recommendation,'timing':timing,'deadline_missed':deadline_missed,'flags':flags,
            'full_reason':recommendation['reasons']+(['missed_prior_recommendation_deadline'] if deadline_missed else [])}
