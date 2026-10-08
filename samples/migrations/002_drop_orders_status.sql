-- Risky: dropping a column still referenced by API / jobs
ALTER TABLE orders
  DROP COLUMN status;
