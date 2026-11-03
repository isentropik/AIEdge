from contextlib import closing
from pathlib import Path
import hashlib
import json
import re

from bench_collector import drain
from bench_store import BurstStore

def binding(context,orientation):
    if type(orientation) is not int or not 0<=orientation<=3:
        raise ValueError('bench orientation required')
    return hashlib.sha256(json.dumps([context,orientation],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def split_ticket(ticket):
    if not isinstance(ticket,str) or not re.fullmatch(r'[0-9a-f]{32}\.[1-9][0-9]{0,9}',ticket):
        raise ValueError('invalid batch ticket')
    device,number=ticket.split('.')
    if int(number)>=2**32-1:raise ValueError('batch counter exhausted')
    return device,int(number)

def gate(collector,transport,path,context,orientation,*,start_on_boot=None,count=1):
    if type(count) is not int or not 1<=count<=2:raise ValueError('trial must contain one or two batches')
    with closing(BurstStore(Path(path).resolve().as_uri()+'?mode=rw',binding(context,orientation),existing=True)) as store:
        entry=store.entry()
        if entry is None:
            if start_on_boot is None:
                if transport.status()['started']:raise ValueError('unowned camera session')
                return
            device,number=split_ticket(start_on_boot)
            store.final_generation=number+count-1
            if store.final_generation>=2**32-1:raise ValueError('batch counter exhausted')
            drain(collector,transport,store,expected_orientation=str(orientation),expected_boot=start_on_boot)
        else:
            first,target=store.db.execute('SELECT boot,target FROM run ORDER BY sequence LIMIT 1').fetchone()
            if start_on_boot is not None and (start_on_boot!=first or split_ticket(first)[1]+count-1!=target):
                raise ValueError('existing trial has different admission scope')
            store.final_generation=target
        while True:
            ticket,bound,owner,result=store.entry()
            if bound!=store.context:raise ValueError('buffered trial configuration changed')
            device,number=split_ticket(ticket)
            transport.owner=owner
            transport.batch=ticket
            if result is None:
                drain(collector,transport,store,resume=True,expected_orientation=str(orientation))
                continue
            store.verify_boundary(ticket,collector.store,False)
            phase=store.db.execute('SELECT retiring FROM run WHERE boot=?',(ticket,)).fetchone()[0]
            successor=f'{device}.{number+1}'
            state=transport.status()
            if phase==2 and number==store.final_generation:
                if state['started']:raise ValueError('unowned active acquisition')
                return
            if state['boot']==ticket:
                if phase or not (state['owned'] and state['started'] and state['finished'] and state['attempted']==5):
                    raise ValueError('unresolved batch retirement')
                expected=[i for i in range(5) if state['failed_mask']&(1<<i)]
                if json.loads(result)['omitted']!=expected:raise ValueError('camera omission ledger changed')
                with store.db:store.db.execute('UPDATE run SET retiring=1 WHERE boot=?',(ticket,))
                state=transport.retire()
            elif phase==0:
                raise ValueError('camera advanced without local retirement')
            if state['boot']!=successor or state['started']:
                raise ValueError('missing free successor ticket')
            with store.db:store.db.execute('UPDATE run SET retiring=2 WHERE boot=?',(ticket,))
            if number==store.final_generation:return
            # Verify no intervening ordinary capture before admitting an adjacent batch.
            store.verify_boundary(ticket,collector.store,True)
            transport.batch=None
            transport.owner=None
            drain(collector,transport,store,expected_orientation=str(orientation),expected_boot=successor)

def needs_camera_preflight(directory,ordinary_store,requested):
    """Skip camera bench routes on an unactivated installation."""
    path=Path(directory)/'burst-bench.sqlite3'
    provisioned=(Path(directory)/'burst-baseline.json').is_file()
    admissions=0
    if ordinary_store is not None:
        with ordinary_store.connect() as db:
            table=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='buffered_batch_admissions'").fetchone()
            if table:admissions=db.execute("SELECT count(*) FROM buffered_batch_admissions").fetchone()[0]
    if not path.is_file():
        if admissions or provisioned:raise ValueError('missing provisioned batch ledger')
        return bool(requested)
    if not provisioned:raise ValueError('missing camera baseline')
    with closing(BurstStore(path.resolve().as_uri()+'?mode=rw','',existing=True)) as store:
        runs=store.db.execute("SELECT count(*) FROM run").fetchone()[0]
        if runs!=admissions:raise ValueError('inconsistent batch admission count')
        if runs==0:return bool(requested)
        history=store.db.execute('SELECT boot,context,result,retiring,target FROM run ORDER BY sequence').fetchall()
        first,_,_,_,target=history[0]
        device,first_number=split_ticket(first)
        if len(history)==2 and target==first_number+1 and all(row[3]==2 for row in history):
            if requested:
                expected=json.loads((Path(directory)/'burst-baseline.json').read_text(encoding='utf-8'))
                if requested!=first+'@'+expected['revision']:
                    raise ValueError('completed buffered trial option differs')
            for index,(ticket,context,sealed,phase,last) in enumerate(history):
                if ticket!=f'{device}.{first_number+index}' or last!=target or context!=history[0][1]:
                    raise ValueError('completed buffered trial identity changed')
                if json.loads(sealed)!={'committed':[0,1,2,3,4],'omitted':[]}:
                    raise ValueError('completed buffered trial evidence missing')
                if store.db.execute('SELECT count(*) FROM frames WHERE boot=?',(ticket,)).fetchone()!=(5,):
                    raise ValueError('completed buffered trial frames missing')
                store.context=context
                store.verify_boundary(ticket,ordinary_store,False)
            return False
        return True
