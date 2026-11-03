"""Isolated finite-burst reader. Commit targets a bench store, separate from usage."""
import hashlib
import re
import time
from buffered_ingest import commit_slot,finish_slots
from capture import validate as validate_jpeg
from capture_clock import parse as parse_clock

def drain(collector, transport, store, limit_seconds=80, *, expected_orientation, resume=False, expected_boot=None):
    if expected_orientation not in ('0','1','2','3'):raise ValueError('unknown configured orientation')
    deadline=time.monotonic()+limit_seconds
    # Same acquisition order as Collector.once. The scheduled loop waits outside
    # the control lock, so its operation-lock failure path cannot strand it.
    with collector.control_lock, collector.camera.operation():
        if collector.stop.is_set() or collector.shutdown.is_set() or collector.transfer_attempt is not None:
            raise ValueError('collector not idle for bench')
        try:
            collector.camera.require_capture()
            if resume:
                entry=store.entry()
                if entry is None or entry[1]!=store.context or entry[3] is not None:
                    raise ValueError('unfinished context missing or changed')
                transport.owner=entry[2]
            initial=transport.status()
            boot=initial['boot']
            if not re.fullmatch(r'[0-9a-f]{32}\.[1-9][0-9]{0,9}',boot):
                raise ValueError('invalid camera boot identity')
            transport.batch=boot
            if resume:
                store.require_open(boot)
                store.verify_boundary(boot,collector.store,True)
                if not initial['started'] or not initial['owned']:
                    raise ValueError('uncertain start; cannot reissue')
            else:
                if expected_boot!=boot:raise ValueError('reviewed camera boot differs')
                if initial['started']:raise ValueError('bench requires unused boot session')
                # Reserve headroom for the complete finite batch before the start POST.
                collector.store.require_space()
                store.intent(boot,collector.store)
                transport.owner=store.entry()[2]
                transport.start(initial)
            rows=store.saved(boot)
            committed=set(rows)
            epoch,previous_tick=rows[max(rows)] if rows else (None,None)
            while time.monotonic()<deadline:
                state=transport.status()
                if state['boot']!=boot or not state['started'] or not state['owned']:
                    raise ValueError('camera session changed')
                if state['failed_mask']:
                    raise ValueError('unclassified capture slot failure; batch held')
                frame=transport.head()
                if frame is None:
                    if state['finished']:
                        mask=state['failed_mask']
                        if type(mask) is not int or not 0<=mask<32 or state['attempted']!=5:
                            raise ValueError('invalid final status')
                        failed={i for i in range(5) if mask & (1<<i)}
                        if committed.intersection(failed) or committed|failed != set(range(5)):
                            raise ValueError('unaccounted capture slot')
                        result=dict(committed=sorted(committed),omitted=sorted(failed))
                        finish_slots(collector.store,boot,store.context,committed,failed)
                        store.finish(boot,result)
                        return result
                    time.sleep(.05)
                    continue
                data,h=frame
                if h.get_all('X-AIEdge-Image-Orientation') != [expected_orientation]:
                    raise ValueError('unexpected frame orientation')
                frame_id,utc,digest=validate_jpeg(data,h)
                if h.get_all('Content-Length')!=[str(len(data))] or h.get_all('Content-Type')!=['image/jpeg']:
                    raise ValueError('invalid JPEG framing')
                slot_header=h.get_all('X-AIEdge-Burst-Slot') or []
                if len(slot_header)!=1 or slot_header[0] not in list('01234'):
                    raise ValueError('invalid burst slot')
                slot=int(slot_header[0])
                clock=parse_clock(h)
                if clock is None or (epoch is not None and epoch!=clock[0]):
                    raise ValueError('capture clock changed')
                replay=slot in committed
                if replay and (slot!=max(committed) or clock!=rows[slot]):
                    raise ValueError('frame order changed')
                if not replay and committed and (slot<=max(committed) or clock[1]<=previous_tick):
                    raise ValueError('frame order changed')
                epoch,previous_tick=clock
                # Status and head are separate HTTP responses. The producer can
                # report an omission between them. Check again before admission.
                missing=range(max(committed,default=-1)+1,slot)
                if any(not state['failed_mask'] & (1<<i) for i in missing):
                    state=transport.status()
                    if state['boot']!=boot or not state['owned'] or not state['started']:
                        raise ValueError('burst owner changed before slot admission')
                if state['failed_mask']:
                    raise ValueError('unclassified capture slot failure; batch held')
                store.commit(boot,slot,frame_id,utc,clock,digest,data)
                commit_slot(collector.store,collector.camera.origin,boot,store.context,slot,data,h,state)
                rows[slot]=clock
                committed.add(slot)
                transport.ack(frame_id,digest)
            raise TimeoutError('burst deadline')
        except Exception:
            # No automatic return to the legacy producer after an uncertain start,
            # write, or ACK. Reconciliation only drains an already-started batch.
            collector.recovery_state='held'
            collector.stop.set()
            raise
