-- Store uploads that failed "receipt-like" validation for debugging and improving the filter.
-- Used when OCR result has no total or no store/address-like content in top 1/3.

create table if not exists non_receipt_rejects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete set null,
  file_hash text,
  image_path text,
  reason text not null,
  ocr_text_snippet text,
  created_at timestamptz default now()
);

create index non_receipt_rejects_user_id_idx on non_receipt_rejects(user_id);
create index non_receipt_rejects_created_at_idx on non_receipt_rejects(created_at);

comment on table non_receipt_rejects is 'Uploads rejected by receipt-like validation (no total or no store/address in top 1/3) for debug and filter tuning';
