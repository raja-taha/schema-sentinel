-- Volatile DEFAULT may rewrite every row on large tables
ALTER TABLE orders
  ADD COLUMN last_touched_at timestamptz NOT NULL DEFAULT now();
