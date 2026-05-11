"""
Token 成本估算工具

用于在入库完成后打印 Token 消耗报告。

注意：
    - DeepSeek API 的 token 计数由服务端返回（usage.prompt_tokens / usage.completion_tokens）
    - Ollama 本地模型不返回 token 计数，使用近似估算
    - 这里使用一个 TokenCounter 类来累加消费、支持多种模型费率查询

费率参考（截至 2026-05）：
    - DeepSeek-V4-Flash: ¥0.3 / 1M 输入 tokens
    - Ollama 本地 (qwen3-vl:8b): 免费（本地硬件成本）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ModelRate:
    """模型费率（单位：元/1M tokens）"""
    input_price: float     # 输入价格
    output_price: float    # 输出价格
    name: str = ""

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（元）"""
        return (input_tokens * self.input_price + output_tokens * self.output_price) / 1_000_000

    def __post_init__(self):
        if not self.name:
            self.name = f"¥{self.input_price}/{self.output_price}"


# 预定义费率
DEFAULT_RATES: dict[str, ModelRate] = {
    "deepseek-v4-flash": ModelRate(0.3, 0.3, "DeepSeek-V4-Flash"),
    "qwen3-vl:8b": ModelRate(0.0, 0.0, "Ollama 本地 (免费)"),
    "qwen-vl:7b": ModelRate(0.0, 0.0, "Ollama 本地 (免费)"),
    "bge-m3": ModelRate(0.0, 0.0, "Ollama 本地 (免费)"),
}


def estimate_text_tokens(text: str) -> int:
    """
    近似估算文本的 token 数。
    中文：~1.5 字符 / token
    英文：~4 字符 / token
    """
    if not text:
        return 0
    # 中文字符计数
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 非中文字符计数（英文/数字/标点/空格）
    other_chars = len(text) - cn_chars
    return int(cn_chars / 1.5 + other_chars / 4) + 1  # +1 保底


def estimate_image_tokens(detail: Literal["low", "high"] = "high") -> int:
    """
    估算图片 token 消耗（DeepSeek 视觉模型）。
    - low: 85 tokens（小图）
    - high: 约 800 tokens（标准页面截图 ~800x600）
    """
    return 85 if detail == "low" else 800


@dataclass
class TokenCounter:
    """
    Token 计数器 — 累加所有 API 调用的 token 消耗。

    使用方式：
        counter = TokenCounter(model_name="deepseek-v4-flash")
        counter.add_tokens(input=1500, output=200)
        report = counter.report()
    """
    model_name: str = "deepseek-v4-flash"
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add_tokens(self, input_t: int = 0, output_t: int = 0) -> None:
        """累加 token 计数"""
        self.input_tokens += input_t
        self.output_tokens += output_t
        self.calls += 1

    def add_call(self, text_input: str = "", text_output: str = "",
                 image_count: int = 0, image_detail: Literal["low", "high"] = "high",
                 actual_input_tokens: int | None = None,
                 actual_output_tokens: int | None = None) -> None:
        """
        添加一次 API 调用计数。

        如果提供了 actual_input_tokens/actual_output_tokens，优先使用实际值（API 返回的 usage）。
        否则使用近似估算。
        """
        if actual_input_tokens is not None:
            input_t = actual_input_tokens
        else:
            input_t = estimate_text_tokens(text_input)
            input_t += estimate_image_tokens(image_detail) * image_count

        if actual_output_tokens is not None:
            output_t = actual_output_tokens
        else:
            output_t = estimate_text_tokens(text_output)

        self.add_tokens(input_t, output_t)

    def report(self) -> dict:
        """
        生成费用报告。

        返回：
            {
                "model": "DeepSeek-V4-Flash",
                "calls": 36,
                "input_tokens": 54000,
                "output_tokens": 7200,
                "total_tokens": 61200,
                "cost_yuan": 0.0184,
                "rate": "¥0.3/1M",
            }
        """
        rate = DEFAULT_RATES.get(self.model_name, ModelRate(0.3, 0.3))
        cost = rate.cost(self.input_tokens, self.output_tokens)
        total = self.input_tokens + self.output_tokens

        return {
            "model": rate.name,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": total,
            "cost_yuan": round(cost, 6),
            "rate": f"¥{rate.input_price}/1M tokens",
        }

    def print_report(self) -> str:
        """打印可读的费用报告"""
        r = self.report()
        lines = [
            f"  Token 消耗报告:",
            f"    模型: {r['model']}",
            f"    调用次数: {r['calls']}",
            f"    总 Token: {r['total_tokens']:,}",
            f"      ├─ 输入: {r['input_tokens']:,}",
            f"      └─ 输出: {r['output_tokens']:,}",
            f"    预估费用: ¥{r['cost_yuan']:.4f} ({r['rate']})",
        ]
        return "\n".join(lines)
