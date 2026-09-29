# -*- coding: utf-8 -*-
"""命令行入口:python -m finagent.cli <task> [--eval] [--trace-dir DIR]"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from .config import load_config
from .knowledge.engine import build_engine
from .agent.runner import AgentRunner
from .agent.memory import Memory
from .tools.registry import build_registry
from .runtime.evaluation import run_suite, TEST_SUITE
from .runtime.trace import Trace


def make_runner(cfg=None):
    cfg = cfg or load_config()
    return AgentRunner(
        cfg=cfg,
        registry=build_registry(),
        knowledge=build_engine(cfg),
        memory=Memory(os.path.join(cfg.workspace_dir, "memory")),
    )


def cmd_run(task: str, show_trace: bool, trace_dir: str | None) -> None:
    runner = make_runner()
    trace = Trace(task)
    answer, trace = runner.run(task, trace)
    print("=" * 72)
    print(answer)
    print("=" * 72)
    if show_trace:
        print(trace.pretty())
    if trace_dir:
        os.makedirs(trace_dir, exist_ok=True)
        fname = f"trace_{trace.started_ms:.0f}.json"
        trace.save(os.path.join(trace_dir, fname))
        print(f"[trace 已保存] {os.path.join(trace_dir, fname)}")


def cmd_eval(trace_dir: str | None, cases: str | None) -> None:
    suite = TEST_SUITE
    if cases:
        ids = set(cases.split(","))
        suite = [c for c in TEST_SUITE if c["id"] in ids]
    print(f"评测集: {len(suite)} 个用例")
    report = run_suite(lambda: make_runner(), suite, trace_dir=trace_dir)
    print("\n---- 指标 ----")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print("\n---- 质量门禁 ----")
    gate = report["gate"]
    for k, v in gate["details"].items():
        mark = {True: "✓", False: "✗", None: "-"}[v["pass"]]
        print(f"  {mark} {k}: {v['value']} (要求 {v['threshold']}) {v['desc']}")
    print(f"\n门禁总判定: {'通过 ✅' if gate['overall'] else '未通过 ❌'}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="finagent")
    ap.add_argument("task", nargs="?", help="研究任务")
    ap.add_argument("--eval", action="store_true", help="运行评测集")
    ap.add_argument("--cases", help="只跑指定 case,逗号分隔(如 T-001,T-005)")
    ap.add_argument("--trace", action="store_true", help="打印执行轨迹")
    ap.add_argument("--trace-dir", default="workspace/traces", help="trace 落盘目录")
    args = ap.parse_args()

    if args.eval:
        cmd_eval(args.trace_dir, args.cases)
    elif args.task:
        cmd_run(args.task, args.trace, args.trace_dir)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
