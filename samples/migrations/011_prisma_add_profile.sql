-- Prisma migrate SQL: additive + risky constraint in one shot
ALTER TABLE "users" ADD COLUMN "profile_id" INTEGER;
ALTER TABLE "users" ALTER COLUMN "profile_id" SET NOT NULL;
CREATE INDEX "users_profile_id_idx" ON "users"("profile_id");
