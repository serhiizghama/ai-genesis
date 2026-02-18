-- AI-Genesis PostgreSQL Schema
-- Applied automatically at startup via connection.py

-- World checkpoints (every ~60 sec or 3750 ticks at 62.5 TPS)
CREATE TABLE IF NOT EXISTS world_checkpoints (
    id SERIAL PRIMARY KEY,
    tick BIGINT NOT NULL,
    params JSONB NOT NULL,
    entity_count INT NOT NULL,
    avg_energy FLOAT,
    resource_count INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Entity snapshots linked to checkpoints
CREATE TABLE IF NOT EXISTS entity_snapshots (
    id SERIAL PRIMARY KEY,
    checkpoint_id INT REFERENCES world_checkpoints(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL,
    x FLOAT NOT NULL,
    y FLOAT NOT NULL,
    energy FLOAT NOT NULL,
    max_energy FLOAT NOT NULL,
    age INT NOT NULL,
    traits JSONB NOT NULL,
    state VARCHAR(20) NOT NULL,
    parent_id UUID
);
CREATE INDEX IF NOT EXISTS idx_entity_snapshots_checkpoint ON entity_snapshots(checkpoint_id);

-- Mutations with source code (no TTL, permanent)
CREATE TABLE IF NOT EXISTS mutations (
    id SERIAL PRIMARY KEY,
    mutation_id VARCHAR(64) UNIQUE NOT NULL,
    trait_name VARCHAR(255) NOT NULL,
    version INT NOT NULL,
    code_hash VARCHAR(64) NOT NULL,
    source_code TEXT NOT NULL,
    cycle_id VARCHAR(64),
    trigger_type VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    is_active BOOLEAN DEFAULT TRUE,
    applied_at TIMESTAMPTZ,
    failed_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Evolution cycles (full history)
CREATE TABLE IF NOT EXISTS evolution_cycles (
    id SERIAL PRIMARY KEY,
    cycle_id VARCHAR(64) UNIQUE NOT NULL,
    problem_type VARCHAR(50),
    severity VARCHAR(20),
    stage VARCHAR(20),
    mutation_id VARCHAR(64),
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Agent feed log (history for UI on restart)
CREATE TABLE IF NOT EXISTS feed_messages (
    id SERIAL PRIMARY KEY,
    agent VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB,
    cycle_id VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feed_messages_created ON feed_messages(created_at DESC);
