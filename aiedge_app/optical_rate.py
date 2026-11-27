"""Clock-interval gas usage from joint fine and slow dial observations."""
from bisect import bisect_left
from math import ceil, floor, inf, isfinite
from statistics import median

# Closed difference constraints. Entry [i][j] bounds x[j]-x[i]. Keep the
# current register, both exact clock ticks and a common slow-dial offset.
ZERO, CURRENT, START, END, OFFSET = range(5)
N = 5
EPS = 1e-10
MAX_ZONES = 1024


def empty():
    return [[0. if i == j else inf for j in range(N)] for i in range(N)]


def constrain(zone, i, j, upper):
    """Intersect one inequality and keep all pairwise projections exact."""
    if zone[i][j] <= upper:
        return True
    if zone[j][i] + upper < -EPS:
        return False
    row = zone[j][:]
    for values in zone:
        bound = values[i] + upper
        if isfinite(bound):
            for k, suffix in enumerate(row):
                if bound + suffix < values[k]:
                    values[k] = bound + suffix
    return True


def forget(zone, index):
    for j in range(N):
        if j != index:
            zone[j][index] = zone[index][j] = inf


def mark(zone, index):
    zone[index] = zone[CURRENT][:]
    for row in zone:
        row[index] = row[CURRENT]
    zone[index][index] = 0.


def contains(outer, inner):
    return all(a + EPS >= b for p,q in zip(outer,inner) for a,b in zip(p,q))


def merged(ranges):
    result = []
    for lo,hi in sorted(ranges):
        if result and lo <= result[-1][1] + EPS:
            result[-1][1] = max(result[-1][1],hi)
        else:
            result.append([lo,hi])
    return result


def pointer_at(rows, stamps, t):
    j = bisect_left(stamps,t)
    if j < len(rows) and stamps[j] == t:
        return rows[j]
    if j == 0 or j == len(rows):
        return None
    delta = rows[j]-rows[j-1]
    return rows[j-1] + delta*(t-stamps[j-1])/(stamps[j]-stamps[j-1])


def unwrapped(centers, period):
    """Follow successive observed pointer angles across zero in either direction."""
    values = [centers[0]]
    for center in centers[1:]:
        winding = floor((values[-1]-center)/period + .5)
        values.append(center + winding*period)
    return values


def slow_travel(samples, start, end, rate, period, allowance):
    coarse = [(s[0],s[4]) for s in samples if s[4] is not None]
    if len(coarse)<2 or not coarse[0][0]<=start<end<=coarse[-1][0]:
        return None
    stamps,centers = zip(*coarse)
    if any((b-a)*rate/1000 + 2*allowance >= period/2 for a,b in zip(stamps,stamps[1:])):
        return None
    trace = unwrapped(centers,period)
    return pointer_at(trace,stamps,end) - pointer_at(trace,stamps,start)


def project(clock, rate, turn, slow_turn, allowance, follow_trace):
    """Intersect both dial measurements, forward flow and the two exact clock ticks."""
    zones = [empty()]
    previous = clock[0][0]
    group = None
    for index,(time,record,winding) in enumerate(clock):
        limit = rate*(time-previous)
        previous = time
        for z in zones:
            for i in range(N):
                if i!=CURRENT:
                    z[i][CURRENT]+=limit
        if isinstance(record,int):
            for z in zones:
                mark(z,record)
            continue
        wall,_,lo,hi,slow = record
        if slow is not None:
            # The configured comparison applies over at most an hour and 27 ft³.
            # Restart its offset before another slower-dial winding can fit.
            if (group is None or max(group[2],slow)-min(group[1],slow)>27
                    or time-group[0]>3600 or (time-group[0])*rate+27+allowance>=slow_turn):
                group=(time,slow,slow)
                for z in zones:
                    forget(z,OFFSET)
            else:
                group=(group[0],min(group[1],slow),max(group[2],slow))
        following={}
        for z in zones:
            if slow is not None and not (constrain(z,OFFSET,CURRENT,slow+allowance)
                                         and constrain(z,CURRENT,OFFSET,-slow)):
                continue
            # The origin of the first fine revolution is arbitrary for usage.
            if follow_trace or index == 0:
                first = last = winding
            else:
                first = ceil((-z[CURRENT][ZERO]-hi-EPS)/turn)
                last = floor((z[ZERO][CURRENT]-lo+EPS)/turn)
            if last-first>=MAX_ZONES:
                return []
            for k in range(first,last+1):
                candidate=[row[:] for row in z]
                if not (constrain(candidate,ZERO,CURRENT,hi+k*turn)
                        and constrain(candidate,CURRENT,ZERO,-lo-k*turn)):
                    continue
                alternatives=following.setdefault(k,[])
                if any(contains(other,candidate) for other in alternatives):
                    continue
                alternatives[:]=[other for other in alternatives if not contains(candidate,other)]
                alternatives.append(candidate)
        zones=[z for alternatives in following.values() for z in alternatives]
        if not zones or len(zones)>MAX_ZONES:
            return []
    return merged((max(0.,-z[END][START]),max(0.,z[START][END])) for z in zones)


def solve(samples, start, end, rate, turn, slow_turn, allowance, register=None):
    stamps = [s[0] for s in samples]
    if len(samples)<2 or not stamps[0]<=start<end<=stamps[-1]:
        return None
    centers = [(s[2]+s[3])/2 for s in samples]
    trace = unwrapped(centers, turn)
    times = [s[1] for s in samples]
    clock = [(s[1],s,round((value-center)/turn)) for s,center,value in zip(samples,centers,trace)]
    for wall,tag in ((start,START),(end,END)):
        clock.append((pointer_at(times,stamps,wall),tag,None))
    clock.sort(key=lambda record: record[0])

    delta = pointer_at(trace,stamps,end) - pointer_at(trace,stamps,start)
    spacings = [b-a for a,b in zip(times,times[1:])]
    typical = median(spacings)
    # Do not extrapolate smooth motion across missing samples. An independent
    # measurement can still resolve the change if the constraints agree on it.
    sparse = any(stamps[i]<end and start<stamps[i+1] and
                 (len(samples)==2 or elapsed>=2*typical) and
                 rate*elapsed+samples[i][3]-samples[i][2]+samples[i+1][3]-samples[i+1][2]>=turn
                 for i,elapsed in enumerate(spacings))
    if sparse:
        if register is not None:
            # Both register ticks are bracketed by identified photos. Report their
            # difference when it agrees with the observed fine and slow dial path.
            # The resulting whisker is conditional on that register estimate.
            use, lower, upper = register
            for lo,hi in project(clock,rate,turn,slow_turn,allowance,follow_trace=True):
                lo,hi=max(lo,lower),min(hi,upper)
                if lo<=use<=hi and hi-lo<turn:
                    return dict(use=use,bands=[[lo,hi]],basis='register')
        bands = project(clock,rate,turn,slow_turn,allowance,follow_trace=False)
        if len(bands)==1:
            lo,hi = bands[0]
            if hi-lo<turn:
                use = delta + round(((lo+hi)/2-delta)/turn)*turn
                return dict(use=max(lo,min(hi,use)),bands=[[lo,hi]])
        return dict(use=None,bands=[],reason="insufficient_motion_samples")
    travel = slow_travel(samples,start,end,rate,slow_turn,allowance)
    if travel is None or abs(travel-delta)<=allowance:
        bands = project(clock,rate,turn,slow_turn,allowance,follow_trace=True)
        if bands:
            lo,hi = bands[0]
            return dict(use=max(lo,min(hi,delta)),bands=[[lo,hi]])

    # Only independent slow-dial travel can justify recovering missed fine turns.
    # A meter capacity or a partial turn inferred solely at a clock boundary cannot.
    unknown = dict(use=None,bands=[],reason="unsupported_dial_motion")
    if travel is None:
        return unknown
    turns = round((travel-delta)/turn)
    if turns<=0:
        return unknown
    estimate = delta + turns*turn
    bands = project(clock,rate,turn,slow_turn,allowance,follow_trace=False)
    for lo,hi in bands:
        if lo-EPS<=estimate<=hi+EPS and hi-lo<turn:
            return dict(use=max(lo,min(hi,estimate)),bands=[[lo,hi]])
    return unknown
