-- 통합 마트 DDL (PostgreSQL). 단일 진실원천은 etl/schema.py(SQLAlchemy Core)이며
-- 본 파일은 수동 적용/리뷰용. 운영 변경은 Alembic 마이그레이션으로 관리한다.

CREATE TABLE IF NOT EXISTS dim_operator (
    operator_key   VARCHAR(64) PRIMARY KEY,
    display_name   VARCHAR(128) NOT NULL,
    "group"        VARCHAR(16)  NOT NULL,  -- mvno | mno
    network        VARCHAR(32),
    is_mvno        BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS fct_plan (
    plan_sk           SERIAL PRIMARY KEY,
    vendor            VARCHAR(64)  NOT NULL,
    plan_id           VARCHAR(128) NOT NULL,
    name              TEXT         NOT NULL,
    network_type      VARCHAR(32),
    data_allowance_mb INTEGER,
    voice_minutes     INTEGER,
    sms_count         INTEGER,
    data_unlimited    BOOLEAN DEFAULT FALSE,
    voice_unlimited   BOOLEAN DEFAULT FALSE,
    sms_unlimited     BOOLEAN DEFAULT FALSE,
    CONSTRAINT uq_fct_plan_natural_key UNIQUE (vendor, plan_id)
);

-- 가격 컴포넌트 SCD Type 2 이력(약정/선택약정/프로모션별 가격 변동 추적)
CREATE TABLE IF NOT EXISTS fct_plan_price (
    id                SERIAL PRIMARY KEY,
    vendor            VARCHAR(64)  NOT NULL,
    plan_id           VARCHAR(128) NOT NULL,
    price_type        VARCHAR(32)  NOT NULL,  -- 정상가/약정할인/선택약정/프로모션
    monthly_fee       DOUBLE PRECISION NOT NULL,
    commitment_months INTEGER,
    row_hash          VARCHAR(64)  NOT NULL,
    valid_from        TIMESTAMP    NOT NULL,
    valid_to          TIMESTAMP,              -- NULL = 현재 유효
    is_current        BOOLEAN      NOT NULL DEFAULT TRUE,
    collected_at      TIMESTAMP    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_fct_plan_price_current
    ON fct_plan_price (vendor, plan_id, price_type, is_current);
