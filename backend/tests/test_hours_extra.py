from src.planning.hours import closed_weekdays


def test_open_range_still_works() -> None:
    assert closed_weekdays("周一至周日 09:00-17:00") == set()
    assert closed_weekdays("周二至周日 09:00-16:30") == {0}
    assert closed_weekdays("周一至周五 09:00-18:00") == {5, 6}


def test_multiple_closed_days_in_one_clause() -> None:
    assert closed_weekdays("周一、周三闭馆") == {0, 2}
    assert closed_weekdays("每周二、周五休息") == {1, 4}


def test_weekend_and_aliases() -> None:
    assert closed_weekdays("周末闭馆") == {5, 6}
    assert closed_weekdays("星期六、星期日不开放") == {5, 6}
    assert closed_weekdays("星期四闭馆") == {3}


def test_always_open_is_known_and_empty() -> None:
    assert closed_weekdays("全年无休 09:00-17:00") == set()
    assert closed_weekdays("每天开放，09:00-22:00") == set()


def test_unknown_stays_unknown() -> None:
    assert closed_weekdays("09:00-17:00") is None
    assert closed_weekdays("需提前预约") is None
    assert closed_weekdays(None) is None


def test_mixed_open_range_and_closed_clause() -> None:
    assert closed_weekdays("周二至周日 09:00-16:30，周一闭馆") == {0}
    assert closed_weekdays("周一至周五 09:00-17:00，周末闭馆") == {5, 6}
