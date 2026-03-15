#!/usr/bin/env python3
"""启动 Sandbox Server"""
import sys
import os

os.environ['TUSHARE_API_TOKEN'] = '9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088'
os.environ['TUSHARE_API_URL'] = 'http://lianghua.nanyangqiankun.top'

sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/AgentFlow')
sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend')

from sandbox.server.config_loader import ConfigLoader

if __name__ == "__main__":
    config_path = "configs/sandbox-server/finance_research_config.json"
    loader = ConfigLoader()
    loader.load(config_path)
    server = loader.create_server(host="0.0.0.0", port=18890)
    print("Starting sandbox server on http://127.0.0.1:18890")
    server.run()
