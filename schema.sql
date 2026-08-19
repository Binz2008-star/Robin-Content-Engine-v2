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

CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    custom_url TEXT,
    description TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ,
    uploads_playlist_id TEXT NOT NULL,
    view_count BIGINT,
    subscriber_count BIGINT,
    hidden_subscriber_count BOOLEAN NOT NULL DEFAULT FALSE,
    video_count BIGINT,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES youtube_channels(channel_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMPTZ,
    duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    privacy_status TEXT,
    made_for_kids BOOLEAN,
    self_declared_made_for_kids BOOLEAN,
    category_id TEXT,
    license TEXT,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    thumbnail_url TEXT,
    view_count BIGINT,
    like_count BIGINT,
    comment_count BIGINT,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel_published
    ON youtube_videos (channel_id, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_youtube_videos_current
    ON youtube_videos (channel_id, is_current)
    WHERE is_current = TRUE;

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

DROP TRIGGER IF EXISTS trg_youtube_channels_updated_at ON youtube_channels;
CREATE TRIGGER trg_youtube_channels_updated_at
BEFORE UPDATE ON youtube_channels
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_youtube_videos_updated_at ON youtube_videos;
CREATE TRIGGER trg_youtube_videos_updated_at
BEFORE UPDATE ON youtube_videos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
