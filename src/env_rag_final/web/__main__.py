"""Launch with the original LightRAG checkout before any lightrag imports."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="本机只读 RAG 检索对照网页")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--report-dir", default="reports/rag-web-20261010-r1/runtime")
    parser.add_argument(
        "--usage-mode",
        choices=("interactive", "goal"),
        default="interactive",
        help="日常问答独立计量；goal 保留历史验收上限",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be in 1024..65535")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    original = Path(__file__).resolve().parents[3].parent / "LightRAG"
    if not (original / "lightrag/operate.py").is_file():
        parser.error("原 LightRAG checkout 不存在")
    sys.path.insert(0, str(original))
    from .server import start

    start(args.port, Path(args.report_dir), interactive=args.usage_mode == "interactive")


if __name__ == "__main__":
    main()
