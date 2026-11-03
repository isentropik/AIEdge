"""HTTP client for the finite local bench protocol. Only the caller admits a burst."""
import json
import re
import time
from urllib.request import Request

class BurstTransport:
    def __init__(self,camera,deadline,*,checkpoint=lambda:None):
        self.checkpoint=checkpoint
        self.owner=None
        self.batch=None
        self.camera=camera
        self.deadline=deadline

    def request(self,path,headers=None,post=False,maximum=2048):
        self.checkpoint()
        camera=self.camera
        fields=dict(headers or {})
        if self.batch:fields['X-AIEdge-Batch']=self.batch
        if self.owner:fields["X-AIEdge-Burst-Owner"]=self.owner
        if camera.token: fields['Authorization']='Bearer '+camera.token
        elif camera.basic: fields['Authorization']='Basic '+camera.basic
        req=Request(camera.origin+'/api/v1/burst/'+path,headers=fields,
                    data=b'' if post else None,method='POST' if post else 'GET')
        req.aiedge_deadline=min(self.deadline,time.monotonic()+20)
        with camera.opener.open(req,timeout=5) as r:
            if path=='frame' and r.status==204:
                if r.headers.get_all('X-AIEdge-Batch')!=[self.batch]:raise ValueError('stale empty batch response')
                return None
            if r.status!=200:raise ValueError('unexpected burst response')
            lengths=r.headers.get_all('Content-Length') or []
            if (len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                    or not 0<int(lengths[0])<=maximum or r.headers.get_all('Transfer-Encoding')):
                raise ValueError('unbounded burst body')
            size=int(lengths[0])
            data=r.read(size)
            if len(data)!=size:raise EOFError('truncated burst body')
            return data,r.headers

    def status(self):
        return self.parse_state(self.request('status'))

    def parse_state(self,response):
        raw,h=response
        doc=json.loads(raw)
        boots=h.get_all('X-AIEdge-Burst-Boot') or []
        if len(boots)!=1 or any(type(doc[k]) is not bool for k in ('started','finished')):
            raise ValueError('invalid burst status')
        worker=h.get_all('X-AIEdge-Burst-Worker')
        if worker!=['none']:
            if worker in (['camera_in_use'],['task_unavailable'],['capture_slot_failed']):
                raise ValueError('burst worker failed: '+worker[0])
            raise ValueError('invalid worker status')
        owned=h.get_all('X-AIEdge-Burst-Owned')
        if owned not in (['1'],['0']):raise ValueError('missing owner status')
        import re
        if not re.fullmatch('[0-9a-f]{32}',boots[0]) or any(type(doc[k]) is not int or not 0<=doc[k]<=m for k,m in [('attempted',5),('failed_mask',31)]) or (not doc['started'] and (doc['attempted'] or doc['failed_mask'] or doc['finished'] or owned==['1'])):
            raise ValueError('inconsistent burst status')
        tickets=h.get_all('X-AIEdge-Batch') or []
        until=h.get_all('X-AIEdge-Start-Until') or []
        if len(tickets)!=1 or not re.fullmatch(boots[0]+r'\.[1-9][0-9]{0,9}',tickets[0]):
            raise ValueError('invalid batch identity')
        if len(until)!=1 or not re.fullmatch(r'[1-9][0-9]{0,18}',until[0]):
            raise ValueError('invalid admission expiry')
        return dict(doc,boot=tickets[0],device_boot=boots[0],expiry=until[0],owned=owned==['1'])
    def start(self,state):
        response=self.request('start',{'X-AIEdge-Burst-Boot':state['device_boot'],'X-AIEdge-Start-Until':state['expiry']},post=True)
        self.confirm(response)
    def confirm(self,response):
        state=self.parse_state(response)
        if state['boot']!=self.batch or not state['started'] or not state['owned']:
            raise ValueError('unexpected batch receipt')
    def head(self):
        frame=self.request('frame',maximum=160000)
        if frame is None:return None
        data,headers=frame
        field=headers.get_all('X-AIEdge-Burst-Slot') or []
        if len(field)!=1 or field[0] not in [f'{self.batch}:{slot}' for slot in range(5)]:
            raise ValueError('unexpected batch frame')
        headers.replace_header('X-AIEdge-Burst-Slot',field[0].rsplit(':',1)[1])
        return data,headers
    def ack(self,ident,digest):
        self.confirm(self.request('ack',{'X-AIEdge-Frame-Id':ident,'X-AIEdge-SHA256':digest},post=True))
    def retire(self):
        return self.parse_state(self.request('retire',post=True))
