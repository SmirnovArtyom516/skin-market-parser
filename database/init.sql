-- Расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Скины CS2
CREATE TABLE skins (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    market_hash_name  VARCHAR(255) UNIQUE NOT NULL,  -- уникальное имя на Steam
    name        VARCHAR(255) NOT NULL,
    weapon      VARCHAR(100),
    skin_name   VARCHAR(100),
    quality     VARCHAR(50),                          -- Factory New, Field-Tested и т.д.
    rarity      VARCHAR(50),                          -- Covert, Classified и т.д.
    is_stattrak BOOLEAN DEFAULT FALSE,
    is_souvenir BOOLEAN DEFAULT FALSE,
    image_url   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- История цен
CREATE TABLE price_history (
    id          BIGSERIAL PRIMARY KEY,
    skin_id     UUID NOT NULL REFERENCES skins(id) ON DELETE CASCADE,
    source      VARCHAR(50) NOT NULL,                 -- skinport, csfloat, dmarket и т.д.
    price_usd   NUMERIC(12, 2) NOT NULL,
    volume_24h  INTEGER,                              -- кол-во продаж за 24 часа
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индекс для быстрого получения последних цен
CREATE INDEX idx_price_history_skin_time ON price_history (skin_id, recorded_at DESC);
CREATE INDEX idx_price_history_source ON price_history (source, recorded_at DESC);

-- Агрегированные цены (OHLC по периодам, чтобы не хранить каждый тик)
CREATE TABLE price_aggregates (
    id          BIGSERIAL PRIMARY KEY,
    skin_id     UUID NOT NULL REFERENCES skins(id) ON DELETE CASCADE,
    source      VARCHAR(50) NOT NULL,
    period      VARCHAR(10) NOT NULL,                 -- '1h', '24h', '7d'
    price_open  NUMERIC(12, 2),
    price_close NUMERIC(12, 2),
    price_high  NUMERIC(12, 2),
    price_low   NUMERIC(12, 2),
    price_avg   NUMERIC(12, 2),
    volume      INTEGER,
    period_start TIMESTAMPTZ NOT NULL,
    period_end   TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_price_agg_skin_period ON price_aggregates (skin_id, period, period_start DESC);

-- Новости и события
CREATE TABLE news_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source      VARCHAR(100) NOT NULL,                -- hltv, steam, reddit, twitter
    source_url  TEXT,
    title       TEXT NOT NULL,
    content     TEXT,
    event_type  VARCHAR(50),                          -- patch, major, trade_ban, case_drop, team_news
    sentiment   SMALLINT,                             -- -1 негативный, 0 нейтральный, 1 позитивный
    published_at TIMESTAMPTZ,
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    is_processed BOOLEAN DEFAULT FALSE                -- обработана ли AI-сервисом
);

CREATE INDEX idx_news_type_time ON news_events (event_type, published_at DESC);
CREATE INDEX idx_news_unprocessed ON news_events (is_processed, collected_at) WHERE is_processed = FALSE;

-- Связь новости → затронутые скины
CREATE TABLE news_skin_impact (
    id          BIGSERIAL PRIMARY KEY,
    news_id     UUID NOT NULL REFERENCES news_events(id) ON DELETE CASCADE,
    skin_id     UUID NOT NULL REFERENCES skins(id) ON DELETE CASCADE,
    impact_score NUMERIC(5, 2),                       -- насколько сильно событие влияет на скин
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Рекомендации AI
CREATE TABLE recommendations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skin_id         UUID NOT NULL REFERENCES skins(id) ON DELETE CASCADE,
    action          VARCHAR(20) NOT NULL,              -- 'buy', 'sell', 'watch'
    confidence      NUMERIC(5, 2) NOT NULL,            -- 0-100%
    target_price    NUMERIC(12, 2),
    current_price   NUMERIC(12, 2),
    potential_roi   NUMERIC(8, 2),                    -- потенциальный ROI в %
    reasoning       TEXT,                             -- объяснение от AI
    news_ids        UUID[],                           -- какие новости повлияли
    time_horizon    VARCHAR(20),                      -- 'short' (1-7d), 'medium' (7-30d), 'long' (30d+)
    status          VARCHAR(20) DEFAULT 'active',     -- active, expired, executed
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);

CREATE INDEX idx_recommendations_active ON recommendations (status, created_at DESC) WHERE status = 'active';

-- Результаты рекомендаций (для отслеживания точности)
CREATE TABLE recommendation_outcomes (
    id                  BIGSERIAL PRIMARY KEY,
    recommendation_id   UUID NOT NULL REFERENCES recommendations(id),
    price_at_7d         NUMERIC(12, 2),
    price_at_14d        NUMERIC(12, 2),
    price_at_30d        NUMERIC(12, 2),
    actual_roi_7d       NUMERIC(8, 2),
    actual_roi_30d      NUMERIC(8, 2),
    evaluated_at        TIMESTAMPTZ DEFAULT NOW()
);
