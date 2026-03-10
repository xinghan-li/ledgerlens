-- Admin failure classification and user escalation notes.
-- 1. receipt_status.admin_failure_kind: why this receipt is in the admin "failed" list.
-- 2. receipt_escalations: user-submitted escalation with notes (one row per escalate action).

-- Add admin_failure_kind to receipt_status (nullable; only set when current_status in ('failed','needs_review'))
alter table receipt_status
  add column if not exists admin_failure_kind text;

comment on column receipt_status.admin_failure_kind is
  'Reason for admin/developer review: first_round_fail (first-round needs_review), user_escalated (user clicked escalate with notes), vision_fail (not a receipt or vision API error), escalation_fail (escalation ran but still failed). NULL when success.';

-- Allow values; no strict check to avoid migration pain; app enforces.
-- first_round_fail | user_escalated | vision_fail | escalation_fail

-- Table: user escalation (notes) when user clicks "Escalate" on a receipt
create table if not exists receipt_escalations (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null references receipt_status(id) on delete cascade,
  user_id uuid not null references users(id),
  notes text not null default '',
  created_at timestamptz default now()
);

create index receipt_escalations_receipt_id_idx on receipt_escalations(receipt_id);
create index receipt_escalations_created_at_idx on receipt_escalations(created_at desc);

comment on table receipt_escalations is 'User-submitted escalation notes; each row is one "Escalate" action. Admin uses notes to see what went wrong.';
