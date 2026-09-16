import json
import tempfile
import unittest
import asyncio
from pathlib import Path
from fastapi import FastAPI
from phone_demo_library import install_phone_demo_library


class PhoneDemoTests(unittest.TestCase):
    def test_catalog_video_range_and_unknown_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'phone-01';folder.mkdir()
            payload={'id':'phone-01','analysisStatus':'not_analyzed',
                     'synchronizationStatus':'unverified','fsr':None}
            (folder/'manifest.json').write_text(json.dumps(payload))
            (folder/'frontal.mp4').write_bytes(b'0123456789')
            app=FastAPI();install_phone_demo_library(app,directory)
            def get(path,headers=()):
                async def run():
                    messages=[]
                    async def receive():return {'type':'http.request','body':b''}
                    async def send(message):messages.append(message)
                    await app({'type':'http','asgi':{'version':'3.0'},'method':'GET',
                        'scheme':'http','path':path,'raw_path':path.encode(),
                        'query_string':b'','headers':list(headers),'http_version':'1.1',
                        'server':('test',80),'client':('test',1),'root_path':''},receive,send)
                    return messages[0]['status'],b''.join(m.get('body',b'') for m in messages)
                return asyncio.run(run())
            self.assertEqual(json.loads(get('/phone-demos')[1]),[payload])
            self.assertEqual(json.loads(get('/phone-demos/phone-01')[1]),payload)
            self.assertEqual(get('/phone-demos/phone-01/frontal.mp4',[(b'range',b'bytes=2-5')]),(206,b'2345'))
            for path in ['/phone-demos/phone-01/manifest.mp4','/phone-demos/unknown/frontal.mp4',
                         '/phone-demos/phone-02','/phone-demos/phone-01/sagittal.mp4']:
                self.assertEqual(get(path)[0],404)


if __name__=='__main__':unittest.main()
