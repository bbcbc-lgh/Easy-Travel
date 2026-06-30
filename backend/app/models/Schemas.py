from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Location(BaseModel):
    longitude: float = Field(..., description="经度", ge=-180, le=180)
    latitude: float = Field(..., description="纬度", ge=-90, le=90)


class Attraction(BaseModel):
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(90, description="建议游览时间(分钟)", gt=0)
    description: str = Field("", description="景点描述")
    category: str = Field("景点", description="景点类别")
    rating: float | None = Field(None, ge=0, le=5, description="评分")
    image_url: str | None = Field(None, description="图片URL")
    ticket_price: int = Field(0, ge=0, description="门票价格(元)")


class Meal(BaseModel):
    type: Literal["breakfast", "lunch", "dinner", "snack"] = Field(..., description="餐饮类型")
    name: str = Field(..., description="餐饮名称")
    address: str | None = Field(None, description="地址")
    location: Location | None = Field(None, description="经纬度坐标")
    description: str | None = Field(None, description="描述")
    estimated_cost: int = Field(0, ge=0, description="预估费用(元)")


class Hotel(BaseModel):
    name: str = Field(..., description="酒店名称")
    address: str = Field("", description="酒店地址")
    location: Location | None = Field(None, description="酒店位置")
    price_range: str = Field("", description="价格范围")
    rating: str = Field("", description="评分")
    distance: str = Field("", description="距离景点距离")
    type: str = Field("", description="酒店类型")
    estimated_cost: int = Field(0, ge=0, description="预估费用(元/晚)")


class Budget(BaseModel):
    total_attractions: int = Field(0, ge=0, description="景点门票总费用")
    total_hotels: int = Field(0, ge=0, description="酒店总费用")
    total_meals: int = Field(0, ge=0, description="餐饮总费用")
    total_transportation: int = Field(0, ge=0, description="交通总费用")
    total: int = Field(0, ge=0, description="总费用")

    @model_validator(mode="after")
    def fill_total(self) -> "Budget":
        expected = (
            self.total_attractions
            + self.total_hotels
            + self.total_meals
            + self.total_transportation
        )
        if self.total == 0:
            self.total = expected
        return self


class PlanQuality(BaseModel):
    score: int = Field(100, ge=0, le=100, description="行程质量评分")
    warnings: list[str] = Field(default_factory=list, description="需要用户注意的问题")
    checks: dict[str, bool] = Field(default_factory=dict, description="质量检查结果")


class RouteLeg(BaseModel):
    origin: str = Field(..., description="起点名称")
    destination: str = Field(..., description="终点名称")
    distance_meters: int = Field(0, ge=0, description="距离(米)")
    duration_minutes: int = Field(0, ge=0, description="耗时(分钟)")
    mode: str = Field("", description="交通方式")


class DayPlan(BaseModel):
    date: str = Field(..., description="日期")
    day_index: int = Field(..., ge=0, description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿安排")
    hotel: Hotel | None = Field(None, description="酒店信息")
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
    forecast_available: bool = Field(True, description="是否有可信天气预报")
    notice: str | None = Field(None, description="天气提示")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value: object) -> int:
        if isinstance(value, str):
            cleaned = value.replace("degC", "").replace("°C", "").replace("℃", "").replace("°", "").strip()
            try:
                return int(float(cleaned))
            except ValueError:
                return 0
        return int(value)


class TripPlanRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=50, description="目的地城市")
    start_date: date = Field(..., description="开始日期")
    end_date: date | None = Field(None, description="结束日期")
    days: int = Field(3, ge=1, le=14, description="旅行天数")
    preferences: str = Field("历史文化", max_length=300, description="旅行偏好")
    budget: Literal["经济", "中等", "舒适", "豪华"] = Field("中等", description="预算档位")
    transportation: str = Field("公共交通", max_length=50, description="交通方式")
    accommodation: str = Field("经济型酒店", max_length=50, description="住宿偏好")

    @model_validator(mode="after")
    def normalize_dates(self) -> "TripPlanRequest":
        if self.end_date is None:
            self.end_date = self.start_date + timedelta(days=self.days - 1)
        else:
            delta_days = (self.end_date - self.start_date).days + 1
            if delta_days <= 0:
                raise ValueError("end_date must be greater than or equal to start_date")
            self.days = delta_days
        return self


class TripPlan(BaseModel):
    id: str | None = Field(None, description="行程ID")
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: list[DayPlan] = Field(default_factory=list, description="每日行程")
    weather_info: list[WeatherInfo] = Field(default_factory=list, description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Budget | None = Field(None, description="预算信息")
    quality: PlanQuality | None = Field(None, description="行程质量评估")


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
