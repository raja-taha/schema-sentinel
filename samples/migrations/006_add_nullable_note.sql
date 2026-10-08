-- Safe-ish: additive nullable column (expand phase)
ALTER TABLE accounts
  ADD COLUMN note text NULL;
