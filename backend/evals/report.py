"""Renders eval results as a Markdown report."""

from collections import Counter
from datetime import datetime
from statistics import mean

from evals.metrics import CaseMetrics
from evals.runner import EvalResult
from evals.usability import RULES


def _aggregate(results: list[EvalResult]) -> dict:
    metrics: list[CaseMetrics] = [result.metrics for result in results if result.error is None]
    if not metrics:
        return {"count": 0}
    judges = [result.judge["score"] for result in results if result.judge]
    return {
        "count": len(metrics),
        "score": mean(m.score for m in metrics),
        "geo": mean(m.avg_intra_day_km for m in metrics),
        "geo_max": max(m.max_intra_day_km for m in metrics),
        "degraded": sum(1 for m in metrics if m.degraded) / len(metrics),
        "structure": sum(1 for m in metrics if m.day_structure_ok) / len(metrics),
        "preference": mean(m.preference_hit_rate for m in metrics),
        "hours": mean(m.hours_known_rate for m in metrics),
        "budget": mean(m.budget_deviation for m in metrics),
        "errors": sum(1 for result in results if result.error),
        "judge": mean(judges) if judges else None,
    }


def render_report(results: list[EvalResult], mode: str, generated_at: datetime, offline: bool = False) -> str:
    stats = _aggregate(results)
    lines = [
        f"# EasyTravel 评测报告（{mode}）",
        "",
        f"- 生成时间：{generated_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 用例数：{stats.get('count', 0)}（失败 {stats.get('errors', 0)}）",
    ]
    if offline:
        lines.append(
            "- 模式说明：离线运行，全部行程由确定性规则引擎生成；综合分不含「是否使用模型」项（权重已归一化）。"
        )
    lines += [
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 | 说明 |",
        "| --- | --- | --- |",
    ]
    if stats.get("count"):
        weight_note = (
            "动线 34%、约束 28%、偏好 22%、预算 16%" if offline else "动线 30%、约束 25%、偏好 20%、预算 15%、模型 10%"
        )
        lines += [
            f"| 综合得分 | **{stats['score']:.1f}** / 100 | 加权：{weight_note} |",
            f"| 单日折返均值 | {stats['geo']:.1f} km | 同一天景点之间的移动距离（不含酒店往返） |",
            f"| 单日折返最大 | {stats['geo_max']:.1f} km | 最差的一天 |",
            f"| 降级比例 | {stats['degraded'] * 100:.0f}% | 由规则引擎生成的比例 |",
            f"| 结构合规率 | {stats['structure'] * 100:.0f}% | 天数正确且每天 1–3 个景点 |",
            f"| 偏好命中率 | {stats['preference'] * 100:.0f}% | 景点与所选偏好关键词的匹配比例 |",
            f"| 营业时间覆盖率 | {stats['hours'] * 100:.0f}% | 景点与餐饮中带营业时间数据的比例 |",
            f"| 预算偏差 | {stats['budget'] * 100:.0f}% | 与预算档位参考值的相对偏差 |",
        ]
        if stats.get("judge") is not None:
            lines.append(f"| 评审得分 | {stats['judge']:.2f} / 5 | LLM-as-judge 平均分 |")
    lines += [
        "",
        "## 明细",
        "",
        "| 用例 | 得分 | 折返(km) | 天数 | 降级 | 偏好 | 预算偏差 | 评审 |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in results:
        m = result.metrics
        judge = f"{result.judge['score']}" if result.judge else "-"
        lines.append(
            f"| {result.case.id} | {m.score:.1f} | {m.avg_intra_day_km:.1f} | {m.days} | "
            f"{'是' if m.degraded else '否'} | {m.preference_hit_rate * 100:.0f}% | "
            f"{m.budget_deviation * 100:.0f}% | {judge} |"
        )

    worst = sorted(
        [result for result in results if result.error is None],
        key=lambda result: result.metrics.score,
    )[:5]
    if worst:
        lines += ["", "## 最差的 5 个用例", ""]
        for result in worst:
            m = result.metrics
            lines.append(
                f"- **{result.case.id}**（{result.case.city} {result.case.days} 天）："
                f"{m.score:.1f} 分，折返 {m.avg_intra_day_km:.1f} km，"
                f"预算偏差 {m.budget_deviation * 100:.0f}%"
            )

    errors = [result for result in results if result.error]
    if errors:
        lines += ["", "## 失败用例", ""]
        for result in errors:
            lines.append(f"- `{result.case.id}`：{result.error}")

    usability = [result for result in results if result.usability is not None]
    if usability:
        verdicts = [result.usability for result in usability if result.usability is not None]
        usable = [verdict for verdict in verdicts if verdict.usable]
        counts = Counter(failure.rule for verdict in verdicts for failure in verdict.failures)
        lines += [
            "",
            "## 能否直接照着走",
            "",
            f"**{len(usable)}/{len(verdicts)}** 份行程可以按原样执行（{len(usable) / len(verdicts):.0%}）。",
            "每一条检查都复用应用自身的阈值，不调用模型、不花钱。",
            "",
            "| 检查 | 未通过次数 |",
            "| --- | ---: |",
        ]
        for rule in RULES:
            lines.append(f"| {rule.label} | {counts.get(rule.key, 0)} |")

        broken = [verdict for verdict in verdicts if not verdict.usable]
        if broken:
            lines += ["", "### 走不通的地方", ""]
            for verdict in broken:
                shown = "；".join(failure.message for failure in verdict.failures[:3])
                lines.append(f"- **{verdict.case_id}**：{shown}")

    judged = [result for result in results if result.judge]
    if judged:
        lines += ["", "## 评审意见（LLM-as-judge）", ""]
        for result in judged:
            verdict = result.judge or {}
            issues = "；".join(verdict.get("issues") or []) or "无"
            lines.append(
                f"- **{result.case.id}** {verdict.get('score')}/5 — {verdict.get('rationale') or ''}（问题：{issues}）"
            )

    lines.append("")
    return "\n".join(lines)
