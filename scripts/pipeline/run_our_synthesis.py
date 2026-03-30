#!/usr/bin/env python3
"""
使用我们的 Seed 运行 Agent Flow 数据合成
"""

import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(_project_root))

from synthesis import synthesize

print("="*70)
print("🚀 Agent Flow 数据合成 - 使用我们的 Seed")
print("="*70)

# 运行合成
synthesize(config_path="configs/synthesis/our_config.json")

print("\n✅ 合成完成！")
print("输出目录: results/our_synthesis/")
