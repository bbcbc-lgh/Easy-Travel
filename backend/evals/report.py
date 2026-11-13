"""Renders eval results as a Markdown report."""

from collections import Counter
from datetime import datetime
from statistics import mean

from evals.metrics import CaseMetrics
from evals.runner import EvalResult
from evals.usability import RULES


def _mean_of_measured(values) -> float | None:
    """Average only what was actually measured; ``None`` means "not measured"."""
    measured = [value for value in values if value is not None]
    return mean(measured) if measured else None


def _aggregate(results: list[EvalResult]) -> dict:
    metrics: list[CaseMetrics] = [result.metrics for result in results if result.error is None]
    if not metrics:
        return {"count": 0}
    return {
        "count": len(metrics),
        "score": mean(m.score for m in metrics),
        "geo": mean(m.avg_intra_day_km for m in metrics),
        "geo_max": max(m.max_intra_day_km for m in metrics),
        "degraded": sum(1 for m in metrics if m.degraded) / len(metrics),
        "structure": sum(1 for m in metrics if m.day_structure_ok) / len(metrics),
        "preference": _mean_of_measured(m.preference_hit_rate for m in metrics),
        "preference_measured": sum(1 for m in metrics if m.preference_hit_rate is not None),
        "hours": mean(m.hours_known_rate for m in metrics),
        "budget": mean(m.budget_deviation for m in metrics),
        "errors": sum(1 for result in results if result.error),
    }


def _preference_row(stats: dict) -> str:
    """0% and "cannot be measured" are different answers and must look different."""
    value = stats.get("preference")
    measured = stats.get("preference_measured", 0)
    total = stats.get("count", 0)
    if value is None:
        return f"| 偏好命中率 | n/a | 没有可映射到偏好轴的景点类别（{total} 条用例均未测到） |"
    note = "景点类别与所选偏好相符的比例"
    if measured < total:
        note += f"（{total - measured} 条用例的类型无法映射，未计入均值）"
    return f"| 偏好命中率 | {value * 100:.0f}% | {note} |"


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
            _preference_row(stats),
            f"| 营业时间覆盖率 | {stats['hours'] * 100:.0f}% | 景点与餐饮中带营业时间数据的比例 |",
            f"| 预算偏差 | {stats['budget'] * 100:.0f}% | 与预算档位参考值的相对偏差 |",
        ]
    lines += [
        "",
        "## 明细",
        "",
        "| 用例 | 得分 | 折返(km) | 天数 | 降级 | 偏好 | 预算偏差 |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: |",
    ]
    for result in results:
        m = result.metrics
        preference = "n/a" if m.preference_hit_rate is None else f"{m.preference_hit_rate * 100:.0f}%"
        lines.append(
            f"| {result.case.id} | {m.score:.1f} | {m.avg_intra_day_km:.1f} | {m.days} | "
            f"{'是' if m.degraded else '否'} | {preference} | "
            f"{m.budget_deviation * 100:.0f}% |"
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

    lines.append("")
    return "\n".join(lines)
