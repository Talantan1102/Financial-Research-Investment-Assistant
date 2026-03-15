#!/usr/bin/env python3
"""运行 GRPO 训练数据合成"""
import sys
import os

sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/AgentFlow')
sys.path.insert(0, '/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend')

os.environ['DASHSCOPE_API_KEY'] = 'sk-946dc6cdc78b40829f826a0ca3fb7382'
os.environ['TUSHARE_API_TOKEN'] = '9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088'
os.environ['TUSHARE_API_URL'] = 'http://lianghua.nanyangqiankun.top'

from synthesis.pipeline import main

if __name__ == "__main__":
    sys.argv = ['pipeline.py', '--config', 'configs/synthesis/finance_research_config.json']
    main()
