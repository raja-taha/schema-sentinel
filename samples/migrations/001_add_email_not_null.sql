-- Risky: NOT NULL column without DEFAULT on a large users table
ALTER TABLE users
  ADD COLUMN email varchar(255) NOT NULL;
