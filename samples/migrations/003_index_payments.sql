-- Risky: blocking index build on a huge payments table
CREATE INDEX idx_payments_created_at ON payments (created_at);
