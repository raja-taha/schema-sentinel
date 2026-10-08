-- Risky: narrowing type can reject / truncate existing values
ALTER TABLE products
  ALTER COLUMN sku TYPE integer USING sku::integer;
