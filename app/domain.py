"""Domain model.

Everything here is a plain dataclass. No I/O, no framework coupling — the
analytics modules operate on these types and nothing else, which is what makes
them independently testable and the what-if simulation nearly free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TxnType(str, Enum):
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"


class FeedStatus(str, Enum):
    FRESH = "fresh"
    DELAYED = "delayed"
    STALE = "stale"
    CONFLICTING = "conflicting"
    MISSING = "missing"


class AlertKind(str, Enum):
    LIQUIDITY = "liquidity"
    ANOMALY = "anomaly"
    DATA_QUALITY = "data_quality"
    COORDINATION = "coordination"


class Classification(str, Enum):
    NORMAL = "normal"
    DEMAND_SPIKE = "demand_spike"
    NEEDS_REVIEW = "needs_review"
    DATA_QUALITY = "data_quality"


class CaseStatus(str, Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    name_bn: str


@dataclass(frozen=True)
class Outlet:
    id: str
    name: str
    area: str
    thana: str
    district: str
    lat: float = 0.0
    lon: float = 0.0


@dataclass(frozen=True)
class Transaction:
    """A single agent-side transaction.

    Directionality is the whole product: a cash-out hands physical cash to the
    customer and takes e-money in return, so it drains the shared drawer and
    grows the provider balance. A cash-in does the exact opposite.
    """
    id: str
    outlet_id: str
    provider_id: str
    ts: float                      # epoch seconds
    type: TxnType
    amount: float
    status: str                    # success | failed | reversed
    sender_hash: str               # seeded pseudonym - never a real identity
    balance_after: float

    def cash_delta(self) -> float:
        """Effect on the shared physical cash drawer."""
        return -self.amount if self.type is TxnType.CASH_OUT else self.amount

    def emoney_delta(self) -> float:
        """Effect on this provider's e-money balance. Opposite of cash."""
        return self.amount if self.type is TxnType.CASH_OUT else -self.amount


@dataclass
class ProviderPosition:
    provider_id: str
    balance: float
    opening_balance: float
    last_feed_at: float | None
    feed_status: FeedStatus = FeedStatus.FRESH
    declared_drift: float = 0.0

    def declared_reconciles(self, computed: float,
                            tolerance: float = 0.01) -> bool:
        scale = max(abs(self.balance), 1.0)
        return abs(computed - self.balance) <= tolerance * scale


@dataclass
class OutletState:
    outlet: Outlet
    cash: float
    cash_opening: float
    positions: dict[str, ProviderPosition]
    transactions: list[Transaction] = field(default_factory=list)
    calendar_context: str = "ordinary"

    def provider_txns(self, provider_id: str) -> list[Transaction]:
        return [t for t in self.transactions if t.provider_id == provider_id]

    def total_value(self) -> float:
        return self.cash + sum(p.balance for p in self.positions.values())


@dataclass
class Alert:
    id: str
    outlet_id: str
    provider_id: str | None
    kind: AlertKind
    severity: str
    confidence: float
    reason: str
    # The same one-line reason in Bengali. The queue prints this string as each
    # alert's triage line, and the dashboard is Bengali by default, so a reason
    # with no Bengali twin showed an English sentence in the middle of the
    # queue. Everything else on the alert already carries both languages —
    # narrative_bn/en and parts_bn/en — so this is the field that was missing
    # rather than a new idea.
    reason_bn: str = ""
    evidence: list[str] = field(default_factory=list)
    uncertainty: str = ""
    classification: Classification = Classification.NORMAL
    rejected_hypotheses: list[tuple[str, str]] = field(default_factory=list)
    recommended_steps: list[str] = field(default_factory=list)
    status: CaseStatus = CaseStatus.NEW
    owner: str = ""
    assignee: str = ""
    created_at: float = 0.0
    # Populated by the narrative layer; kept on the alert so the API and the
    # UI never have to re-derive prose.
    narrative_bn: str = ""
    narrative_en: str = ""
    narrative_source: str = "template"
    # Structured, per-language copies of the four narrative parts. The UI
    # renders these rather than parsing the flattened strings above, so the
    # Bengali view shows Bengali evidence and Bengali next steps instead of
    # falling back to the English block.
    parts_bn: dict = field(default_factory=dict)
    parts_en: dict = field(default_factory=dict)
    # True when this alert exists because a projection was *withdrawn* rather
    # than made: the feed cannot be trusted, so nothing was estimated. Such an
    # alert is a statement about feed integrity, not about activity, so the
    # detection scoring deliberately does not count it. Without the separate
    # flag it was re-kinded to DATA_QUALITY and scored as a data-quality
    # detection — which coincided with a genuinely planted episode in the demo
    # and so hid inside the published false-positive rate instead of showing up.
    feed_withdrawn: bool = False


@dataclass
class CaseEvent:
    alert_id: str
    actor: str
    action: str
    note: str
    ts: float


@dataclass
class OutletRisk:
    """Area-level rollup used by hotspot mapping and prioritisation."""
    area: str
    district: str
    outlet_count: int
    at_risk_count: int
    total_cash: float
    total_emoney: float
    nearest_surplus_outlet: str | None = None
    nearest_surplus_provider: str | None = None
    nearest_surplus_value: float = 0.0
    distance_km: float | None = None


@dataclass
class NetworkNode:
    account_hash: str
    outlet_ids: list[str] = field(default_factory=list)
    provider_ids: list[str] = field(default_factory=list)
    txn_count: int = 0
    total_value: float = 0.0
    is_concentrated: bool = False


@dataclass
class NetworkEdge:
    source: str
    target: str
    shared_txns: int
    providers: list[str] = field(default_factory=list)
