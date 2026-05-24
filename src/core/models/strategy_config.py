from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
import json
import os

@dataclass
class StrategyMetadata:
    strategy_id: str
    strategy_name: str
    status: str = "ALPHA_DRAFT"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metrics_schema_version: Optional[str] = None
    t_stat_method: Optional[str] = None
    p_value_method: Optional[str] = None

@dataclass
class EnvironmentConfig:
    universe: str = "unknown"
    timeframe: str = "unknown"

@dataclass
class AlphaPipelineConfig:
    expression: str = ""
    winsor_method: Optional[str] = None
    quantile_lb: Optional[float] = None
    quantile_ub: Optional[float] = None
    risk_factors: List[str] = field(default_factory=list)
    ridge_alpha: Optional[float] = None
    auto_drop_zero_vol: bool = False

@dataclass
class BacktestProfile:
    settings: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, float]] = None

@dataclass
class RiskAudit:
    status: str = "PENDING"
    details: Optional[Dict[str, Any]] = None

@dataclass
class StrategyConfig:
    """Strategy JSON DNA (Baton Relay Root Object)"""
    metadata: StrategyMetadata
    environment_config: EnvironmentConfig
    alpha_pipeline: AlphaPipelineConfig
    backtest_profile: BacktestProfile = field(default_factory=BacktestProfile)
    risk_audit: RiskAudit = field(default_factory=RiskAudit)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyConfig":
        return cls(
            metadata=StrategyMetadata(**data.get("metadata", {})),
            environment_config=EnvironmentConfig(**data.get("environment_config", {})),
            alpha_pipeline=AlphaPipelineConfig(**data.get("alpha_pipeline", {})),
            backtest_profile=BacktestProfile(**data.get("backtest_profile", {})),
            risk_audit=RiskAudit(**data.get("risk_audit", {}))
        )

    @classmethod
    def from_json(cls, filepath: str) -> "StrategyConfig":
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Config API not found: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)
