"""Harness 支柱三 · 熵管理（Entropy Management / 代码 GC）。

核心思想：**长期运行的 Agent 系统会积累"数字债务"**——过时记忆、失效缓存、
历史草稿、跑偏的文档。必须有一个后台 Agent 定期扫描并修复。

在本项目的具体职责：
1. 清理超过保留期的历史草稿与中间态
2. 压缩/归档长期未访问的向量记录
3. 校验"已发布项目表"与真实发布记录是否一致
4. 输出心跳与健康报告

第 1 篇：定义任务与心跳契约。
第 7 篇：落地 GC Agent 并挂到调度器。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from zhixun.config.logging import get_logger

logger = get_logger(__name__)

# harness/entropy/__init__.py -> parents[0]=entropy [1]=harness [2]=zhixun [3]=src [4]=backend
HEARTBEAT_FILE = Path(__file__).resolve().parents[4] / "logs" / "heartbeat.json"


@dataclass(slots=True)
class EntropyReport:
    """一次熵扫描的结果。"""

    scanned_at: datetime = field(default_factory=datetime.now)
    stale_drafts: int = 0
    stale_vectors: int = 0
    inconsistent_records: int = 0
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_at": self.scanned_at.isoformat(),
            "stale_drafts": self.stale_drafts,
            "stale_vectors": self.stale_vectors,
            "inconsistent_records": self.inconsistent_records,
            "actions": self.actions,
        }


class EntropyScanner:
    """熵扫描器（GC Agent 的执行体）。"""

    def __init__(self, retention_days: int = 7) -> None:
        self.retention_days = retention_days

    async def scan(self) -> EntropyReport:
        """扫描并（在允许时）修复。"""
        report = EntropyReport()
        # TODO(第 7 篇): 扫描草稿目录 / 向量表 / 发布记录一致性
        logger.info("entropy.scanned", retention_days=self.retention_days)
        return report

    def write_heartbeat(self, report: EntropyReport) -> None:
        """写心跳文件，供运维监控读取。"""
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
