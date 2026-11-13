"""The type inspector exists because the preference metric was guessing.

Its output is what CATEGORY_AXES was corrected from, so the parts that decide
"which segment counts" and "which segment is unmapped" have to be pinned.
"""

from src.cli.poi_types import TypeReport, format_report, leaf_segments


def test_a_type_hierarchy_is_split_into_segments() -> None:
    assert leaf_segments("风景名胜;公园广场;公园") == ["风景名胜", "公园广场", "公园"]


def test_a_multi_valued_segment_is_kept_whole_here() -> None:
    """AMap returns "博物馆|风景名胜": the inspector reports it verbatim.

    Flattening it here would hide the very thing that made the metric miss those
    attractions - that a segment can carry two values.
    """
    assert leaf_segments("科教文化服务;博物馆|风景名胜") == ["科教文化服务", "博物馆|风景名胜"]


def test_an_empty_category_yields_nothing() -> None:
    assert leaf_segments("") == []
    assert leaf_segments(";;") == []


def test_unmapped_segments_are_listed() -> None:
    report = TypeReport(cities=["杭州"])
    report.segments["公园"] = 3
    report.segments["旅游景点"] = 2

    assert report.unmapped() == ["旅游景点"]


def test_the_report_says_which_segments_score_nothing() -> None:
    report = TypeReport(cities=["杭州"], attractions=2)
    report.segments["公园"] = 1
    report.segments["旅游景点"] = 1

    text = format_report(report)

    assert "公园" in text
    assert "休闲、自然风光" in text
    assert "没有映射的段" in text
    assert "旅游景点" in text


def test_a_fully_mapped_report_says_so() -> None:
    report = TypeReport(cities=["杭州"], attractions=1)
    report.segments["博物馆"] = 1

    assert "所有出现过的类型都有映射" in format_report(report)
