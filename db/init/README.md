# Database migrations

The production stack applies versioned Alembic migrations through the one-shot `db-init` service.
Never edit an applied migration. Add a forward-only revision for each controlled release and retain
the migration output as validation evidence.
