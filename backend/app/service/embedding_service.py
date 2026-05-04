"""
Embedding 服务 - 使用阿里 DashScope

功能：
1. generate_embedding - 使用 text-embedding-v4 生成向量
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def generate_embedding(
    text: str | list[str],
    api_key: str = None,
    base_url: str = None,
    model_name: str = "text-embedding-v4",
    dimensions: int = 1024,
    encoding_format: str = "float",
    max_batch_size: int = 10,
) -> list[float] | list[list[float]] | None:
    """
    生成文本的向量嵌入（使用阿里 text-embedding-v4）

    Args:
        text: 单个文本或文本列表
        api_key: API密钥（默认从环境变量获取）
        base_url: API基础URL（默认从环境变量获取）
        model_name: 模型名称
        dimensions: 向量维度（默认1024）
        encoding_format: 编码格式
        max_batch_size: 最大批量大小（阿里云限制为10）

    Returns:
        单个文本时返回向量，文本列表时返回向量列表
    """
    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    base_url = base_url or os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    if not api_key:
        print("错误: 缺少 DASHSCOPE_API_KEY 环境变量")
        return None

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
    except Exception as e:
        print(f"初始化 OpenAI 客户端失败: {e}")
        return None

    # 单个文本
    if isinstance(text, str):
        try:
            completion = client.embeddings.create(
                model=model_name, input=text, dimensions=dimensions, encoding_format=encoding_format
            )
            return completion.data[0].embedding
        except Exception as e:
            print(f"Embedding 请求失败: {e}")
            return None

    # 文本列表 - 分批处理
    if isinstance(text, list):
        all_embeddings = []

        for i in range(0, len(text), max_batch_size):
            batch = text[i : i + max_batch_size]

            try:
                completion = client.embeddings.create(
                    model=model_name,
                    input=batch,
                    dimensions=dimensions,
                    encoding_format=encoding_format,
                )
                batch_embeddings = [item.embedding for item in completion.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"Embedding 批量请求失败 (batch {i // max_batch_size + 1}): {e}")
                all_embeddings.extend([None] * len(batch))

        return all_embeddings

    return None
