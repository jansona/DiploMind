"""Opt-in review browser fixture: explicit mock plus one simulated faulty AI.

No API/credentials. England emits a same-destination collision; its single review
returns None. This verifies normal multiplayer flow survives review failure.
"""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from diplomind.config import Config
import diplomind.config as config
from diplomind.gateway import Gateway
from diplomind.schemas import OrderSet

OUT=ROOT/'artifacts/preflight-e2e'
COUNTS={'initial_faults':0,'review_failures':0}
CFG=Config(api='mock',model='offline-simulation',api_key=None,rounds=1,order_preflight_review=True)
config.load=lambda:CFG

class FaultGateway(Gateway):
    @classmethod
    def from_config(cls,cfg): return cls(api='mock',model=cfg.model,api_key=None)
    async def achat(self,messages,schema,tag='',**kwargs):
        if tag=='ENGLAND:order' and schema is OrderSet:
            COUNTS['initial_faults']+=1
            out=OrderSet(orders=['F EDI - NTH','F LON - NTH','A LVP - YOR'])
        elif tag=='ENGLAND:order_review' and schema is OrderSet:
            assert kwargs.get('retry')==0
            COUNTS['review_failures']+=1
            out=None
        else:return await super().achat(messages,schema,tag=tag,**kwargs)
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'fault-counts.json').write_text(json.dumps(COUNTS))
        return out

from diplomind import session
session.Gateway=FaultGateway
session.Session.SAVES=OUT/'saves'
from diplomind.web import app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8732,access_log=False,timeout_graceful_shutdown=3)
