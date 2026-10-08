-- Multi-change release migration (mixed risk)
ALTER TABLE products ADD COLUMN description text NULL;
ALTER TABLE products ALTER COLUMN sku TYPE varchar(64);
CREATE INDEX idx_orders_user_id ON orders (user_id);
ALTER TABLE users DROP COLUMN email;
