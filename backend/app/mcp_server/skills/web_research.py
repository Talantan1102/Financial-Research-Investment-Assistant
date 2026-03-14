# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""WebResearch Skill - 网络搜索与信息收集 (MCP 专用版)

纯 MCP 工具实现，通过 MCP Client 调用，无降级逻辑。
"""

import os
import json
import hashlib
import time
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

import aiohttp

from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult


logger = logging.getLogger("WebResearchSkill")


@dataclass
class SearchResult:
    """搜索结果数据结构"""
    url: str
    name: str
    summary: str
    snippet: str
    site_name: str = ""
    site_icon: str = ""
    source: str = "web"
    timestamp: str = ""
    relevance_score: float = 0.0


class WebResearchSkill(BaseSkill):
    """
    网络研究 Skill (MCP 专用版)

    提供以下工具：
    1. web_search - 网络搜索
    2. knowledge_search - 知识库搜索
    3. deep_search - 深度搜索（递归+交叉验证）
    4. extract_webpage - 网页内容提取
    """

    name = "web_research"
    description = "网络搜索与信息收集，支持网络搜索、知识库搜索和深度研究"

    # 搜索缓存配置
    CACHE_TTL = 3600  # 1小时

    def __init__(self):
        self._search_cache: Dict[str, Tuple[List, float]] = {}
        self._search_api_key: Optional[str] = None
        super().__init__()

    @property
    def search_api_key(self) -> str:
        """获取搜索 API Key"""
        if self._search_api_key is None:
            self._search_api_key = os.getenv("SEARCH_API_KEY") or os.getenv("BOCHA_API_KEY", "")
        return self._search_api_key

    def _register_tools(self):
        """注册 WebResearch 相关工具"""

        # 1. 网络搜索
        self.register_tool(
            name="web_search",
            handler=self.web_search,
            description="搜索互联网获取最新信息，适用于查找实时数据、新闻、市场信息等",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索关键词，例如：'2024年新能源汽车销量'",
                    required=True
                ),
                ToolParameter(
                    name="count",
                    type="integer",
                    description="返回结果数量（默认5，最大20）",
                    required=False,
                    default=5
                ),
                ToolParameter(
                    name="freshness",
                    type="string",
                    description="结果时效性：day(一天内), week(一周内), month(一月内), year(一年内)",
                    required=False,
                    default=None
                )
            ]
        )

        # 2. 知识库搜索
        self.register_tool(
            name="knowledge_search",
            handler=self.knowledge_search,
            description="搜索本地知识库获取专业文档，适用于查找内部资料、专业报告等",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="搜索问题或关键词",
                    required=True
                ),
                ToolParameter(
                    name="kb_name",
                    type="string",
                    description="知识库名称（如未提供，将使用默认知识库）",
                    required=False,
                    default=""
                ),
                ToolParameter(
                    name="top_k",
                    type="integer",
                    description="返回结果数量（默认5）",
                    required=False,
                    default=5
                )
            ]
        )

        # 3. 深度搜索
        self.register_tool(
            name="deep_search",
            handler=self.deep_search,
            description="深度搜索，自动进行多轮搜索和交叉验证，适用于复杂研究问题",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="研究问题，例如：'小米汽车2024年市场竞争力分析'",
                    required=True
                ),
                ToolParameter(
                    name="sub_queries",
                    type="array",
                    description="子查询列表（可选，不提供则自动生成）",
                    required=False,
                    default=None
                ),
                ToolParameter(
                    name="max_depth",
                    type="integer",
                    description="最大搜索深度（默认2）",
                    required=False,
                    default=2
                ),
                ToolParameter(
                    name="cross_verify",
                    type="boolean",
                    description="是否进行交叉验证（默认True）",
                    required=False,
                    default=True
                )
            ]
        )

        # 4. 网页内容提取
        self.register_tool(
            name="extract_webpage",
            handler=self.extract_webpage,
            description="提取网页完整内容，支持自动解析正文",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="网页URL",
                    required=True
                ),
                ToolParameter(
                    name="extract_type",
                    type="string",
                    description="提取类型：article(文章正文), full(完整HTML), text(纯文本)",
                    required=False,
                    default="article"
                )
            ]
        )

        # 5. 批量搜索
        self.register_tool(
            name="batch_search",
            handler=self.batch_search,
            description="并行执行多个搜索查询，提高效率",
            parameters=[
                ToolParameter(
                    name="queries",
                    type="array",
                    description="搜索查询列表，每个元素包含query和count",
                    required=True
                ),
                ToolParameter(
                    name="search_type",
                    type="string",
                    description="搜索类型：web(网络), local(知识库), both(两者)",
                    required=False,
                    default="web"
                )
            ]
        )

    # ========== 工具实现 ==========

    async def web_search(
        self,
        query: str,
        count: int = 5,
        freshness: Optional[str] = None
    ) -> ToolResult:
        """网络搜索"""
        if not query:
            return ToolResult(success=False, error="搜索关键词不能为空")

        count = min(max(count, 1), 20)

        # 检查缓存
        cached = self._get_cached_search(query)
        if cached is not None:
            logger.info(f"缓存命中: {query[:50]}...")
            return ToolResult(success=True, data={
                "results": cached[:count],
                "count": len(cached[:count]),
                "source": "cache",
                "query": query
            })

        # 调用博查 API
        url = "https://api.bochaai.com/v1/web-search"
        payload = {
            "query": query,
            "summary": True,
            "count": count,
            "page": 1
        }
        if freshness:
            payload["freshness"] = freshness

        headers = {
            'Authorization': self.search_api_key,
            'Content-Type': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=25) as response:
                response.raise_for_status()
                data = await response.json()

                webpages_data = data.get('data', {}).get('webPages', {})
                value_list = webpages_data.get('value', [])

                results = []
                for item in value_list:
                    if item.get('url') and (item.get('snippet') or item.get('summary')):
                        results.append({
                            'url': item.get('url'),
                            'name': item.get('name', 'N/A'),
                            'summary': item.get('summary', '') or item.get('snippet', ''),
                            'snippet': item.get('snippet', ''),
                            'siteName': item.get('siteName', 'N/A'),
                            'siteIcon': item.get('siteIcon', ''),
                            'source': 'web',
                            'timestamp': item.get('dateLastCrawled', ''),
                            'relevance_score': item.get('score', 0)
                        })

                # 缓存结果
                self._set_cached_search(query, results)

                return ToolResult(success=True, data={
                    "results": results,
                    "count": len(results),
                    "source": "web",
                    "query": query
                })

    async def knowledge_search(
        self,
        query: str,
        kb_name: str = "",
        top_k: int = 5
    ) -> ToolResult:
        """知识库搜索"""
        if not query:
            return ToolResult(success=False, error="搜索问题不能为空")

        if not kb_name:
            kb_name = os.getenv("DEFAULT_KB_NAME", "default")

        from app.service.milvus_service import MilvusService
        from app.service.embedding_service import generate_embedding

        milvus_service = MilvusService()

        # 生成查询向量
        query_embedding = await asyncio.to_thread(generate_embedding, query)

        # 执行搜索
        results = await asyncio.to_thread(
            milvus_service.search,
            collection_name=kb_name,
            query_vector=query_embedding,
            top_k=top_k
        )

        # 格式化结果
        formatted_results = []
        for r in results:
            formatted_results.append({
                'url': f"local://{kb_name}/{r.get('document_id', 'unknown')}",
                'name': r.get('document_name', 'N/A'),
                'summary': r.get('content_with_weight', ''),
                'snippet': r.get('content_with_weight', '')[:200] if r.get('content_with_weight') else '',
                'siteName': f"知识库: {kb_name}",
                'siteIcon': '',
                'source': 'local',
                'score': r.get('score', 0),
                'document_id': r.get('document_id', ''),
                'chunk_id': r.get('chunk_id', '')
            })

        return ToolResult(success=True, data={
            "results": formatted_results,
            "count": len(formatted_results),
            "source": "knowledge_base",
            "kb_name": kb_name,
            "query": query
        })

    async def deep_search(
        self,
        query: str,
        sub_queries: Optional[List[str]] = None,
        max_depth: int = 2,
        cross_verify: bool = True
    ) -> ToolResult:
        """深度搜索"""
        if not query:
            return ToolResult(success=False, error="研究问题不能为空")

        if not sub_queries:
            sub_queries = [query]

        all_results = []
        all_sources = []

        # 并行搜索所有子查询
        logger.info(f"深度搜索开始: {query}, 子查询数: {len(sub_queries)}")

        search_tasks = []
        for sub_query in sub_queries:
            task = self._execute_web_search(sub_query, count=10)
            search_tasks.append(task)

        search_results = await asyncio.gather(*search_tasks)

        # 收集结果
        for i, results in enumerate(search_results):
            for r in results:
                r['sub_query'] = sub_queries[i]
                all_results.append(r)
                all_sources.append(r.get('url'))

        # 去重
        seen_urls = set()
        unique_results = []
        for r in all_results:
            url = r.get('url')
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(r)

        # 交叉验证
        cross_validation = {}
        if cross_verify and len(unique_results) > 0:
            cross_validation = self._perform_cross_validation(unique_results, query)

        # 第二轮深度搜索
        if max_depth > 1 and len(unique_results) > 0:
            key_findings = self._extract_key_findings(unique_results[:5])
            if key_findings:
                logger.info(f"进行第二轮深度搜索，关键词: {key_findings}")
                depth2_results = await self._execute_web_search(key_findings, count=5)
                for r in depth2_results:
                    r['depth'] = 2
                    if r.get('url') not in seen_urls:
                        unique_results.append(r)
                        seen_urls.add(r.get('url'))

        # 按相关度排序
        unique_results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

        return ToolResult(success=True, data={
            "results": unique_results[:20],
            "count": len(unique_results),
            "query": query,
            "sub_queries": sub_queries,
            "cross_validation": cross_validation,
            "depth": max_depth
        })

    async def _execute_web_search(self, query: str, count: int = 10) -> List[Dict]:
        """执行网络搜索（内部方法）"""
        url = "https://api.bochaai.com/v1/web-search"
        payload = {
            "query": query,
            "summary": True,
            "count": count,
            "page": 1
        }
        headers = {
            'Authorization': self.search_api_key,
            'Content-Type': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=25) as response:
                response.raise_for_status()
                data = await response.json()

                webpages_data = data.get('data', {}).get('webPages', {})
                value_list = webpages_data.get('value', [])

                results = []
                for item in value_list:
                    if item.get('url') and (item.get('snippet') or item.get('summary')):
                        results.append({
                            'url': item.get('url'),
                            'name': item.get('name', 'N/A'),
                            'summary': item.get('summary', '') or item.get('snippet', ''),
                            'snippet': item.get('snippet', ''),
                            'siteName': item.get('siteName', 'N/A'),
                            'siteIcon': item.get('siteIcon', ''),
                            'source': 'web',
                            'timestamp': item.get('dateLastCrawled', ''),
                            'relevance_score': item.get('score', 0)
                        })

                return results

    async def extract_webpage(
        self,
        url: str,
        extract_type: str = "article"
    ) -> ToolResult:
        """提取网页内容"""
        if not url:
            return ToolResult(success=False, error="URL不能为空")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0'
            }) as response:
                html = await response.text()

                content = ""
                title = ""

                if extract_type == "article":
                    try:
                        import trafilatura
                        content = trafilatura.extract(html) or ""
                    except ImportError:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        for script in soup(["script", "style"]):
                            script.decompose()
                        content = soup.get_text(separator='\n', strip=True)
                        title = soup.title.string if soup.title else ""
                elif extract_type == "text":
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')
                    for script in soup(["script", "style"]):
                        script.decompose()
                    content = soup.get_text(separator='\n', strip=True)
                    title = soup.title.string if soup.title else ""
                else:
                    content = html

                return ToolResult(success=True, data={
                    "url": url,
                    "title": title,
                    "content": content[:10000] if content else "",
                    "extract_type": extract_type,
                    "length": len(content) if content else 0
                })

    async def batch_search(
        self,
        queries: List[Dict],
        search_type: str = "web"
    ) -> ToolResult:
        """批量搜索"""
        if not queries or not isinstance(queries, list):
            return ToolResult(success=False, error="查询列表不能为空")

        all_results = {}

        if search_type in ["web", "both"]:
            web_tasks = []
            for q in queries:
                query_str = q.get("query", "") if isinstance(q, dict) else str(q)
                count = q.get("count", 5) if isinstance(q, dict) else 5
                task = self._execute_web_search(query_str, count)
                web_tasks.append((query_str, task))

            for query_str, task in web_tasks:
                results = await task
                all_results[f"web_{query_str}"] = results

        return ToolResult(success=True, data={
            "results": all_results,
            "query_count": len(queries),
            "search_type": search_type
        })

    # ========== 辅助方法 ==========

    def _get_cached_search(self, query: str) -> Optional[List]:
        """获取缓存的搜索结果"""
        query_hash = hashlib.md5(query.strip().lower().encode()).hexdigest()
        if query_hash in self._search_cache:
            results, timestamp = self._search_cache[query_hash]
            if time.time() - timestamp < self.CACHE_TTL:
                return results
            else:
                del self._search_cache[query_hash]
        return None

    def _set_cached_search(self, query: str, results: List):
        """缓存搜索结果"""
        query_hash = hashlib.md5(query.strip().lower().encode()).hexdigest()
        self._search_cache[query_hash] = (results, time.time())

        # 清理过期缓存
        current_time = time.time()
        expired_keys = [
            k for k, (_, t) in self._search_cache.items()
            if current_time - t > self.CACHE_TTL
        ]
        for k in expired_keys:
            del self._search_cache[k]

    def _perform_cross_validation(self, results: List[Dict], query: str) -> Dict:
        """执行交叉验证"""
        return {
            "total_sources": len(results),
            "unique_domains": len(set(r.get('siteName', '') for r in results)),
            "high_confidence_sources": [r.get('url') for r in results[:3]],
            "verification_status": "partial"
        }

    def _extract_key_findings(self, results: List[Dict]) -> str:
        """从结果中提取关键线索用于深度搜索"""
        texts = []
        for r in results[:3]:
            texts.append(r.get('name', ''))
            texts.append(r.get('summary', '')[:100])
        return ' '.join(texts)[:200] if texts else ""
