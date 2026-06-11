"""iOS Calm plotly 主题 —— 代码解释器(run_python)固定画图风格(spec § 4)。

纯 dict / 字符串,**不在此 import plotly** —— executor 主进程不该硬依赖 plotly(它走
optional extra)。子进程 wrapper 在沙箱里 import plotly 时,用 ``ios_template_layout()``
构造 ``go.layout.Template(layout=...)`` 并设为默认模板,用户建的每张图自动继承。
``fig.to_dict()`` 会把模板内联进 ``layout.template``,前端 plotly 直接渲染(前端无需
知道 'ios' 这个名字)。
"""

from __future__ import annotations

# 系统字体栈:plotly 在浏览器渲染,中文交给系统字体(PingFang SC 等),无 matplotlib 乱码坑。
IOS_FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', system-ui, sans-serif"

# 序列轮色(多系列按序轮用)—— iOS 系统色。
IOS_COLORWAY = ["#5E5CE6", "#00C7BE", "#FF9500", "#AF52DE", "#34C759", "#FF2D55"]

# 红涨绿跌(中国习惯)—— 数据语义色,harness 套不了,charting skill 教模型显式用。
IOS_UP = "#FF3B30"
IOS_DOWN = "#34C759"


def ios_template_layout() -> dict:
    """返回 plotly Template 的 layout dict(子进程 wrapper 用它构造 Template)。"""
    axis = {
        "gridcolor": "#F0F0F2",
        "zerolinecolor": "#E5E5EA",
        "linecolor": "#D1D1D6",
        "tickfont": {"color": "#1D1D1F", "size": 12},
        "title": {"font": {"color": "#1D1D1F"}},
    }
    return {
        "colorway": IOS_COLORWAY,
        "font": {"family": IOS_FONT, "color": "#1D1D1F", "size": 13},
        "paper_bgcolor": "#FFFFFF",
        "plot_bgcolor": "#FFFFFF",
        "xaxis": dict(axis),
        "yaxis": dict(axis),
        "title": {"x": 0.0, "xanchor": "left", "font": {"size": 17, "color": "#1D1D1F"}},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        "margin": {"l": 56, "r": 24, "t": 48, "b": 48},
        "colorscale": {"sequential": [[0, "#E8E8FB"], [1, "#5E5CE6"]]},
        "hoverlabel": {
            "bgcolor": "#FFFFFF",
            "bordercolor": "#E5E5EA",
            "font": {"family": IOS_FONT, "color": "#1D1D1F"},
        },
    }


__all__ = ["IOS_FONT", "IOS_COLORWAY", "IOS_UP", "IOS_DOWN", "ios_template_layout"]
