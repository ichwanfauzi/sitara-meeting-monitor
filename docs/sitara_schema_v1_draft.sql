-- SITARA Database Schema v1.0
-- PostgreSQL 15+
-- Initial schema for meetings, minutes, decisions, action items, assignments,
-- progress updates, approvals, documents, notifications, and audit logs.
-- Review organization-specific policies before production deployment.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================================================
-- 1. ORGANIZATION, USERS, RBAC
-- =========================================================

CREATE TABLE units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_unit_id UUID REFERENCES units(id) ON DELETE RESTRICT,
    unit_code VARCHAR(50) UNIQUE,
    unit_name VARCHAR(200) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (parent_unit_id IS NULL OR parent_unit_id <> id)
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_number VARCHAR(100) UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(320) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_code VARCHAR(50) NOT NULL UNIQUE,
    role_name VARCHAR(100) NOT NULL,
    description TEXT,
    is_system_role BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    permission_code VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE user_units (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_until DATE,
    PRIMARY KEY (user_id, unit_id, valid_from),
    CHECK (valid_until IS NULL OR valid_until >= valid_from)
);

CREATE UNIQUE INDEX uq_user_primary_unit_active
    ON user_units(user_id) WHERE is_primary = TRUE AND valid_until IS NULL;

CREATE TABLE reporting_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    supervisor_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    subordinate_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    unit_id UUID REFERENCES units(id) ON DELETE RESTRICT,
    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_until DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (supervisor_user_id <> subordinate_user_id),
    CHECK (valid_until IS NULL OR valid_until >= valid_from),
    UNIQUE (supervisor_user_id, subordinate_user_id, valid_from)
);

-- Seed role names; user accounts are created separately.
INSERT INTO roles (role_code, role_name, description, is_system_role) VALUES
('SUPER_ADMIN', 'Super Admin', 'Administrasi teknis sistem dan pengelolaan akun istimewa.', TRUE),
('SEKRETARIAT', 'Sekretariat', 'Operasional notulensi, verifikasi, status resmi, distribusi, dan arsip.', TRUE),
('REKTOR', 'Rektor', 'Akses pimpinan sesuai kewenangan.', TRUE),
('WAREK', 'Wakil Rektor', 'Akses pimpinan sesuai bidang dan kewenangan.', TRUE),
('PIC', 'PIC', 'Melihat dan memperbarui tugas yang ditugaskan.', TRUE)
ON CONFLICT (role_code) DO NOTHING;

-- =========================================================
-- 2. MEETINGS, PARTICIPANTS, AGENDAS, DISCUSSIONS, DECISIONS
-- =========================================================

CREATE TABLE meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_number VARCHAR(150) NOT NULL UNIQUE,
    title VARCHAR(300) NOT NULL,
    meeting_type VARCHAR(100) NOT NULL DEFAULT 'RAPIM',
    meeting_date DATE NOT NULL,
    start_time TIME,
    end_time TIME,
    location VARCHAR(300),
    chairperson_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    notetaker_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    started_at TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ,
    finalized_by UUID REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('DRAFT', 'LIVE', 'FINAL', 'ARCHIVED')),
    CHECK (end_time IS NULL OR start_time IS NULL OR end_time >= start_time),
    CHECK (
        (status <> 'FINAL' AND status <> 'ARCHIVED')
        OR (finalized_at IS NOT NULL AND finalized_by IS NOT NULL)
    )
);

CREATE TABLE meeting_participants (
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    attendance_status VARCHAR(20) NOT NULL DEFAULT 'INVITED',
    participant_title VARCHAR(200),
    PRIMARY KEY (meeting_id, user_id),
    CHECK (attendance_status IN ('INVITED', 'PRESENT', 'ABSENT', 'EXCUSED'))
);

CREATE TABLE agendas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    agenda_number INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL,
    agenda_description TEXT,
    lead_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    supporting_unit_id UUID REFERENCES units(id) ON DELETE RESTRICT,
    duration_minutes INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (meeting_id, agenda_number),
    CHECK (agenda_number > 0),
    CHECK (duration_minutes IS NULL OR duration_minutes >= 0)
);

CREATE TABLE discussions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agenda_id UUID NOT NULL REFERENCES agendas(id) ON DELETE CASCADE,
    discussion_number INTEGER NOT NULL,
    subject VARCHAR(500),
    content TEXT NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agenda_id, discussion_number),
    CHECK (discussion_number > 0)
);

CREATE TABLE decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discussion_id UUID NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    decision_number INTEGER NOT NULL,
    decision_text TEXT NOT NULL,
    output_expected TEXT,
    target_date DATE,
    is_action_item BOOLEAN NOT NULL DEFAULT FALSE,
    proposed_pic_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discussion_id, decision_number),
    CHECK (decision_number > 0)
);

-- A decision can generate at most one parent action item in this v1 model.
-- That action item may then have multiple assignments (main/supporting PICs).
CREATE TABLE action_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id UUID NOT NULL UNIQUE REFERENCES decisions(id) ON DELETE RESTRICT,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    expected_output TEXT,
    priority VARCHAR(20) NOT NULL DEFAULT 'NORMAL',
    target_date DATE,
    official_status VARCHAR(30) NOT NULL DEFAULT 'BELUM_DIMULAI',
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CHECK (priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    CHECK (official_status IN (
        'BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI'
    )),
    CHECK ((official_status = 'SELESAI') = (completed_at IS NOT NULL))
);

-- =========================================================
-- 3. ASSIGNMENTS, PROGRESS, STATUS HISTORY, APPROVALS
-- =========================================================

CREATE TABLE assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_item_id UUID NOT NULL REFERENCES action_items(id) ON DELETE RESTRICT,
    assignee_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_by_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assignment_role VARCHAR(20) NOT NULL,
    parent_assignment_id UUID REFERENCES assignments(id) ON DELETE RESTRICT,
    assignment_note TEXT,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (assignment_role IN ('MAIN', 'SUPPORTING')),
    CHECK (parent_assignment_id IS NULL OR parent_assignment_id <> id)
);

CREATE UNIQUE INDEX uq_action_item_active_main_assignee
    ON assignments(action_item_id)
    WHERE assignment_role = 'MAIN' AND is_active = TRUE;

CREATE UNIQUE INDEX uq_action_item_active_assignee_role
    ON assignments(action_item_id, assignee_user_id, assignment_role)
    WHERE is_active = TRUE;

CREATE TABLE progress_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_item_id UUID NOT NULL REFERENCES action_items(id) ON DELETE RESTRICT,
    assignment_id UUID REFERENCES assignments(id) ON DELETE SET NULL,
    submitted_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    progress_percent SMALLINT,
    update_text TEXT NOT NULL,
    obstacle_description TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_by UUID REFERENCES users(id) ON DELETE RESTRICT,
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    CHECK (progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100),
    CHECK ((reviewed_by IS NULL AND reviewed_at IS NULL)
        OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE TABLE status_histories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_item_id UUID NOT NULL REFERENCES action_items(id) ON DELETE RESTRICT,
    old_status VARCHAR(30),
    new_status VARCHAR(30) NOT NULL,
    changed_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    change_note TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (old_status IS NULL OR old_status IN (
        'BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI'
    )),
    CHECK (new_status IN (
        'BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI'
    )),
    CHECK (old_status IS DISTINCT FROM new_status)
);

CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_item_id UUID NOT NULL REFERENCES action_items(id) ON DELETE RESTRICT,
    progress_update_id UUID REFERENCES progress_updates(id) ON DELETE RESTRICT,
    submitted_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    reviewer_user_id UUID REFERENCES users(id) ON DELETE RESTRICT,
    approval_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    submission_note TEXT,
    review_note TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    CHECK (approval_status IN ('PENDING', 'APPROVED', 'REVISION_REQUIRED')),
    CHECK (
        (approval_status = 'PENDING' AND reviewed_at IS NULL)
        OR (approval_status <> 'PENDING' AND reviewed_at IS NOT NULL)
    )
);

-- =========================================================
-- 4. DOCUMENTS, VERSIONS, TEMPLATES, REPOSITORY METADATA
-- =========================================================

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID REFERENCES meetings(id) ON DELETE RESTRICT,
    action_item_id UUID REFERENCES action_items(id) ON DELETE RESTRICT,
    progress_update_id UUID REFERENCES progress_updates(id) ON DELETE RESTRICT,
    uploaded_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    document_type VARCHAR(30) NOT NULL,
    title VARCHAR(500) NOT NULL,
    original_filename VARCHAR(500) NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    mime_type VARCHAR(150) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    checksum_sha256 CHAR(64),
    is_final BOOLEAN NOT NULL DEFAULT FALSE,
    access_classification VARCHAR(20) NOT NULL DEFAULT 'RESTRICTED',
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (document_type IN (
        'AGENDA', 'MEETING_MATERIAL', 'MINUTES_DRAFT', 'MINUTES_FINAL',
        'DECISION_BRIEF_DRAFT', 'DECISION_BRIEF_FINAL', 'TASK_EVIDENCE',
        'FOLLOW_UP', 'OTHER'
    )),
    CHECK (file_size_bytes > 0),
    CHECK (access_classification IN ('RESTRICTED', 'INTERNAL', 'TASK_ASSIGNEES')),
    CHECK (
        num_nonnulls(meeting_id, action_item_id, progress_update_id) >= 1
    )
);

CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    version_number INTEGER NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    checksum_sha256 CHAR(64),
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    change_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number),
    CHECK (version_number > 0)
);

CREATE TABLE document_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_code VARCHAR(100) NOT NULL UNIQUE,
    template_name VARCHAR(200) NOT NULL,
    document_type VARCHAR(30) NOT NULL,
    template_version VARCHAR(50) NOT NULL,
    storage_key TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================
-- 5. DECISION BRIEF, NOTIFICATIONS, NOTES, AUDIT
-- =========================================================

CREATE TABLE decision_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE RESTRICT,
    version_number INTEGER NOT NULL DEFAULT 1,
    brief_status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    content_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    generated_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    reviewed_by UUID REFERENCES users(id) ON DELETE RESTRICT,
    reviewed_at TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ,
    document_id UUID REFERENCES documents(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (meeting_id, version_number),
    CHECK (version_number > 0),
    CHECK (brief_status IN ('DRAFT', 'IN_REVIEW', 'FINAL', 'ARCHIVED')),
    CHECK (
        (brief_status <> 'FINAL')
        OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND finalized_at IS NOT NULL)
    )
);

CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    notification_type VARCHAR(50) NOT NULL,
    title VARCHAR(300) NOT NULL,
    message TEXT NOT NULL,
    meeting_id UUID REFERENCES meetings(id) ON DELETE CASCADE,
    action_item_id UUID REFERENCES action_items(id) ON DELETE CASCADE,
    progress_update_id UUID REFERENCES progress_updates(id) ON DELETE CASCADE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE task_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_item_id UUID NOT NULL REFERENCES action_items(id) ON DELETE CASCADE,
    author_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    note_text TEXT NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'ASSIGNEES_AND_SUPERVISORS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (visibility IN ('SECRETARIAT_ONLY', 'ASSIGNEES_AND_SUPERVISORS', 'AUTHORIZED_USERS'))
);

CREATE TABLE audit_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action_code VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID,
    meeting_id UUID REFERENCES meetings(id) ON DELETE SET NULL,
    action_item_id UUID REFERENCES action_items(id) ON DELETE SET NULL,
    before_data JSONB,
    after_data JSONB,
    source_ip INET,
    user_agent TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================
-- 6. INDEXES
-- =========================================================

CREATE INDEX idx_meetings_date ON meetings(meeting_date DESC);
CREATE INDEX idx_meetings_status ON meetings(status);
CREATE INDEX idx_agendas_meeting_sort ON agendas(meeting_id, sort_order);
CREATE INDEX idx_discussions_agenda ON discussions(agenda_id);
CREATE INDEX idx_decisions_discussion ON decisions(discussion_id);
CREATE INDEX idx_action_items_status_target ON action_items(official_status, target_date);
CREATE INDEX idx_assignments_assignee_active ON assignments(assignee_user_id, is_active);
CREATE INDEX idx_progress_updates_task_time ON progress_updates(action_item_id, submitted_at DESC);
CREATE INDEX idx_approvals_status_time ON approvals(approval_status, submitted_at DESC);
CREATE INDEX idx_documents_meeting ON documents(meeting_id);
CREATE INDEX idx_documents_action_item ON documents(action_item_id);
CREATE INDEX idx_notifications_recipient_unread ON notifications(recipient_user_id, created_at DESC)
    WHERE read_at IS NULL;
CREATE INDEX idx_audit_logs_meeting_time ON audit_logs(meeting_id, occurred_at DESC);
CREATE INDEX idx_audit_logs_task_time ON audit_logs(action_item_id, occurred_at DESC);

COMMIT;

-- =========================================================
-- IMPORTANT IMPLEMENTATION NOTES
-- =========================================================
-- 1. Enforce "only Secretariat changes official task status" in backend
--    authorization and in a database trigger/RLS policy before production.
-- 2. Enforce that a FINAL meeting has an authorized finalizer and that
--    active Secretariat/Rektor/Warek users can edit during LIVE; notetaker
--    identity is attribution, not an exclusive edit gate.
-- 3. Enforce that Secretariat/Rektor/Warek can read complete minutes and
--    Decision Briefs across Rapim; PIC sees only assigned task data.
-- 4. Validate that an ACTION_ITEM decision has a corresponding action_items
--    row, and a non-action-item decision does not have one, using a
--    transactional service or deferred constraint trigger.
-- 5. Store files outside the public web root/object storage with private
--    access. Never store raw file bytes or expose storage_key directly.
-- 6. Create application-specific permission seeds and database roles before
--    production. Do not use a database superuser for the web application.
-- 7. Add a trigger to append status_histories and audit_logs atomically when
--    official_status changes. Restrict direct updates to action_items.
-- 8. For live minutes, allow all three core roles to append revisions using
--    base_revision_id concurrency checks. Keep notetaker identity for attribution.
