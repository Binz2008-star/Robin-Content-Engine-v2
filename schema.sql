CREATE TABLE IF NOT EXISTS video_queue (
    id BIGSERIAL PRIMARY KEY,
    source_path TEXT,
    source_url TEXT,
    source_title TEXT NOT NULL,
    rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    rights_note TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'rendered', 'uploaded', 'failed', 'quarantined')),
    generated_title TEXT,
    generated_description TEXT,
    generated_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_script TEXT,
    output_path TEXT,
    youtube_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((source_path IS NOT NULL) OR (source_url IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_video_queue_claim
    ON video_queue (status, created_at)
    WHERE status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS idx_video_queue_youtube_id
    ON video_queue (youtube_id)
    WHERE youtube_id IS NOT NULL;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_video_queue_updated_at ON video_queue;
CREATE TRIGGER trg_video_queue_updated_at
BEFORE UPDATE ON video_queue
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
