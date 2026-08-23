"""评测编排：造输入 → build_prompt → 调 LLM → 解析 → 逐 scorer 打分 → 报告。

用法: python -m drama_agent.evals.harness <node> [model]
位于 src 下,不进 pytest 默认收集;评测的编排逻辑可用 mock-LLM 写单测。
"""
import asyncio
import sys
from drama_agent.services.llm_service import llm_service
from drama_agent.evals import scorers
from drama_agent.evals.cases import CASES
from drama_agent.workflow.nodes import (
    story_analyzer, screenplay_writer, storyboard_director, prompt_engineer,
)


async def _run_story_analyzer(inputs: dict, model: str | None):
    system, user = story_analyzer.build_prompt(**inputs)
    parsed = await llm_service.complete_json(system, user, temperature=0.3, model=model)
    return scorers.score_story_analysis("", parsed)


async def _run_screenplay(inputs: dict, model: str | None):
    system, user = screenplay_writer.build_prompt(**inputs)
    text = await llm_service.complete(system, user, temperature=0.7, model=model)
    return scorers.score_screenplay(text)


async def _run_storyboard(inputs: dict, model: str | None):
    system, user = storyboard_director.build_prompt(**inputs)
    parsed = await llm_service.complete_json(system, user, temperature=0.3, model=model)
    if isinstance(parsed, dict) and "shots" in parsed:
        parsed = parsed["shots"]
    return scorers.score_storyboard("", parsed if isinstance(parsed, list) else [])


async def _run_prompt_engineer(inputs: dict, model: str | None):
    system, user = prompt_engineer.build_prompt(**inputs)
    parsed = await llm_service.complete_json(system, user, temperature=0.4, model=model)
    return scorers.score_prompt("", parsed)


_RUNNERS = {
    "story_analyzer": _run_story_analyzer,
    "screenplay_writer": _run_screenplay,
    "storyboard_director": _run_storyboard,
    "prompt_engineer": _run_prompt_engineer,
}


async def run_eval(node: str, model: str | None = None) -> dict:
    if node not in _RUNNERS:
        raise ValueError(f"Unknown eval node: {node}")
    runner = _RUNNERS[node]
    results = []
    all_passed = True
    for case in CASES.get(node, []):
        scores = await runner(case["inputs"], model)
        avg = sum(s["score"] for s in scores) / len(scores) if scores else 0.0
        case_passed = avg >= case.get("min_pass", 1.0) and all(s["passed"] for s in scores)
        all_passed = all_passed and case_passed
        results.append({"inputs": case["inputs"], "scores": scores, "avg": avg, "passed": case_passed})
    return {"node": node, "results": results, "passed": all_passed}


def _main() -> None:
    node = sys.argv[1] if len(sys.argv) > 1 else None
    model = sys.argv[2] if len(sys.argv) > 2 else None
    if not node:
        print("usage: python -m drama_agent.evals.harness <node> [model]")
        print("nodes:", ", ".join(_RUNNERS))
        return
    report = asyncio.run(run_eval(node, model))
    print(f"[eval] node={report['node']} passed={report['passed']}")
    for i, r in enumerate(report["results"]):
        print(f"  case#{i} avg={r['avg']:.2f} passed={r['passed']}")
        for s in r["scores"]:
            mark = "✓" if s["passed"] else "✗"
            print(f"    {mark} {s['name']} {s['detail']}")


if __name__ == "__main__":
    _main()
