"""Mock 博查搜索服务

利用大模型能力生成模拟的搜索结果数据，格式与博查API返回格式完全一致。
用于降低API调用成本，同时保留切换到真实API的能力。
"""

import asyncio
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from app.config.llm_config import LLMConfig


class BochaWebPage(BaseModel):
    """博查API webPages.value 单项格式"""

    name: str = Field(..., min_length=5, max_length=80, description="文章标题")
    url: str = Field(..., pattern=r"^https?://", description="文章URL")
    siteName: str = Field(..., min_length=2, max_length=30, description="网站名称")
    datePublished: str = Field(
        ..., pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", description="发布日期"
    )
    summary: str = Field(..., min_length=20, max_length=300, description="AI生成的内容摘要")
    snippet: str = Field(..., min_length=10, max_length=200, description="原文片段")

    @field_validator("url")
    @classmethod
    def validate_url_starts_with_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("URL必须以https://开头")
        return v


class BochaSearchResponse(BaseModel):
    """博查API响应格式"""

    webPages: dict[str, Any]


class MockBochaService:
    """
    Mock 博查搜索服务

    使用LLM生成模拟搜索结果，格式与真实博查API完全一致。
    支持四类搜索：新闻、公告、行业新闻、研报。
    """

    # 搜索类型对应的中文描述
    SEARCH_TYPE_DESCRIPTIONS = {
        "news": "股票新闻",
        "announcement": "公司公告",
        "industry": "行业新闻",
        "report": "研究报告",
    }

    # 模拟网站来源配置
    SOURCES = {
        "news": [
            ("新浪财经", "finance.sina.com.cn"),
            ("东方财富网", "finance.eastmoney.com"),
            ("证券时报", "stcn.com"),
            ("雪球", "xueqiu.com"),
            ("腾讯财经", "finance.qq.com"),
            ("网易财经", "money.163.com"),
        ],
        "announcement": [
            ("巨潮资讯网", "cninfo.com.cn"),
            ("上海证券交易所", "sse.com.cn"),
            ("深圳证券交易所", "szse.cn"),
            ("证券时报", "stcn.com"),
        ],
        "industry": [
            ("财新网", "caixin.com"),
            ("第一财经", "yicai.com"),
            ("界面新闻", "jiemian.com"),
            ("36氪", "36kr.com"),
            ("中国证券报", "cs.com.cn"),
            ("上海证券报", "cnstock.com"),
        ],
        "report": [
            ("中信证券", "citics.com"),
            ("中金公司", "cicc.com"),
            ("国泰君安", "gtja.com"),
            ("海通证券", "htsec.com"),
            ("华泰证券", "htsc.com.cn"),
            ("招商证券", "cmschina.com"),
        ],
    }

    def __init__(self):
        config = LLMConfig()
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.model = "deepseek-v4-flash"

    async def generate_search_results(
        self,
        query: str,
        search_type: Literal["news", "announcement", "industry", "report"],
        count: int = 10,
        freshness: str = "Month",
    ) -> dict[str, Any]:
        """
        生成mock搜索结果，返回与博查API相同格式。

        Args:
            query: 搜索查询
            search_type: 搜索类型
            count: 返回结果数量
            freshness: 时间范围 (Day, Week, Month, Year)

        Returns:
            符合博查API格式的响应数据

        Raises:
            ValueError: 如果LLM返回格式不正确
            Exception: LLM调用异常直接抛出
        """
        prompt = self._build_prompt(query, search_type, count, freshness)
        max_tokens = min(500 + count * 400, 4000)

        # 异步调用LLM
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的财经信息生成助手。请严格按照用户要求的JSON格式返回数据，不要包含任何markdown代码块标记或其他说明文字。",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM返回内容为空")

        import json

        try:
            raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回非有效JSON: {str(e)}")

        # 使用Pydantic严格校验
        validated_data = self._validate_response(raw_data, count)
        return validated_data

    def _build_prompt(
        self,
        query: str,
        search_type: Literal["news", "announcement", "industry", "report"],
        count: int,
        freshness: str,
    ) -> str:
        """构建针对搜索类型的prompt"""

        type_desc = self.SEARCH_TYPE_DESCRIPTIONS.get(search_type, "搜索结果")
        sources = self.SOURCES.get(search_type, self.SOURCES["news"])

        # 生成时间范围描述
        freshness_desc = {
            "Day": "最近1天内",
            "Week": "最近1周内",
            "Month": "最近1个月内",
            "Year": "最近1年内",
        }.get(freshness, "最近1个月内")

        # 构建来源列表文本
        sources_text = "\n".join([f"- {name} (域名: {domain})" for name, domain in sources])

        # 根据搜索类型构建特定提示
        if search_type == "news":
            content_guidance = """
内容要求：
1. 生成时效性强的股票新闻，涵盖业绩发布、产品创新、市场拓展、战略合作、股价波动等角度
2. 每条新闻标题应简洁有力，突出关键信息
3. summary字段：80-150字的摘要，概述新闻要点
4. snippet字段：50-100字的片段，可以是summary的精华部分或关键引言
5. 日期应在指定时间范围内，分布合理"""

        elif search_type == "announcement":
            content_guidance = """
内容要求：
1. 生成正式公告风格的内容，区分定期报告（年报/季报）、重大事项、信息披露
2. 使用正式的公告语言，包含具体数据（如营收、净利润、股份数量等）
3. summary字段：80-150字，概括公告核心内容
4. snippet字段：50-100字，引用公告中的关键表述
5. 公告编号格式如：2024-XXX"""

        elif search_type == "industry":
            content_guidance = """
内容要求：
1. 生成行业动态和政策新闻，涵盖政策变化、市场趋势、技术进展、竞争格局等
2. 从宏观和行业视角分析问题
3. summary字段：80-150字，总结行业动态要点
4. snippet字段：50-100字，引用关键数据或观点
5. 可包含专家观点、市场预测等内容"""

        else:  # report
            content_guidance = """
内容要求：
1. 生成专业研报风格，包含投资评级（买入/增持/中性/卖出）、目标价、核心观点
2. 模拟知名券商研报格式，包含具体财务数据和估值分析
3. summary字段：80-150字，概述评级理由和核心投资逻辑
4. snippet字段：50-100字，引用分析师关键观点或盈利预测数据
5. 标题应包含评级关键词，如"买入"、"增持"、"首次覆盖"等"""

        prompt = f"""请为以下搜索查询生成{count}条模拟的{type_desc}搜索结果。

搜索查询：{query}
时间范围：{freshness_desc}

可用来源网站（每条结果选择一个）：
{sources_text}

{content_guidance}

格式要求：
必须返回严格符合以下JSON结构的数据：
{{
    "webPages": {{
        "value": [
            {{
                "name": "文章标题（5-80字）",
                "url": "https://来源域名/文章路径",
                "siteName": "来源网站名称",
                "datePublished": "YYYY-MM-DDTHH:MM:SS",
                "summary": "AI生成的内容摘要（80-150字）",
                "snippet": "原文片段（50-100字）"
            }}
        ]
    }}
}}

约束条件：
1. 生成{count}条结果（不多不少）
2. URL必须以https://开头，域名从提供的来源中选择
3. datePublished必须是YYYY-MM-DDTHH:MM:SS格式，日期在{freshness_desc}
4. 所有字段都必须有值，不能为空字符串
5. 内容应多样化，避免重复
6. 确保数据看起来真实可信，包含具体数字和细节"""

        return prompt

    def _validate_response(self, raw_data: dict[str, Any], expected_count: int) -> dict[str, Any]:
        """
        使用Pydantic逐条校验webPages.value，确保格式完全正确

        Args:
            raw_data: LLM返回的原始数据
            expected_count: 期望的结果数量

        Returns:
            校验通过的数据

        Raises:
            ValueError: 校验失败时抛出
        """
        if not isinstance(raw_data, dict):
            raise ValueError(f"LLM返回必须是JSON对象，实际为: {type(raw_data).__name__}")

        if "webPages" not in raw_data:
            raise ValueError(f"LLM返回缺少webPages字段，实际字段: {list(raw_data.keys())}")

        web_pages = raw_data["webPages"]
        if not isinstance(web_pages, dict):
            raise ValueError(f"webPages必须是对象，实际为: {type(web_pages).__name__}")

        if "value" not in web_pages:
            raise ValueError(f"webPages缺少value字段，实际字段: {list(web_pages.keys())}")

        items = web_pages["value"]
        if not isinstance(items, list):
            raise ValueError(f"webPages.value必须是数组，实际为: {type(items).__name__}")

        if len(items) == 0:
            raise ValueError("webPages.value为空数组")

        validated_items = []
        for idx, item in enumerate(items):
            try:
                validated_item = BochaWebPage(**item)
                validated_items.append(validated_item.model_dump())
            except Exception as e:
                raise ValueError(f"第{idx + 1}条结果校验失败: {str(e)}")

        return {"webPages": {"value": validated_items}}
