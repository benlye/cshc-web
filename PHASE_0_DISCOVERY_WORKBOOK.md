# Phase 0 Discovery Workbook

This workbook is the step-by-step capture document for Phase 0 of the modernization plan.

Use it offline, fill in the sections below, and return the completed document as input for implementation planning and execution.

Do not paste live secrets into this file. Record:

- variable names
- where the value currently lives
- who can access or rotate it
- whether the value is already known or still needs retrieval

## Completion Standard

Phase 0 is complete when this workbook contains:

- the current runtime env var and secrets inventory
- the current AWS resource and host-responsibility inventory
- the current TLS and DNS ownership path
- the current scheduled job inventory
- the current database baseline, including version, engine, charset, collation, size, and persistence details
- the current backup and restore process, plus at least one restore rehearsal result
- the CloudFormation and Ansible retain/rewrite/retire classification
- locked inputs for Phase 1

## How To Use This Workbook

1. Work through the steps in order.
2. If you cannot answer a field, write `UNKNOWN`.
3. If a field is not applicable, write `N/A`.
4. For any answer taken from a command, paste both:
   - the command used
   - the relevant output or a short summary
5. For any decision or assumption, record:
   - why it was chosen
   - who confirmed it
   - when it was confirmed

## Step 1: Environment and Secrets Inventory

Goal: capture every runtime setting the app needs without exposing secret values.

### 1.1 Runtime Variables

Fill this table with every app setting required in production or staging.

| Variable | Purpose | Secret? | Current source | Current owner | Required in prod | Required in staging | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` |  |  |  |  |  |  |  |
| `SECRET_KEY` |  |  |  |  |  |  |  |
| `DB_HOST` |  |  |  |  |  |  |  |
| `DB_PORT` |  |  |  |  |  |  |  |
| `DB_NAME` |  |  |  |  |  |  |  |
| `DB_USER` |  |  |  |  |  |  |  |
| `DB_PASSWORD` |  |  |  |  |  |  |  |
| `ALLOWED_HOSTS` |  |  |  |  |  |  |  |
| `AWS_STORAGE_BUCKET_NAME` |  |  |  |  |  |  |  |
| `EMAIL_*` |  |  |  |  |  |  |  |
| `SENTRY_*` |  |  |  |  |  |  |  |
| `GOOGLE_*` |  |  |  |  |  |  |  |
| `STRIPE_*` |  |  |  |  |  |  |  |

Add rows for anything else used in production.

### 1.2 Secrets Storage and Rotation

| Secret or secret family | Current storage location | Rotation method | Last rotated | Recovery owner | Notes |
| --- | --- | --- | --- | --- | --- |
| Django secret key |  |  |  |  |  |
| Database password |  |  |  |  |  |
| AWS credentials if any are app-managed |  |  |  |  |  |
| Third-party API credentials |  |  |  |  |  |

### 1.3 Open Questions

- Missing variables:
- Variables with unclear ownership:
- Variables that should move to AWS-managed secret storage:

## Step 2: AWS Resource and Host Responsibility Inventory

Goal: capture the current deployed shape and the operational responsibilities attached to it.

### 2.1 Environments

| Environment | Current platform | App host shape | DB host shape | Public URL | Notes |
| --- | --- | --- | --- | --- | --- |
| Production |  |  |  |  |  |
| Staging |  |  |  |  |  |
| Any other non-prod |  |  |  |  |  |

### 2.2 Core AWS Resources

| Resource type | Name or ID | Purpose | Environment | Managed by | Notes |
| --- | --- | --- | --- | --- | --- |
| Elastic Beanstalk application |  |  |  |  |  |
| Elastic Beanstalk environment |  |  |  |  |  |
| EC2 instance(s) |  |  |  |  |  |
| S3 bucket: static |  |  |  |  |  |
| S3 bucket: media |  |  |  |  |  |
| S3 bucket: backups |  |  |  |  |  |
| Route53 hosted zone or other DNS |  |  |  |  |  |
| Security groups |  |  |  |  |  |
| IAM roles / instance profiles |  |  |  |  |  |
| CloudWatch logs / alarms |  |  |  |  |  |
| EventBridge rules / Scheduler |  |  |  |  |  |
| Any cache service |  |  |  |  |  |

### 2.3 Current Host Responsibilities

List what the current web host is doing today.

| Responsibility | Where it runs now | How it is managed now | Keep / move / retire | Notes |
| --- | --- | --- | --- | --- |
| Django app runtime |  |  |  |  |
| Reverse proxy / TLS |  |  |  |  |
| Static collection |  |  |  |  |
| Scheduled jobs |  |  |  |  |
| MySQL |  |  |  |  |
| Backups |  |  |  |  |
| Cert renewal |  |  |  |  |
| Node / asset build |  |  |  |  |
| Memcached or other cache |  |  |  |  |

### 2.4 Findings

- Resources not represented in code:
- Resources with unclear ownership:
- Resources likely to survive modernization:
- Resources likely to be retired:

## Step 3: TLS, DNS, and Public Edge Path

Goal: document how traffic reaches the app today.

### 3.1 DNS and Certificates

| Item | Current value | Managed by | Renewal / update path | Notes |
| --- | --- | --- | --- | --- |
| Primary domain |  |  |  |  |
| `www` alias |  |  |  |  |
| DNS provider |  |  |  |  |
| TLS terminator |  |  |  |  |
| Certificate issuer |  |  |  |  |
| Certificate storage location |  |  |  |  |
| Redirect behavior (`http` -> `https`, apex -> `www`, etc.) |  |  |  |  |

### 3.2 Request Path Summary

Describe the current request path in one short paragraph.

`TODO`

### 3.3 Findings

- Any committed certificate or private key material:
- Any undocumented DNS dependencies:
- Any edge behavior that must be preserved:

## Step 4: Scheduled Jobs and Operational Commands

Goal: capture what runs on a schedule today and what commands operations depend on.

### 4.1 Scheduled Jobs

| Job name | Current trigger | Command | Frequency | Environment | Failure signal | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `nightly_tasks` |  |  |  |  |  |  |
| backup job |  |  |  |  |  |  |

Add rows for all current scheduled work.

### 4.2 Operational Commands

| Command | Purpose | Where it is run | Who runs it | When | Notes |
| --- | --- | --- | --- | --- | --- |
| `manage.py migrate` |  |  |  |  |  |
| `manage.py collectstatic` |  |  |  |  |  |
| `manage.py compress` |  |  |  |  |  |
| `manage.py nightly_tasks` |  |  |  |  |  |
| backup command |  |  |  |  |  |

### 4.3 Findings

- Jobs that must move to EventBridge Scheduler later:
- Jobs that may remain instance-local temporarily:
- Commands that assume host-specific paths:

## Step 5: Database Baseline

Goal: capture the current production MySQL baseline before any new host is built.

Run the following on the current production database and paste the results or summarized findings below.

### 5.1 Required SQL

```sql
SELECT VERSION();

SHOW VARIABLES LIKE 'character_set_server';
SHOW VARIABLES LIKE 'collation_server';
SHOW VARIABLES LIKE 'default_storage_engine';

SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE, TABLE_COLLATION
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'cshc'
ORDER BY TABLE_NAME;

SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'cshc'
  AND COLLATION_NAME IS NOT NULL
ORDER BY TABLE_NAME, ORDINAL_POSITION;

SELECT TABLE_NAME, TABLE_ROWS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'cshc'
ORDER BY TABLE_NAME;
```

### 5.2 Baseline Capture

| Item | Result | Evidence / command | Notes |
| --- | --- | --- | --- |
| MySQL version |  |  |  |
| Server charset |  |  |  |
| Server collation |  |  |  |
| Default storage engine |  |  |  |
| Any `MyISAM` tables? |  |  |  |
| Any non-`utf8mb4` tables? |  |  |  |
| Any mixed-collation columns? |  |  |  |
| Approximate database size |  |  |  |
| Largest tables |  |  |  |

### 5.3 Persistence and Capacity

| Item | Result | Evidence / command | Notes |
| --- | --- | --- | --- |
| Current DB host |  |  |  |
| Current data path |  |  |  |
| Current disk size |  |  |  |
| Free disk headroom |  |  |  |
| Restart behavior / service manager |  |  |  |
| Backup storage target |  |  |  |

### 5.4 Known DB Problems

- Current collation errors:
- Known import problems:
- Known migration problems:
- Tables likely to need manual cleanup:

## Step 6: Backup and Restore Validation

Goal: prove that current backups are real and usable.

### 6.1 Current Backup Path

Describe the current backup path end to end.

`TODO`

### 6.2 Backup Details

| Item | Result | Notes |
| --- | --- | --- |
| Backup type |  |  |
| Tool used |  |  |
| Where backups land |  |  |
| Frequency |  |  |
| Retention |  |  |
| Encryption status |  |  |
| Who checks failures |  |  |

### 6.3 Restore Rehearsal

Perform one restore rehearsal onto a disposable MySQL instance or equivalent safe target.

| Item | Result | Notes |
| --- | --- | --- |
| Backup used |  |  |
| Restore target |  |  |
| Restore date |  |  |
| Restore succeeded? |  |  |
| Time taken |  |  |
| Post-restore checks run |  |  |
| Issues found |  |  |
| Manual steps required |  |  |

### 6.4 Evidence

- Commands used:
- Relevant logs:
- Follow-up fixes needed:

## Step 7: Automation Mapping

Goal: decide what survives from `cshc-web-automation` and what should not carry forward.

### 7.1 CloudFormation Inventory

| Stack / template / component | Current responsibility | Retain / rewrite / retire | Notes |
| --- | --- | --- | --- |
|  |  |  |  |

### 7.2 Ansible Inventory

| Role / playbook / task area | Current responsibility | Retain / rewrite / retire | Notes |
| --- | --- | --- | --- |
|  |  |  |  |

### 7.3 Default Classification Rules

Use these defaults unless you have a concrete reason to override them:

- retain CloudFormation for infrastructure definition
- retain Ansible for direct-host configuration, especially the separate MySQL host
- retire Ansible for webapp runtime deployment onto EB hosts
- retire old Apache / mod_wsgi / on-host Certbot / local MySQL web-host assumptions from the web tier

### 7.4 Findings

- Infra pieces clearly reusable:
- Infra pieces requiring rewrite:
- Web-host assumptions that must be removed:

## Step 8: Phase 1 Locked Inputs

Goal: produce the minimum decisions required to start implementation.

### 8.1 Required Inputs

| Decision | Chosen value | Confirmed by | Date | Notes |
| --- | --- | --- | --- | --- |
| Current production MySQL major version |  |  |  |  |
| New DB host starts on same major version | Yes / No |  |  |  |
| New DB host OS |  |  |  |  |
| Initial DB instance size assumption |  |  |  |  |
| Initial DB storage size assumption |  |  |  |  |
| Backup/export ownership |  |  |  |  |
| Registry preference (`ECR`, `GHCR`, `Docker Hub`) |  |  |  |  |
| Cache direction (`locmem`, `memcached`, undecided`) |  |  |  |  |
| Staging DB approach |  |  |  |  |

### 8.2 Remaining Unknowns

List only the unknowns that still block Phase 1.

- `TODO`

## Step 9: Handoff Summary

When returning this workbook, include a short summary here.

### 9.1 Ready Items

- `TODO`

### 9.2 Risks or Gaps

- `TODO`

### 9.3 Questions For Next Pass

- `TODO`

## Final Checklist

Mark each item `DONE`, `PARTIAL`, or `NOT DONE`.

| Item | Status | Notes |
| --- | --- | --- |
| Runtime env vars inventoried |  |  |
| Secrets ownership documented |  |  |
| AWS resources inventoried |  |  |
| Current host responsibilities mapped |  |  |
| TLS and DNS path documented |  |  |
| Scheduled jobs documented |  |  |
| Operational commands documented |  |  |
| Production DB baseline captured |  |  |
| DB persistence and disk details captured |  |  |
| Backup path documented |  |  |
| Restore rehearsal completed |  |  |
| CloudFormation inventory classified |  |  |
| Ansible inventory classified |  |  |
| Phase 1 inputs locked |  |  |
| Blocking unknowns listed clearly |  |  |
