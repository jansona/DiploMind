"""Isolated native QA server: configuration is literal mock, never read from disk."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from diplomind.config import Config
import diplomind.config as config
CFG=Config(api='mock',model='offline-simulation',api_key=None,rounds=1)
config.load=lambda:CFG
from diplomind.session import Session
Session.SAVES=ROOT/'artifacts/performance/isolated-browser-saves'
from diplomind.web import app
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=8732,access_log=False)
