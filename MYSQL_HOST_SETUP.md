# MySQL Host Setup and Migration Guide

This guide is the step-by-step runbook for standing up the new self-managed
MySQL host for `cshc-web` and migrating existing data onto it.

## Default Approach

Use this sequence:

1. Discover the exact current production MySQL major version.
2. Build the new host on the **same MySQL major version first**.
3. Import current data onto the new host.
4. Fix storage engine, charset, and collation issues on the new host.
5. Validate the current app against the cleaned database.
6. Only then plan any later jump to MySQL 8.

This separates `data migration` risk from `server-version upgrade` risk.

## Assumptions

- Production remains on MySQL.
- The new DB host is a separate EC2 instance in AWS.
- The web tier will connect over private networking only.
- Existing backups are logical dumps.
- Existing infrastructure automation lives in `cshc-web-automation` and should be reused selectively: CloudFormation for infrastructure and Ansible for direct MySQL host configuration.
- The current codebase still contains a migration-time `MyISAM` workaround, so
  old schema assumptions may still exist in historical data.
- The app should eventually land on `InnoDB` + `utf8mb4`.

## Step 0: Discover the Current Production Baseline

Run these on the current production DB before provisioning the new host:

```sql
SELECT VERSION();

SHOW VARIABLES LIKE 'character_set_server';
SHOW VARIABLES LIKE 'collation_server';

SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'cshc'
ORDER BY TABLE_NAME;

SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'cshc'
  AND COLLATION_NAME IS NOT NULL
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

Record:

- MySQL version
- server charset/collation
- any `MyISAM` tables
- any tables or columns not already on `utf8mb4`

If possible, also capture row counts for later comparison:

```sql
SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'cshc'
ORDER BY TABLE_NAME;
```

## Step 1: Provision the New Host

Default recommendation: use a small Ubuntu LTS EC2 instance for the DB host,
because the official MySQL packages make same-major-version installs and later
upgrades easier. This does not change the decision to use EB/Amazon Linux for
the web tier.

Automation recommendation:

- use **CloudFormation** to create the DB host infrastructure
- use **Ansible** to configure the host after it exists
- do not create the DB host manually if the goal is repeatable recovery and
  rebuild

Create:

- 1 EC2 instance in the same VPC/private network as the EB environment
- 1 dedicated security group for MySQL
- 1 EBS volume sized for:
  - current DB size
  - growth headroom
  - temporary migration working space
  - local backup/export headroom if needed

Security group rules:

- inbound `3306` only from the EB/web security group and approved admin IPs/VPN
- no public MySQL access from the internet
- normal outbound access allowed for package install and patching

Choose instance size conservatively. Prefer extra RAM over extra CPU for MySQL.

CloudFormation responsibilities at this step:

- EC2 instance
- security group
- EBS volume and attachment
- IAM instance profile if backup/export tooling needs AWS access
- DNS record if you want a stable internal hostname

Capture all of these in the infrastructure stack rather than in ad hoc console
steps where possible.

## Step 1.1: Map Existing Automation Before Reuse

Before writing new automation, classify the existing `cshc-web-automation`
content:

- keep CloudFormation patterns for VPC, EC2, EBS, security groups, and DNS
- keep Ansible patterns for generic host bootstrap and MySQL host management
- retire Ansible assumptions tied to the old webapp stack, especially:
  - `apache2`
  - `mod_wsgi`
  - `certbot` on the web host
  - `memcached` on the web host
  - local MySQL on the web host
  - host-managed virtualenv and Node installs for the website runtime

The new DB host guide assumes the automation is split this way.

## Step 2: Install the Same MySQL Major Version

Install the **same major version as the current production database**.

Do not jump to MySQL 8 in this guide unless the current production DB is
already on MySQL 8.

Preferred implementation:

- encode base package install and MySQL configuration in Ansible
- keep version selection explicit in inventory or host vars
- keep configuration templates for `mysqld.cnf` under source control

After installation:

- enable the MySQL service
- set a strong root/admin password or socket-only admin auth
- configure the server to bind to the private interface
- confirm the data directory is on the intended volume

Set target defaults in `mysqld.cnf` or equivalent:

- `character-set-server = utf8mb4`
- `collation-server = utf8mb4_unicode_ci`
- `default_storage_engine = InnoDB`
- `innodb_file_per_table = 1`
- `skip_name_resolve = 1`

Then restart MySQL and verify:

```sql
SHOW VARIABLES LIKE 'character_set_server';
SHOW VARIABLES LIKE 'collation_server';
SHOW VARIABLES LIKE 'default_storage_engine';
```

Important:

- New server defaults do **not** automatically fix imported legacy tables.
- They only ensure newly created objects use sane defaults.

Ansible should own:

- package installation
- service enable/restart
- templated MySQL config
- CLI helper config for the admin user if you choose to manage it that way

## Step 3: Create Database and App User

Create a dedicated DB and least-privilege app user.

Example:

```sql
CREATE DATABASE cshc
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'cshc'@'10.%' IDENTIFIED BY 'replace-me';
GRANT ALL PRIVILEGES ON cshc.* TO 'cshc'@'10.%';
FLUSH PRIVILEGES;
```

Adjust the host pattern to match your VPC or use a more specific private IP
range.

## Step 4: Take or Prepare the Import Dump

Preferred input: take a fresh logical dump from the current production source
before cutover work starts.

If you can still produce a fresh dump, prefer:

```bash
mysqldump \
  --single-transaction \
  --skip-lock-tables \
  --default-character-set=utf8 \
  --routines \
  --triggers \
  --events \
  cshc > cshc-migration.sql
```

Why `utf8` here:

- the repo’s existing dump workflow already assumes `utf8`
- matching the current source behavior reduces import surprises during the
  first migration pass

If you only have older dumps:

- use the newest known-good dump available
- record its origin and date
- expect to do more validation after import

## Step 5: Import the Dump to the New Host

Import into the new `cshc` database:

```bash
mysql \
  --default-character-set=utf8 \
  -h <new-db-host> \
  -u <admin-user> \
  -p cshc < cshc-migration.sql
```

After import:

- run basic table checks
- compare row counts against the source if available
- confirm the app can authenticate with the new DB user

## Step 6: Audit Storage Engines, Charset, and Collation

Run these on the new host after import:

```sql
SELECT TABLE_NAME, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'cshc'
ORDER BY TABLE_NAME;

SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'cshc'
  AND COLLATION_NAME IS NOT NULL
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

Pay attention to:

- tables still on `MyISAM`
- tables not using `utf8mb4`
- columns with mixed collations inside the same table
- known error patterns such as `Illegal mix of collations`

## Step 7: Convert Storage Engine to InnoDB

Convert any remaining `MyISAM` tables first:

```sql
ALTER TABLE <table_name> ENGINE=InnoDB;
```

Do this table by table, starting with lower-risk content tables first.

After each batch:

- rerun the engine audit query
- spot-check row counts
- confirm no conversion error occurred

## Step 8: Normalize Database and Tables to utf8mb4

First set the database defaults:

```sql
ALTER DATABASE cshc
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

Then convert tables one by one:

```sql
ALTER TABLE <table_name>
  CONVERT TO CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

Recommended order:

1. small lookup/config tables
2. content tables
3. large/high-risk tables
4. blog/comment related tables

Do not bulk-run every table blindly on the first attempt. Work in batches so
you can isolate failures.

## Step 9: Handle Collation Errors During Conversion

If you hit collation or index-length errors:

1. Stop the batch.
2. Record the exact failing table and error.
3. Inspect the offending table and columns:

```sql
SHOW CREATE TABLE <table_name>;

SELECT COLUMN_NAME, COLUMN_TYPE, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'cshc'
  AND TABLE_NAME = '<table_name>';
```

Common fixes:

- convert the table after moving it to `InnoDB`
- shorten oversized indexed `VARCHAR` columns if the old version cannot support
  the wider `utf8mb4` index length
- convert specific text columns manually before rerunning full table conversion

Example manual column conversion:

```sql
ALTER TABLE <table_name>
  MODIFY <column_name> VARCHAR(191)
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

Use `191` only where older index-length limits force it. Do not shorten columns
unnecessarily.

Important version note:

- If the current production DB is older than MySQL 5.7.7, full `utf8mb4`
  conversion may hit index-length limits more often.
- In that case, finish the migration with the cleanest compatible charset state
  you can achieve, document the blocking tables, and treat full normalization as
  part of the later MySQL/Django upgrade work.

## Step 10: Find Remaining Non-utf8mb4 Columns

After the conversion work, rerun:

```sql
SELECT TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'cshc'
  AND COLLATION_NAME IS NOT NULL
  AND (
    CHARACTER_SET_NAME <> 'utf8mb4'
    OR COLLATION_NAME NOT LIKE 'utf8mb4%'
  )
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

The goal is either:

- zero rows returned, or
- a short explicit exception list with documented reasons

## Step 11: Validate with the App

Point the app at the new DB host using the modernized env vars:

- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`

Run at minimum:

```bash
python src/manage.py check
python src/manage.py migrate --plan
python src/manage.py showmigrations
```

Then manually validate:

- homepage loads
- admin login works
- representative content pages render
- one GraphQL request works
- scheduled task commands start without DB errors

Do not drop the old DB or declare cutover readiness until this step passes.

## Step 12: Configure Backup and Recovery on the New Host

Keep the existing logical S3-backed backup model, but validate it against the
new host before cutover.

You need:

- a tested logical backup job
- a tested restore onto another host or disposable instance
- documented DB admin credentials and access path
- documented storage location for dumps

Minimum recovery exercise:

1. take a fresh logical backup from the new host
2. restore it onto a disposable MySQL instance
3. confirm the restored DB opens and key tables exist

Automation expectation:

- CloudFormation should make it easy to create a disposable recovery host
- Ansible should make it easy to configure that host identically enough to
  prove the restore process

## Step 13: Cutover Preparation

Before cutover:

- take a fresh final source backup
- freeze or control writes if required
- take a final import delta if your process requires it
- verify app credentials point at the new host
- verify security group rules from the web tier
- verify rollback path to the old DB still works

## Step 14: Cutover and Immediate Checks

After switching the app to the new DB host:

- run `manage.py check`
- load the site
- log into admin
- exercise one write path
- monitor MySQL error log and application logs

If there are collation errors after cutover:

- capture the exact SQL/table/column involved
- compare that object’s collation against the normalization audit queries
- roll back if the issue is broad rather than isolated

## Rollback Plan

Minimum rollback position:

- old source DB remains intact until the new host is proven
- pre-cutover dump is verified
- app config can be pointed back to the old DB quickly
- new-host migration steps are logged so partial changes are understood

If the new host fails validation after cutover:

1. point the app back to the old DB
2. confirm reads and writes work
3. preserve logs and failing SQL from the new host
4. resume cleanup on the new host offline

## Definition of Done

This guide is complete when all of the following are true:

- the new MySQL host exists and is private-network reachable from the web tier
- the host can be rebuilt repeatably from CloudFormation plus Ansible rather
  than undocumented manual steps
- the current data is imported successfully
- table engines are moved to `InnoDB` where feasible
- charset/collation is normalized to `utf8mb4` where feasible
- any exceptions are explicitly documented
- backups and restore are validated
- the app can connect and run basic checks against the new host
