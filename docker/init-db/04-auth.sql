-- ============================================================================
-- DISTRICT RESOURCE PROFILING (DKI JAKARTA)
-- Authentication & Authorization Schema (TODO-4)
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_email_lower ON app_users (LOWER(email));

-- Chat audit log (question length and tools used only; no question/prompt text stored for privacy)
CREATE TABLE IF NOT EXISTS chat_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES app_users(id) ON DELETE SET NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    question_length INT NOT NULL,
    tools_used TEXT[] DEFAULT '{}',
    guardrail_status VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_chat_audit_user_id ON chat_audit (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_audit_timestamp ON chat_audit (timestamp DESC);
