"""Fixed benchmark dataset (docs/evaluation.md §2, brief §24-25).

`BenchmarkQuestion` records everything the harness needs to run one question
through the graph and score it: the question itself, its category (one of
the 7 fixed in docs/evaluation.md §2), the research dimensions a good plan
should cover, a small curated ground-truth evidence set used for
claim-verification-accuracy scoring, the alternatives/criteria a reasonable
plan is expected to surface, and free-text evaluation notes for a human
reviewer. `BENCHMARK` is deliberately static (no generation, no LLM calls) so
the harness is reproducible run to run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BenchmarkCategory = Literal[
    "technology_selection",
    "architecture",
    "cloud",
    "business",
    "product",
    "security",
    "engineering",
]

ClaimStatus = Literal[
    "VERIFIED", "PARTIALLY_VERIFIED", "CONTRADICTED", "UNSUPPORTED", "OUTDATED"
]


class KnownEvidenceItem(BaseModel):
    """One curated ground-truth fact for claim-verification-accuracy scoring
    (docs/evaluation.md §1 "Claim verification accuracy"). `text` is matched
    against extracted `Claim.text` (case-insensitive substring) by
    `metrics.claim_verification_accuracy`; `expected_status` is the label
    that claim's `ClaimVerification.status` is compared against."""

    text: str
    expected_status: ClaimStatus = "VERIFIED"


class BenchmarkQuestion(BaseModel):
    id: str
    question: str
    category: BenchmarkCategory
    expected_research_dimensions: list[str] = Field(default_factory=list)
    known_evidence: list[KnownEvidenceItem] = Field(default_factory=list)
    expected_alternatives: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


BENCHMARK: list[BenchmarkQuestion] = [
    # -- technology_selection --
    BenchmarkQuestion(
        id="tech-01",
        question="Should a startup use PostgreSQL + pgvector or a dedicated vector database?",
        category="technology_selection",
        expected_research_dimensions=["cost", "operational complexity", "query performance"],
        known_evidence=[
            KnownEvidenceItem(text="pgvector adds vector search to an existing Postgres instance"),
            KnownEvidenceItem(text="dedicated vector databases scale ANN search independently"),
        ],
        expected_alternatives=["PostgreSQL + pgvector", "Dedicated vector database"],
        evaluation_criteria=["cost", "operational complexity", "query performance"],
        constraints=["team of 3 engineers", "budget < $5k/mo"],
    ),
    BenchmarkQuestion(
        id="tech-02",
        question="Should a mid-size SaaS product adopt Kafka or a simpler queue like SQS/RabbitMQ for event streaming?",
        category="technology_selection",
        expected_research_dimensions=["throughput requirements", "operational overhead", "ecosystem maturity"],
        known_evidence=[
            KnownEvidenceItem(text="Kafka is designed for high-throughput durable event streaming"),
            KnownEvidenceItem(text="managed queues like SQS reduce operational burden for lower-throughput workloads"),
        ],
        expected_alternatives=["Kafka", "SQS", "RabbitMQ"],
        evaluation_criteria=["throughput", "operational overhead", "cost"],
    ),
    BenchmarkQuestion(
        id="tech-03",
        question="Should a data team pick Snowflake or a self-managed Postgres warehouse for analytics?",
        category="technology_selection",
        expected_research_dimensions=["cost at scale", "query performance", "maintenance burden"],
        expected_alternatives=["Snowflake", "self-managed Postgres warehouse"],
        evaluation_criteria=["cost", "scalability", "maintenance burden"],
    ),
    # -- architecture --
    BenchmarkQuestion(
        id="arch-01",
        question="Should a 5-person engineering team build a monolith or microservices for their new product?",
        category="architecture",
        expected_research_dimensions=["team size fit", "deployment complexity", "long-term scalability"],
        known_evidence=[
            KnownEvidenceItem(text="microservices introduce distributed-systems operational overhead"),
            KnownEvidenceItem(text="a monolith is simpler to deploy and reason about for small teams"),
        ],
        expected_alternatives=["monolith", "microservices"],
        evaluation_criteria=["team velocity", "operational complexity", "scalability"],
        constraints=["team of 5 engineers", "pre-product-market-fit"],
    ),
    BenchmarkQuestion(
        id="arch-02",
        question="Should the system use event-driven architecture or synchronous request/response between internal services?",
        category="architecture",
        expected_research_dimensions=["coupling", "latency", "failure isolation"],
        expected_alternatives=["event-driven architecture", "synchronous request/response"],
        evaluation_criteria=["coupling", "latency", "resilience"],
    ),
    BenchmarkQuestion(
        id="arch-03",
        question="Should a growing platform move to a multi-tenant single-database model or a database-per-tenant model?",
        category="architecture",
        expected_research_dimensions=["isolation guarantees", "operational cost", "scaling limits"],
        expected_alternatives=["single database, multi-tenant schema", "database-per-tenant"],
        evaluation_criteria=["isolation", "cost", "operational complexity"],
    ),
    # -- cloud --
    BenchmarkQuestion(
        id="cloud-01",
        question="Should a data-heavy workload run on AWS, GCP, or be self-hosted?",
        category="cloud",
        expected_research_dimensions=["cost at scale", "managed-service maturity", "vendor lock-in"],
        known_evidence=[
            KnownEvidenceItem(text="self-hosting trades lower unit cost for higher operational burden"),
        ],
        expected_alternatives=["AWS", "GCP", "self-hosted"],
        evaluation_criteria=["cost", "vendor lock-in", "operational maturity"],
        constraints=["data-heavy workload", "small platform team"],
    ),
    BenchmarkQuestion(
        id="cloud-02",
        question="Should a company adopt a multi-cloud strategy or standardize on a single cloud provider?",
        category="cloud",
        expected_research_dimensions=["resilience to outages", "operational complexity", "negotiating leverage"],
        expected_alternatives=["multi-cloud", "single cloud provider"],
        evaluation_criteria=["resilience", "operational complexity", "cost"],
    ),
    BenchmarkQuestion(
        id="cloud-03",
        question="Should a workload run on Kubernetes or a simpler managed container platform like AWS Fargate/Cloud Run?",
        category="cloud",
        expected_research_dimensions=["operational overhead", "flexibility", "cost"],
        expected_alternatives=["Kubernetes", "managed container platform"],
        evaluation_criteria=["operational overhead", "flexibility", "cost"],
    ),
    # -- business --
    BenchmarkQuestion(
        id="biz-01",
        question="Should a new SaaS product launch with a freemium model or paid-only from day one?",
        category="business",
        expected_research_dimensions=["customer acquisition cost", "conversion rates", "support cost"],
        known_evidence=[
            KnownEvidenceItem(text="freemium models tend to lower customer acquisition cost while increasing support load"),
        ],
        expected_alternatives=["freemium", "paid-only"],
        evaluation_criteria=["acquisition cost", "conversion rate", "revenue predictability"],
    ),
    BenchmarkQuestion(
        id="biz-02",
        question="Should a startup prioritize expanding into a new geographic market or deepening its existing market first?",
        category="business",
        expected_research_dimensions=["market saturation", "localization cost", "competitive pressure"],
        expected_alternatives=["expand geographically", "deepen existing market"],
        evaluation_criteria=["growth potential", "cost", "risk"],
    ),
    BenchmarkQuestion(
        id="biz-03",
        question="Should a company build its sales motion around self-serve signups or an outbound enterprise sales team?",
        category="business",
        expected_research_dimensions=["deal size", "sales cycle length", "product complexity"],
        expected_alternatives=["self-serve", "outbound enterprise sales"],
        evaluation_criteria=["cost of sale", "deal size", "scalability"],
    ),
    # -- product --
    BenchmarkQuestion(
        id="prod-01",
        question="Should a new consumer app be built mobile-first or web-first for its MVP?",
        category="product",
        expected_research_dimensions=["target user behavior", "development cost", "time to market"],
        known_evidence=[
            KnownEvidenceItem(text="mobile-first suits apps with frequent, on-the-go usage patterns"),
        ],
        expected_alternatives=["mobile-first", "web-first"],
        evaluation_criteria=["development cost", "time to market", "fit with user behavior"],
    ),
    BenchmarkQuestion(
        id="prod-02",
        question="Should the product team ship a broad set of shallow features or a narrow set of deep features for the initial release?",
        category="product",
        expected_research_dimensions=["user retention drivers", "development capacity", "competitive differentiation"],
        expected_alternatives=["broad shallow feature set", "narrow deep feature set"],
        evaluation_criteria=["user retention", "differentiation", "development cost"],
    ),
    BenchmarkQuestion(
        id="prod-03",
        question="Should onboarding be a guided step-by-step wizard or a flexible, exploratory blank-canvas experience?",
        category="product",
        expected_research_dimensions=["user activation rate", "product complexity", "target user sophistication"],
        expected_alternatives=["guided wizard onboarding", "exploratory blank-canvas onboarding"],
        evaluation_criteria=["activation rate", "time to value", "user sophistication fit"],
    ),
    # -- security --
    BenchmarkQuestion(
        id="sec-01",
        question="Should the company build its own SSO/identity system or buy a managed identity provider (e.g. Auth0/Okta)?",
        category="security",
        expected_research_dimensions=["security risk surface", "engineering cost", "compliance requirements"],
        known_evidence=[
            KnownEvidenceItem(text="managed identity providers reduce the in-house security risk surface for authentication"),
        ],
        expected_alternatives=["build in-house SSO/identity", "buy a managed identity provider"],
        evaluation_criteria=["security risk", "cost", "time to implement"],
    ),
    BenchmarkQuestion(
        id="sec-02",
        question="Should application secrets be stored in a dedicated secrets manager (e.g. Vault/AWS Secrets Manager) or encrypted environment variables?",
        category="security",
        expected_research_dimensions=["rotation capability", "audit trail", "operational cost"],
        expected_alternatives=["dedicated secrets manager", "encrypted environment variables"],
        evaluation_criteria=["security posture", "operational cost", "auditability"],
    ),
    BenchmarkQuestion(
        id="sec-03",
        question="Should the API use API-key authentication or OAuth2/OIDC for third-party integrations?",
        category="security",
        expected_research_dimensions=["integration complexity", "security guarantees", "developer experience"],
        expected_alternatives=["API-key authentication", "OAuth2/OIDC"],
        evaluation_criteria=["security", "integration complexity", "developer experience"],
    ),
    # -- engineering --
    BenchmarkQuestion(
        id="eng-01",
        question="Should a public API be designed as REST or GraphQL?",
        category="engineering",
        expected_research_dimensions=["client flexibility", "caching behavior", "learning curve"],
        known_evidence=[
            KnownEvidenceItem(text="GraphQL lets clients request exactly the fields they need"),
            KnownEvidenceItem(text="REST benefits from simpler, well-understood HTTP caching semantics"),
        ],
        expected_alternatives=["REST", "GraphQL"],
        evaluation_criteria=["client flexibility", "caching", "learning curve"],
    ),
    BenchmarkQuestion(
        id="eng-02",
        question="Should the team adopt trunk-based development or long-lived feature branches for its git workflow?",
        category="engineering",
        expected_research_dimensions=["merge conflict frequency", "release cadence", "CI/CD maturity"],
        expected_alternatives=["trunk-based development", "long-lived feature branches"],
        evaluation_criteria=["merge overhead", "release cadence", "risk of integration issues"],
    ),
    BenchmarkQuestion(
        id="eng-03",
        question="Should the team write end-to-end tests with a heavy UI-automation suite or invest primarily in unit and contract tests?",
        category="engineering",
        expected_research_dimensions=["test suite runtime", "flakiness", "coverage of integration risk"],
        expected_alternatives=["heavy UI-automation E2E suite", "unit + contract tests"],
        evaluation_criteria=["reliability", "runtime cost", "coverage of integration risk"],
    ),
    BenchmarkQuestion(
        id="eng-04",
        question="Should the team migrate to strict static typing across the codebase or keep it dynamically typed with runtime validation?",
        category="engineering",
        expected_research_dimensions=["migration cost", "defect rate", "developer velocity"],
        expected_alternatives=["migrate to static typing", "stay dynamically typed with runtime validation"],
        evaluation_criteria=["defect rate", "migration cost", "developer velocity"],
    ),
]

assert len(BENCHMARK) >= 20, "benchmark must have at least 20 questions per docs/evaluation.md §2"
assert {q.category for q in BENCHMARK} == set(BenchmarkCategory.__args__), (  # type: ignore[attr-defined]
    "benchmark must cover all 7 categories fixed in docs/evaluation.md §2"
)
