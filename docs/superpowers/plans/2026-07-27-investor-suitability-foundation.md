# Investor Suitability Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, user-operated market-permission application flow for paper-trading accounts, independent of the chat Agent.

**Architecture:** Add versioned PostgreSQL suitability records beside the existing paper account, a pure rule evaluator, and a transaction service that atomically records disclosure acceptance and enables permissions. Expose authenticated REST endpoints and a dedicated React page; no Agent tool may mutate these records.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy/PostgreSQL, Pydantic v2, pytest, React 19, TypeScript, Ant Design, Vitest, Playwright.

---

## File map

- Create `backend/app/models/investor_suitability.py`: suitability profile, rule, assessment, disclosure, entitlement, and application tables.
- Create `backend/app/schemas/investor_suitability.py`: HTTP request/response contracts with Chinese field descriptions.
- Create `backend/app/services/investor_suitability/rules.py`: pure, versioned suitability evaluation.
- Create `backend/app/services/investor_suitability/service.py`: application state machine and atomic enablement.
- Create `backend/app/router/investor_suitability_router.py`: authenticated user-facing REST API.
- Modify `backend/app/models/__init__.py`: register new models with metadata.
- Modify `backend/app/app_main.py`: include the new router.
- Modify `backend/app/scripts/migrate_paper_trading_schema.py`: canonical upgrade and verification for existing databases.
- Create focused backend tests under `backend/tests/unit/services/investor_suitability/` and `backend/tests/integration/investor_suitability/`.
- Create `frontend/src/api/investorSuitability.ts`: typed client.
- Create `frontend/src/pages/market-permissions/`: permissions overview and application flow.
- Modify `frontend/src/router/routes.tsx`: add `/market-permissions` routes.

### Task 1: Persist suitability and permission facts

**Files:**
- Create: `backend/app/models/investor_suitability.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/integration/investor_suitability/test_models.py`

- [ ] **Step 1: Write failing model tests**

```python
def test_one_current_entitlement_per_account_and_market(db_session, paper_account):
    db_session.add_all([
        MarketEntitlement.new(account=paper_account, market=Market.STAR),
        MarketEntitlement.new(account=paper_account, market=Market.STAR),
    ])
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cancelled_application_cannot_reference_enabled_entitlement(db_session, application):
    application.status = ApplicationStatus.CANCELLED_BY_USER
    application.enabled_entitlement_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest backend/tests/integration/investor_suitability/test_models.py -q`

Expected: FAIL because `app.models.investor_suitability` does not exist.

- [ ] **Step 3: Add enums and focused ORM models**

```python
class Market(enum.StrEnum):
    MAIN = "main"
    CHINEXT = "chinext"
    STAR = "star"
    BSE = "bse"


class EntitlementStatus(enum.StrEnum):
    NOT_APPLIED = "not_applied"
    PENDING_DISCLOSURE = "pending_disclosure"
    ENABLED = "enabled"
    RESTRICTED = "restricted"
    REVOKED = "revoked"


class ApplicationStatus(enum.StrEnum):
    IN_PROGRESS = "in_progress"
    AWAITING_INFORMATION = "awaiting_information"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CANCELLED_BY_USER = "cancelled_by_user"
    EXPIRED = "expired"
    REJECTED = "rejected"
    COMPLETED = "completed"
```

Create six tables named `investor_suitability_profiles`, `market_access_rules`, `suitability_assessments`, `risk_disclosure_acceptances`, `market_entitlements`, and `entitlement_applications`. Use UUID primary keys, account-generation foreign keys where the record belongs to a paper account, JSONB only for immutable submitted snapshots and failed-condition arrays, and check constraints for finite/non-negative assets and experience months. Add a unique `(account_id, account_generation, market)` key for the current entitlement and a unique `(market, rule_version)` key for rules.

- [ ] **Step 4: Register every model and rerun tests**

Run: `uv run pytest backend/tests/integration/investor_suitability/test_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the model slice**

```powershell
git add backend/app/models/investor_suitability.py backend/app/models/__init__.py backend/tests/integration/investor_suitability/test_models.py
git commit -m "feat(suitability): add durable market permission facts"
```

### Task 2: Add versioned rules and deterministic evaluation

**Files:**
- Create: `backend/app/services/investor_suitability/__init__.py`
- Create: `backend/app/services/investor_suitability/rules.py`
- Create: `backend/app/services/investor_suitability/rules/a_share_20260727.json`
- Test: `backend/tests/unit/services/investor_suitability/test_rules.py`

- [ ] **Step 1: Write failing rule tests**

```python
@pytest.mark.parametrize(
    ("market", "assets", "months", "allowed", "codes"),
    [
        (Market.MAIN, Decimal("0"), 0, True, ()),
        (Market.CHINEXT, Decimal("99999.99"), 24, False, ("assets_below_minimum",)),
        (Market.CHINEXT, Decimal("100000"), 24, True, ()),
        (Market.STAR, Decimal("500000"), 23, False, ("experience_below_minimum",)),
        (Market.BSE, Decimal("500000"), 24, True, ()),
    ],
)
def test_evaluate_market_access(market, assets, months, allowed, codes):
    result = evaluate_market_access(rulebook(), market, assets, months)
    assert result.allowed is allowed
    assert tuple(item.code for item in result.failed_conditions) == codes
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/services/investor_suitability/test_rules.py -q`

Expected: FAIL because `evaluate_market_access` is missing.

- [ ] **Step 3: Implement immutable rule contracts and evaluator**

```python
class FailedCondition(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: Literal["assets_below_minimum", "experience_below_minimum"]
    actual: Decimal | int
    required: Decimal | int


class AssessmentDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    allowed: bool
    failed_conditions: tuple[FailedCondition, ...]
    rule_version: str


def evaluate_market_access(
    rules: MarketRuleBook,
    market: Market,
    average_assets_20d: Decimal,
    experience_months: int,
) -> AssessmentDecision:
    rule = rules.current(market)
    failures = []
    if rule.minimum_average_assets_20d is not None and average_assets_20d < rule.minimum_average_assets_20d:
        failures.append(FailedCondition(code="assets_below_minimum", actual=average_assets_20d, required=rule.minimum_average_assets_20d))
    if rule.minimum_experience_months is not None and experience_months < rule.minimum_experience_months:
        failures.append(FailedCondition(code="experience_below_minimum", actual=experience_months, required=rule.minimum_experience_months))
    return AssessmentDecision(allowed=not failures, failed_conditions=tuple(failures), rule_version=rule.rule_version)
```

The JSON fixture must contain main board with null thresholds, ChiNext with `100000/24`, STAR with `500000/24`, and BSE with `500000/24`, plus one disclosure version per market.

- [ ] **Step 4: Run rule tests**

Run: `uv run pytest backend/tests/unit/services/investor_suitability/test_rules.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/investor_suitability backend/tests/unit/services/investor_suitability/test_rules.py
git commit -m "feat(suitability): add versioned access rules"
```

### Task 3: Implement the application state machine and atomic enablement

**Files:**
- Create: `backend/app/services/investor_suitability/service.py`
- Test: `backend/tests/integration/investor_suitability/test_service.py`

- [ ] **Step 1: Write failing transaction tests**

```python
def test_confirm_atomically_records_disclosure_and_enables_permission(service, eligible_application):
    entitlement = service.confirm(
        user_id=eligible_application.user_id,
        application_id=eligible_application.id,
        disclosure_version="star-2026-01",
        idempotency_key="confirm-1",
    )
    assert entitlement.status is EntitlementStatus.ENABLED
    assert entitlement.can_buy is True
    assert entitlement.can_sell is True
    assert service.disclosure_for(eligible_application.id).accepted_at is not None


def test_cancel_never_creates_disclosure_or_permission(service, awaiting_application):
    service.cancel(user_id=awaiting_application.user_id, application_id=awaiting_application.id)
    assert service.disclosure_for(awaiting_application.id) is None
    assert service.entitlement_for(awaiting_application.account_id, awaiting_application.market) is None
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/investor_suitability/test_service.py -q`

Expected: FAIL because `SuitabilityApplicationService` is missing.

- [ ] **Step 3: Implement explicit service methods**

```python
class SuitabilityApplicationService:
    def start(self, *, user_id: UUID, account_id: UUID, market: Market, idempotency_key: str) -> EntitlementApplication: ...
    def submit_profile(self, *, user_id: UUID, application_id: UUID, average_assets_20d: Decimal, experience_months: int, risk_level: str) -> SuitabilityAssessment: ...
    def confirm(self, *, user_id: UUID, application_id: UUID, disclosure_version: str, idempotency_key: str) -> MarketEntitlement: ...
    def cancel(self, *, user_id: UUID, application_id: UUID) -> EntitlementApplication: ...
    def list_entitlements(self, *, user_id: UUID, account_id: UUID) -> list[MarketEntitlement]: ...
```

`confirm` must lock the application, active account generation, current rule and current entitlement; rerun evaluation against the stored snapshot; reject a stale disclosure version; insert disclosure and entitlement changes in the caller's transaction; and make repeated use of the same idempotency key return the same result.

- [ ] **Step 4: Run service and concurrency tests**

Run: `uv run pytest backend/tests/integration/investor_suitability/test_service.py -q`

Expected: PASS, including concurrent confirmation with exactly one enabled entitlement.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/investor_suitability/service.py backend/tests/integration/investor_suitability/test_service.py
git commit -m "feat(suitability): add permission application workflow"
```

### Task 4: Add canonical schema migration and verification

**Files:**
- Modify: `backend/app/scripts/migrate_paper_trading_schema.py`
- Test: `backend/tests/integration/test_paper_trading_schema_upgrade.py`

- [ ] **Step 1: Add a failing legacy-upgrade test**

```python
def test_upgrade_adds_canonical_suitability_schema(legacy_application_engine):
    changes = migrate_paper_trading_schema(legacy_application_engine)
    assert "create investor suitability schema" in changes
    assert canonical_suitability_schema(legacy_application_engine) is True
    assert migrate_paper_trading_schema(legacy_application_engine) == ()
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/test_paper_trading_schema_upgrade.py::test_upgrade_adds_canonical_suitability_schema -q`

Expected: FAIL because the migration does not create or verify the new objects.

- [ ] **Step 3: Extend migration checks**

Add explicit catalog verification for every table, column type, check constraint, unique index, foreign key, and enum value. Follow the existing fail-closed pattern and compare canonical trigger details if a trigger is added; object names alone are not sufficient evidence.

```python
def canonical_suitability_schema(engine: Engine) -> bool:
    required = {
        "investor_suitability_profiles",
        "market_access_rules",
        "suitability_assessments",
        "risk_disclosure_acceptances",
        "market_entitlements",
        "entitlement_applications",
    }
    return required <= _table_names(engine) and _suitability_constraints_match(engine)
```

- [ ] **Step 4: Run migration tests twice**

Run: `uv run pytest backend/tests/integration/test_paper_trading_schema_upgrade.py -q`

Expected: PASS, including idempotent second invocation and rejection of a same-name/wrong-definition object.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/scripts/migrate_paper_trading_schema.py backend/tests/integration/test_paper_trading_schema_upgrade.py
git commit -m "feat(db): migrate investor suitability schema"
```

### Task 5: Expose authenticated permission-application APIs

**Files:**
- Create: `backend/app/schemas/investor_suitability.py`
- Create: `backend/app/router/investor_suitability_router.py`
- Modify: `backend/app/app_main.py`
- Test: `backend/tests/integration/investor_suitability/test_endpoints.py`

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_user_can_start_submit_cancel_and_confirm_application(client, auth_headers):
    started = client.post("/api/v0/market-permissions/star/applications", headers=auth_headers, json={}).json()
    assessed = client.put(
        f"/api/v0/market-permissions/applications/{started['application_id']}/profile",
        headers=auth_headers,
        json={"declared_average_assets_20d": "600000.00", "securities_experience_months": 36, "risk_level": "C4"},
    ).json()
    assert assessed["decision"] == "passed"
```

Also test cross-user 404, stale disclosure 409, incomplete profile 422, repeated confirmation idempotency, and cancelled application remaining disabled.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/investor_suitability/test_endpoints.py -q`

Expected: FAIL with route not found.

- [ ] **Step 3: Add schemas and routes**

```python
router = APIRouter(prefix="/api/v0/market-permissions", tags=["market-permissions"])

@router.get("", response_model=list[MarketEntitlementRead])
def list_permissions(...): ...

@router.post("/{market}/applications", response_model=ApplicationRead)
def start_application(...): ...

@router.put("/applications/{application_id}/profile", response_model=AssessmentRead)
def submit_profile(...): ...

@router.post("/applications/{application_id}/confirm", response_model=MarketEntitlementRead)
def confirm_application(...): ...

@router.post("/applications/{application_id}/cancel", response_model=ApplicationRead)
def cancel_application(...): ...
```

Every schema field must include a Chinese `description`, and errors must return stable machine codes plus plain Chinese messages.

- [ ] **Step 4: Run endpoint tests**

Run: `uv run pytest backend/tests/integration/investor_suitability/test_endpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/schemas/investor_suitability.py backend/app/router/investor_suitability_router.py backend/app/app_main.py backend/tests/integration/investor_suitability/test_endpoints.py
git commit -m "feat(api): expose market permission applications"
```

### Task 6: Build the independent market-permission page

**Files:**
- Create: `frontend/src/api/investorSuitability.ts`
- Create: `frontend/src/pages/market-permissions/index.tsx`
- Create: `frontend/src/pages/market-permissions/application.tsx`
- Create: `frontend/src/pages/market-permissions/index.module.scss`
- Modify: `frontend/src/router/routes.tsx`
- Test: `frontend/src/pages/market-permissions/__tests__/application.test.tsx`

- [ ] **Step 1: Write failing UI tests**

```tsx
it('lets the user cancel at the disclosure step without enabling permission', async () => {
  render(<PermissionApplicationPage />)
  await userEvent.type(screen.getByLabelText('最近20个交易日日均资产'), '600000')
  await userEvent.type(screen.getByLabelText('证券交易经验月数'), '36')
  await userEvent.click(screen.getByRole('button', { name: '检查开通条件' }))
  await userEvent.click(screen.getByRole('button', { name: '取消申请' }))
  expect(cancelApplication).toHaveBeenCalledOnce()
  expect(confirmApplication).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/pages/market-permissions/__tests__/application.test.tsx`

Workdir: `frontend`

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement typed API and routes**

```tsx
{ path: '/market-permissions', Component: MarketPermissionsPage },
{ path: '/market-permissions/:market/apply', Component: PermissionApplicationPage },
```

The application page must display Chinese explanations for every field, the declared-not-verified warning, failed conditions with actual/required values, the complete disclosure text, separate cancel and final-confirm actions, and an already-enabled short circuit.

- [ ] **Step 4: Run UI tests and build**

Run: `npm test -- src/pages/market-permissions/__tests__/application.test.tsx && npm run build`

Workdir: `frontend`

Expected: PASS and successful Vite build.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api/investorSuitability.ts frontend/src/pages/market-permissions frontend/src/router/routes.tsx
git commit -m "feat(frontend): add market permission application flow"
```

### Task 7: Prove the standalone flow end to end

**Files:**
- Create: `frontend/tests/e2e/market-permissions.spec.ts`
- Modify: `docs/claude-context/paper-trading-runtime-adaptation-done.md`

- [ ] **Step 1: Add Playwright scenarios**

```ts
test('eligible user can apply, cancel, and later complete without any chat run', async ({ page }) => {
  await page.goto('/market-permissions/star/apply')
  await page.getByLabel('最近20个交易日日均资产').fill('600000')
  await page.getByLabel('证券交易经验月数').fill('36')
  await page.getByRole('button', { name: '检查开通条件' }).click()
  await expect(page.getByText('等待签署风险揭示书')).toBeVisible()
  await page.getByRole('button', { name: '取消申请' }).click()
  await expect(page.getByText('申请已取消')).toBeVisible()
})
```

- [ ] **Step 2: Run focused backend and frontend suites**

Run: `uv run pytest backend/tests/unit/services/investor_suitability backend/tests/integration/investor_suitability backend/tests/integration/test_paper_trading_schema_upgrade.py -q`

Run: `npm test -- src/pages/market-permissions && npx playwright test tests/e2e/market-permissions.spec.ts`

Workdir for frontend commands: `frontend`

Expected: all PASS. If Playwright is blocked by the local Windows environment, record the exact failure and do not claim browser evidence.

- [ ] **Step 3: Update the project context card with actual evidence**

Record only commands actually run and results actually observed. State explicitly that this phase does not yet connect the Agent.

- [ ] **Step 4: Commit**

```powershell
git add frontend/tests/e2e/market-permissions.spec.ts docs/claude-context/paper-trading-runtime-adaptation-done.md
git commit -m "test: verify standalone market permission flow"
```
