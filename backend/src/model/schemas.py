from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_TRIP_DAYS = 14

#: Where a price came from. ``unknown`` means "do not show a number" - never 0.
PriceSource = Literal["api", "estimated", "unknown"]
#: Where a place record came from. ``sample`` means demo data, not navigable.
PlaceSource = Literal["amap", "sample"]


class Location(BaseModel):
    longitude: float = Field(..., description="经度", ge=-180, le=180)
    latitude: float = Field(..., description="纬度", ge=-90, le=90)


class Attraction(BaseModel):
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(default=90, description="建议游览时间(分钟)", gt=0)
    description: str = Field(default="", description="景点描述")
    category: str = Field(default="景点", description="景点类别")
    rating: float | None = Field(default=None, ge=0, le=5, description="评分")
    image_url: str | None = Field(default=None, description="图片URL")
    ticket_price: int = Field(default=0, ge=0, description="门票价格(元)")
    price_source: PriceSource = Field(
        default="estimated",
        description="门票价格来源：接口返回/规则估算/无法确认",
    )
    opening_hours: str | None = Field(default=None, description="营业/开放时间原文，来源于数据接口")
    contact_phone: str | None = Field(default=None, description="联系电话，来源于数据接口")
    level: str | None = Field(default=None, description="景区等级等标签，如 5A景区")
    source: PlaceSource = Field(default="sample", description="place data source")


class Meal(BaseModel):
    type: Literal["breakfast", "lunch", "dinner", "snack"] = Field(..., description="餐饮类型")
    name: str = Field(..., description="餐饮名称")
    address: str | None = Field(default=None, description="地址")
    location: Location | None = Field(default=None, description="经纬度坐标")
    description: str | None = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, ge=0, description="预估费用(元)")
    price_source: PriceSource = Field(
        default="estimated",
        description="人均价格来源：接口返回/规则估算/无法确认",
    )
    opening_hours: str | None = Field(default=None, description="营业时间原文，来源于数据接口")
    source: PlaceSource = Field(default="sample", description="meal data source")


class Hotel(BaseModel):
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Location | None = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: int = Field(default=0, ge=0, description="预估费用(元/晚)")
    price_source: PriceSource = Field(
        default="estimated",
        description="房价来源：接口返回/规则估算/无法确认",
    )
    source: PlaceSource = Field(default="sample", description="hotel data source")


class Budget(BaseModel):
    total_attractions: int = Field(default=0, ge=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, ge=0, description="酒店总费用")
    total_meals: int = Field(default=0, ge=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, ge=0, description="交通总费用")
    total: int = Field(default=0, ge=0, description="总费用")

    @model_validator(mode="after")
    def fill_total(self) -> "Budget":
        expected = self.total_attractions + self.total_hotels + self.total_meals + self.total_transportation
        if self.total == 0:
            self.total = expected
        return self


class PlanQuality(BaseModel):
    score: int = Field(default=100, ge=0, le=100, description="行程质量评分")
    warnings: list[str] = Field(default_factory=list, description="需要用户注意的问题")
    checks: dict[str, bool] = Field(default_factory=dict, description="质量检查结果")


class DayEdit(BaseModel):
    """What the model may change on a single day. It never rewrites the whole plan."""

    day_index: int = Field(..., ge=0, description="第几天(从0开始)")
    remove_attractions: list[str] = Field(default_factory=list, description="要移除的景点名称")
    add_attractions: list[str] = Field(default_factory=list, description="要新增的景点名称，必须来自候选列表")
    description: str | None = Field(default=None, description="新的当日说明；为空表示不改")
    meals: list[str] | None = Field(default=None, description="替换当天的餐饮，必须来自候选列表；为空表示不改")
    hotel: str | None = Field(default=None, description="更换酒店，必须来自候选列表；为空表示不改")


class PlanPatch(BaseModel):
    """The only thing the model returns for a conversational edit."""

    days: list[DayEdit] = Field(default_factory=list, description="按天组织的变更")
    overall_suggestions: str | None = Field(default=None, description="更新后的整体建议")
    reply: str = Field(..., min_length=1, description="一句话说明改了什么")


class PlanDecisionDay(BaseModel):
    """What the model is allowed to decide for one day: choices, not facts."""

    day_index: int = Field(..., ge=0, description="第几天(从0开始)")
    description: str = Field(..., min_length=1, description="当日安排与理由")
    attractions: list[str] = Field(default_factory=list, description="只能取候选景点名称")
    meals: list[str] = Field(default_factory=list, description="只能取候选餐饮名称")
    hotel: str | None = Field(default=None, description="只能取候选酒店名称")


class PlanDecision(BaseModel):
    """The model's entire output contract: names only, never coordinates or prices."""

    days: list[PlanDecisionDay] = Field(default_factory=list, description="每日选择")
    overall_suggestions: str | None = Field(default=None, description="整体建议")


class RouteLeg(BaseModel):
    origin: str = Field(..., description="起点名称")
    destination: str = Field(..., description="终点名称")
    distance_meters: int = Field(default=0, ge=0, description="距离(米)")
    duration_minutes: int = Field(default=0, ge=0, description="耗时(分钟)")
    mode: str = Field(default="", description="交通方式")


class DayPlan(BaseModel):
    date: str = Field(..., description="日期")
    day_index: int = Field(..., ge=0, description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿安排")
    hotel: Hotel | None = Field(default=None, description="酒店信息")
    attractions: list[Attraction] = Field(default_factory=list, description="景点列表")
    meals: list[Meal] = Field(default_factory=list, description="餐饮安排")
    routes: list[RouteLeg] = Field(default_factory=list, description="当日路线估算")


class WeatherInfo(BaseModel):
    date: str = Field(..., description="日期")
    day_weather: str = Field(..., description="白天天气")
    night_weather: str = Field(..., description="夜间天气")
    day_temp: int = Field(..., description="白天温度(摄氏度)")
    night_temp: int = Field(..., description="夜间温度(摄氏度)")
    wind_direction: str = Field(..., description="风向")
    wind_power: str = Field(..., description="风力")
    forecast_available: bool = Field(default=True, description="是否有可信天气预报")
    notice: str | None = Field(default=None, description="天气提示")
    source: Literal["amap", "open_meteo", "qweather", "sample", "unavailable"] = Field(
        default="unavailable", description="weather data source"
    )

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value: object) -> int:
        if isinstance(value, str):
            cleaned = value.replace("degC", "").replace("°C", "").replace("℃", "").replace("°", "").strip()
            try:
                return int(float(cleaned))
            except ValueError:
                return 0
        if isinstance(value, (int, float)):
            return int(value)
        raise ValueError(f"cannot read a temperature from {type(value).__name__}")


class TripPlanRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=50, description="目的地城市")
    start_date: date = Field(..., description="开始日期")
    end_date: date | None = Field(default=None, description="结束日期")
    days: int = Field(default=3, ge=1, le=MAX_TRIP_DAYS, description="旅行天数")
    preferences: str = Field(default="历史文化", max_length=300, description="旅行偏好")
    budget: Literal["经济", "中等", "舒适", "豪华"] = Field(default="中等", description="预算档位")
    transportation: str = Field(default="公共交通", max_length=50, description="交通方式")
    accommodation: str = Field(default="经济型酒店", max_length=50, description="住宿偏好")

    @field_validator("city")
    @classmethod
    def strip_city(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("city must not be blank")
        return cleaned

    @model_validator(mode="after")
    def normalize_dates(self) -> "TripPlanRequest":
        if self.end_date is None:
            self.end_date = self.start_date + timedelta(days=self.days - 1)
        else:
            delta_days = (self.end_date - self.start_date).days + 1
            if delta_days <= 0:
                raise ValueError("end_date must be greater than or equal to start_date")
            self.days = delta_days
        # ``days`` was mutated above, so re-check the bound the field declares.
        if not 1 <= self.days <= MAX_TRIP_DAYS:
            raise ValueError(f"trip length must be between 1 and {MAX_TRIP_DAYS} days")
        return self

    @property
    def resolved_end_date(self) -> date:
        """``end_date`` after validation.

        The field is ``date | None`` because callers may omit it, but
        ``normalize_dates`` always fills it in. Code that needs a concrete date
        uses this property instead of re-deriving that invariant (or asserting).
        """
        return self.end_date or self.start_date
        return self


class TripPlan(BaseModel):
    id: str | None = Field(default=None, description="行程ID")
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: list[DayPlan] = Field(default_factory=list, description="每日行程")
    weather_info: list[WeatherInfo] = Field(default_factory=list, description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Budget | None = Field(default=None, description="预算信息")
    quality: PlanQuality | None = Field(default=None, description="行程质量评估")
    degraded: bool = Field(default=False, description="是否降级为规则引擎生成")
    degraded_reason: str | None = Field(default=None, description="降级原因")
    data_notices: list[str] = Field(default_factory=list, description="data availability notices")


class HealthResponse(BaseModel):
    status: str
    app_name: str
    services: dict[str, bool]


class TripPlanSummary(BaseModel):
    id: str
    city: str
    start_date: str
    end_date: str
    days: int
    created_at: str
    updated_at: str


class ReviseRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=300, description="自然语言的修改要求")

    @field_validator("instruction")
    @classmethod
    def strip_instruction(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("instruction must not be blank")
        return cleaned


class ReviseResponse(BaseModel):
    plan: TripPlan
    reply: str
