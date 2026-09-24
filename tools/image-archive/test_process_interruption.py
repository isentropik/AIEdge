"""Abrupt receiver-process exit on disposable files, not physical power loss."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from image_archive_store import ArchiveConflict, digest, store_capture

CHILD = r'''
import json, os, sys
from pathlib import Path
import image_archive_store as store
root=Path(sys.argv[1]);mode=sys.argv[2]
fixture=json.loads((root/'fixture.json').read_text())
image=bytes.fromhex(fixture['image']);metadata=fixture['metadata']
original_write=store.write_immutable
original_link=store.publish_no_replace
def write(path,data):
    result=original_write(path,data)
    if mode=='after_blob' and path.parent.name=='blobs':os._exit(73)
    return result
def link(source,destination):
    if Path(destination).parent.name=='captures':
        if mode=='before_record_link':os._exit(73)
        if mode=='after_record_link':
            original_link(source,destination);os._exit(73)
    return original_link(source,destination)
store.write_immutable=write;store.publish_no_replace=link
receipt=store.store_capture(root,metadata,image)
(root/'receipt.json').write_text(json.dumps(receipt))
'''


class InterruptionTests(unittest.TestCase):
    def test_retry_after_abrupt_process_exit(self):
        for mode in ('after_blob', 'before_record_link', 'after_record_link'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='aiedge-process-test-') as directory:
                root=Path(directory)
                image=b'synthetic storage fixture; not a training image'
                metadata=dict(version=1,device_id='fixture',boot_id='boot',capture_us=123,
                    capture_utc=None,image_sha256=digest(image),image_bytes=len(image),
                    firmware_sha256='1'*64,model_sha256='2'*64,
                    calibration_sha256='3'*64,settings_sha256='4'*64)
                (root/'fixture.json').write_text(json.dumps({'image':image.hex(),'metadata':metadata}))
                child=subprocess.run([sys.executable,'-c',CHILD,str(root),mode],
                    cwd=Path(__file__).resolve().parent,capture_output=True,timeout=20)
                self.assertEqual(child.returncode,73,child.stderr.decode(errors='replace'))
                self.assertFalse((root/'receipt.json').exists())
                self.assertEqual(next((root/'blobs').glob('*.image')).read_bytes(),image)
                before=list((root/'captures').glob('*.json'))
                self.assertEqual(len(before),int(mode=='after_record_link'))
                pending=list(root.rglob('.pending-*'))
                expected = int(mode=='before_record_link' or (mode=='after_record_link' and os.name!='nt'))
                self.assertEqual(len(pending),expected)
                receipt=store_capture(root,metadata,image)
                self.assertEqual(receipt['duplicate'],mode=='after_record_link')
                self.assertTrue(receipt['verified_readback'])
                self.assertFalse(receipt['training_eligible'])
                self.assertEqual(receipt['review_status'],'unreviewed')
                self.assertEqual(len(list((root/'captures').glob('*.json'))),1)
                self.assertEqual(len(list((root/'blobs').glob('*.image'))),1)
                record=next((root/'captures').glob('*.json'))
                preserved=record.read_bytes()
                self.assertEqual(digest(preserved),receipt['record_sha256'])
                self.assertEqual(json.loads(preserved)['metadata'],metadata)
                self.assertTrue(store_capture(root,metadata,image)['duplicate'])
                with self.assertRaises(ArchiveConflict):
                    store_capture(root,{**metadata,'model_sha256':'5'*64},image)
                self.assertEqual(record.read_bytes(),preserved)
                self.assertEqual(list(root.rglob('.pending-*')),pending)


if __name__=='__main__':unittest.main()
