"""Clock-interval gas usage from joint fine and slow dial observations."""
from bisect import bisect_left
from math import ceil, floor, inf, isfinite

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


def pointer_at(rows, stamps, t, period):
    j = bisect_left(stamps,t)
    if j < len(rows) and stamps[j] == t:
        return rows[j]
    if j == 0 or j == len(rows):
        return None
    delta = (rows[j]-rows[j-1]+period/2) % period - period/2
    return rows[j-1] + delta*(t-stamps[j-1])/(stamps[j]-stamps[j-1])


def solve(samples, start, end, rate, turn, slow_turn, allowance):
    """Each row is (wall ms, camera seconds, fine lower, fine upper, slow center).

    Extending an exposure through a clock tick preserves both sides of that
    tick. Distinct winding paths can only merge when one contains the other.
    """
    stamps = [s[0] for s in samples]
    if len(samples)<2 or not stamps[0]<=start<end<=stamps[-1]:
        return None
    clock = [(s[1],s) for s in samples]
    for wall,tag in ((start,START),(end,END)):
        j = bisect_left(stamps,wall)
        t = samples[j][1]
        if stamps[j]!=wall:
            before=samples[j-1]
            t=before[1]+(t-before[1])*(wall-before[0])/(stamps[j]-before[0])
        clock.append((t,tag))
    clock.sort(key=lambda pair:pair[0])
    zones = [empty()]
    previous = clock[0][0]
    coarse = []
    group = None
    for index,(time,record) in enumerate(clock):
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
            coarse.append((wall,slow))
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
            first=ceil((-z[CURRENT][ZERO]-hi-EPS)/turn) if index else 0
            last=floor((z[ZERO][CURRENT]-lo+EPS)/turn) if index else 0
            if last-first>=MAX_ZONES:
                return dict(use=None,bands=[],reason="optical_work_limit")
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
        if not zones:
            return dict(use=None,bands=[],reason="inconsistent_observations")
        if len(zones)>MAX_ZONES:
            return dict(use=None,bands=[],reason="optical_work_limit")
    bands=merged((max(0.,-z[END][START]),max(0.,z[START][END])) for z in zones)
    centers=[(s[2]+s[3])/2 for s in samples]
    delta=pointer_at(centers,stamps,end,turn)-pointer_at(centers,stamps,start,turn)
    slow_stamps=[wall for wall,_ in coarse]
    unwrapped=[coarse[0][1]] if coarse else []
    for (a,v),(b,w) in zip(coarse,coarse[1:]):
        movement=(w-v+slow_turn/2)%slow_turn-slow_turn/2
        if (b-a)*rate/1000 + 2*allowance >= slow_turn/2:
            break
        unwrapped.append(unwrapped[-1]+movement)
    # Select the winding nearest the observed slow movement; within that winding
    # use the fine pointer's interpolated movement. Ties use the smaller change.
    target=bands[0][0]
    if len(coarse)>=2 and len(unwrapped)==len(coarse):
        opening=pointer_at(unwrapped,slow_stamps,start,slow_turn)
        closing=pointer_at(unwrapped,slow_stamps,end,slow_turn)
        if opening is not None and closing is not None:
            target=max(0.,closing-opening)
    def estimate(band):
        lo,hi=band
        turns=round((min(hi,max(lo,target))-delta)/turn)
        return max(lo,min(hi,delta+turns*turn))
    use=min((estimate(b) for b in bands),key=lambda value:(abs(value-target),value))
    return dict(use=use,bands=bands)
