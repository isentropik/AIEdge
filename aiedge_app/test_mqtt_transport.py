"""Actual Paho client against a loopback MQTT 3.1.1 protocol fixture, not HA."""
import hashlib,json,socket,tempfile,threading,unittest
from datetime import datetime,timezone
from mqtt_output import MqttOutput
from reading_format import validate
from test_reading_format import document

class Broker:
    def __init__(self):
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen(1);self.listener.settimeout(1)
        self.port=self.listener.getsockname()[1];self.done=threading.Event();self.messages=[];self.error=None;self.will=None
        self.thread=threading.Thread(target=self.run);self.thread.start()
    @staticmethod
    def read(sock,n):
        data=b''
        while len(data)<n:
            block=sock.recv(n-len(data))
            if not block:raise EOFError
            data+=block
        return data
    @staticmethod
    def string(data,offset):
        length=int.from_bytes(data[offset:offset+2],'big');start=offset+2
        return data[start:start+length],start+length
    def run(self):
        try:
            while not self.done.is_set():
                try:connection,_=self.listener.accept();break
                except socket.timeout:continue
            else:return
            with connection:
                connection.settimeout(5)
                while not self.done.is_set():
                    header=self.read(connection,1)[0];length=0;shift=0
                    while True:
                        byte=self.read(connection,1)[0];length+=(byte&127)<<shift;shift+=7
                        if not byte&128:break
                        if shift>28:raise ValueError('bad MQTT length')
                    if length>65536:raise ValueError('oversized fixture packet')
                    body=self.read(connection,length);kind=header>>4
                    if kind==1:
                        if body[:7]!=b'\x00\x04MQTT\x04':raise ValueError('unexpected protocol')
                        flags=body[7];identity,offset=self.string(body,10)
                        if flags&4:
                            topic,offset=self.string(body,offset);payload,offset=self.string(body,offset)
                            self.will=(topic.decode(),payload.decode(),bool(flags&32),(flags>>3)&3)
                        connection.sendall(b'\x20\x02\x00\x00')
                    elif kind==8:connection.sendall(b'\x90\x03'+body[:2]+b'\x01')
                    elif kind==3:
                        topic,offset=self.string(body,0);qos=(header>>1)&3;mid=body[offset:offset+2] if qos else b'';offset+=2 if qos else 0
                        self.messages.append((topic.decode(),body[offset:].decode(),qos,bool(header&1)))
                        if qos==1:connection.sendall(b'\x40\x02'+mid)
                    elif kind==12:connection.sendall(b'\xd0\x00')
                    elif kind==14:break
                    else:raise ValueError('unexpected MQTT packet')
        except (EOFError,OSError) as exc:
            if not self.done.is_set():self.error=repr(exc)
        except Exception as exc:self.error=repr(exc)
    def close(self):
        self.done.set();self.listener.close();self.thread.join(6)
        if self.thread.is_alive():raise RuntimeError('fixture broker did not stop')

class TransportTests(unittest.TestCase):
    def test_actual_client_discovery_qos_and_graceful_offline(self):
        broker=Broker()
        with tempfile.TemporaryDirectory() as directory:
            doc=document([1000,100]);revision=validate(doc)[1]
            snapshot={'format':doc,'latest':{'captured_at':datetime.now(timezone.utc).isoformat(),'sha256':'b'*64},
                      'reading':{'state':'estimated','value':120,'source_sha256':'b'*64,'format_id':revision,'unit':'ft3'}}
            worker=MqttOutput(directory,lambda:snapshot,30,provider=lambda:{'host':'127.0.0.1','port':broker.port,'ssl':False,'username':'fixture','password':'test'})
            try:
                worker.publish_snapshot(snapshot)
                self.assertEqual(worker.state,'publishing')
                worker.close()
                self.assertEqual(broker.will[1:],('offline',True,1))
                configs=[json.loads(row[1]) for row in broker.messages if row[0].endswith('/config')]
                self.assertEqual(len(configs),1);self.assertNotIn('state_class',configs[0])
                states=[row for row in broker.messages if row[0].endswith('/state')]
                self.assertEqual(len(states),1);self.assertEqual(json.loads(states[0][1])['value'],120)
                self.assertEqual(states[0][2:],(1,False))
                self.assertEqual(broker.messages[-1][1],'offline')
            finally:worker.close();broker.close()
        self.assertIsNone(broker.error)

if __name__=='__main__':unittest.main()
