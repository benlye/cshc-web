# Platform and Dependency Modernization Plan

## Executive Summary

This document is the working runbook for modernizing the Cambridge South Hockey Club website. The current application is a Django web app with a React/Webpack frontend and an AWS Elastic Beanstalk deployment shape that dates back to 2018. The codebase still reflects Python 3.6, Django 2.0, Node/Webpack/Babel 2017-era tooling, several unmaintained Python packages, and deployment assumptions tied to old Elastic Beanstalk Apache and mod_wsgi internals.

The chosen path is to modernize the application on AWS Elastic Beanstalk first, because it is the lower-cost option for the club and avoids taking on unnecessary platform complexity during the dependency upgrade. The modernization must be done in a way that improves application portability so that a later move to ECS Fargate remains straightforward if operational needs change.

The target baseline for the modernized application is:

- Python `3.12`
- Django `4.2 LTS`
- Node `20 LTS`
- npm `10`
- AWS Elastic Beanstalk on Amazon Linux with a modern Python platform and a portable application startup model

## Current State Assessment

### Application

- Django is pinned at `2.0.9` in `requirements/base.txt`.
- The codebase still uses APIs associated with older Django versions, including `django.conf.urls.url`, `ugettext_lazy`, the old `raven` Sentry integration, and legacy cache backend names.
- The app includes GraphQL, traditional Django-rendered pages, Django admin, a blog, CKEditor uploads, and multiple local apps with migrations.
- Production uses MySQL while local development defaults to SQLite.

### Frontend

- The frontend is a multi-entry React app compiled into Django-consumed bundles via `webpack 3`.
- The toolchain is built around `Babel 6`, `React 16`, `react-apollo`, `node-sass`, `react-hot-loader`, and a `package-lock.json` with `lockfileVersion: 1`.
- The frontend is not a separate deployed SPA and should remain integrated with Django during this modernization.

### Hosting and Operations

- The repo is configured for AWS Elastic Beanstalk with `Python 3.6`.
- The deployment is tied to custom Apache and `mod_wsgi` configuration in `.ebextensions`.
- Deployment scripts assume Elastic Beanstalk instance paths such as `/opt/python/run/venv/` and Python 3.6 site-packages paths.
- Nightly jobs are currently driven through instance-local cron.
- Static and media storage are already structured around S3-backed storage.
- Secrets and environment configuration are required at runtime through environment variables.

### Testing and Delivery

- Automated test coverage is minimal; the repo currently contains only a stub `members/tests.py`.
- There is no visible CI configuration in the repository.
- The current upgrade cannot safely be executed as a pure version-bump exercise. It requires code migration, dependency replacement, deployment changes, and a new validation baseline.

## Locked Decisions

### Chosen Platform Strategy

- Production hosting remains on AWS.
- The application will be modernized on Elastic Beanstalk first.
- The production modernization target is a current Elastic Beanstalk Python platform on Amazon Linux.
- A hand-curated Ubuntu AMI or self-managed EC2 host build is not the target end state.
- The legacy Ubuntu CloudFormation and Ansible automation is migration input only, not the basis of the future platform.
- The modernization will avoid deepening dependence on old EB-specific behavior or old Ubuntu host assumptions.
- ECS Fargate remains a future option, not part of the current migration.
- EKS is explicitly out of scope because it is too operationally and financially heavy for this use case.

### Accepted Platform Tradeoffs

- Reusing the existing Ubuntu automation is not a priority because that automation preserves host ownership the modernization is meant to reduce.
- Some Ubuntu-specific operator familiarity will be lost, including `apt`, `apache2`, and other Debian-style package and service conventions.
- The chosen path is somewhat more AWS-aligned operationally, but that tradeoff is acceptable because the goal is to simplify deployment on Elastic Beanstalk rather than preserve a generic hand-built host model.
- The current Ubuntu automation includes `apt`, `apache2`, the `ubuntu` SSH user, Certbot on the instance, local MySQL, cron, and `mod_wsgi`; carrying that model forward would turn the modernization into an OS maintenance project instead of an application modernization.
- The preferred Elastic Beanstalk TLS model is ACM certificates attached to an Application Load Balancer, which is a cleaner fit for managed operations but may add meaningful monthly cost if the current production environment is still single-instance without a load balancer.

### Chosen Upgrade Strategy

- Upgrade toward a supported LTS stack rather than latest-everything.
- Use staged Django LTS hops instead of a single large version jump.
- Replace dependency blockers rather than trying to preserve every legacy library.
- Keep public URLs and core user-facing behavior stable unless an incompatibility makes a targeted change unavoidable.

### Cost and Operational Priorities

- Prefer the lowest-cost viable production platform.
- Keep infrastructure simple enough to be maintainable for a nonprofit sports club.
- Invest effort in app portability and deployment clarity rather than in a larger platform rewrite.

## Target Architecture

The modernized production architecture should be:

- AWS Elastic Beanstalk on a current Amazon Linux Python platform
- Django served by `gunicorn`
- MySQL on Amazon RDS
- Static and media assets stored in S3
- TLS terminated using AWS-managed components rather than committed certificates in the repo
- Secrets stored in AWS-managed configuration or secret storage
- Scheduled jobs invoked through portable operational commands, not instance-specific path assumptions

### Certificate Strategy

- The preferred Elastic Beanstalk certificate model is AWS Certificate Manager with TLS terminated at an Application Load Balancer.
- This is the normal AWS-supported pattern for HTTPS on Elastic Beanstalk and is the default target architecture for the modernization.
- Continuing to use Certbot on the instance is technically possible through custom Elastic Beanstalk configuration, but it is a custom workaround rather than the preferred managed-platform design.
- Instance-local certificate issuance and renewal increase host customization, replacement complexity, and future migration effort, especially for any later move to ECS Fargate or Elastic Beanstalk Docker.
- The current repository strongly suggests direct HTTPS termination on the instance; if production is still single-instance, moving to ACM plus ALB will likely add a real monthly cost and should be treated as a deliberate tradeoff rather than a free improvement.

### Portability Rules

All modernization work should preserve a clean future path to ECS Fargate by enforcing these rules:

- Application configuration comes from environment variables and secret stores only.
- Static and media assets do not depend on local instance storage.
- The app starts with a standard process command such as `gunicorn cshc.wsgi`.
- Migrations, static collection, and scheduled jobs are standalone commands that can be run in any compatible execution environment.
- No production behavior depends on Apache-specific, Ubuntu-specific, or host-path-specific configuration.

### Developer Workflow

- Local development remains containerized and should continue to work well on Windows with Docker Desktop and WSL2.
- Local development should track runtime parity rather than OS parity: Python `3.12`, Node `20`, the same app dependencies, and the same operational commands where practical.
- Local development does not need to run Amazon Linux; Debian-based or Ubuntu-based development containers are acceptable if they reproduce the required application behavior.
- If OS-specific packaging concerns need validation, handle that in CI or a separate parity image rather than making Amazon Linux the default developer environment.
- Choosing Amazon Linux on Elastic Beanstalk now does not materially block a later move to ECS Fargate or Elastic Beanstalk Docker, provided host-specific behavior continues to be removed.

## Phased Migration Plan

### Phase 0: Baseline, Inventory, and Safety Net

Goals:

- capture the current production shape
- reduce rollout risk before version upgrades
- create a staging environment for validation

Work:

- Inventory all required production environment variables.
- Inventory AWS resources in use: Elastic Beanstalk environment, RDS, S3 buckets, DNS, TLS termination, cron-equivalent jobs, and any cache services.
- Confirm production database engine/version and backup/restore process.
- Confirm current static/media bucket layout and retention expectations.
- Document all management commands used operationally, including `nightly_tasks`, `collectstatic`, `compress`, and migrations.
- Create a staging environment on the target EB platform before production cutover.
- Add a minimum smoke test suite that covers:
  - homepage
  - authentication flow
  - admin login
  - GraphQL endpoint
  - one representative React-backed page
  - one scheduled management command entrypoint
- Add CI to run dependency install, Django checks, migrations, tests, and frontend build.

Exit criteria:

- staging environment exists
- smoke suite exists and runs in CI
- backup and restore process is documented and validated
- required env vars and AWS resources are documented

### Phase 1: Deployment Portability and Elastic Beanstalk Cleanup

Goals:

- remove Python 3.6 and Apache/mod_wsgi coupling
- remove dependence on the legacy Ubuntu host build shape
- modernize the deployment shape before major dependency upgrades
- keep EB, but make the app runtime portable

Work:

- Replace the current custom Apache/mod_wsgi-centric deployment shape with the supported EB Python process model using `gunicorn`.
- Use Amazon Linux through the supported Elastic Beanstalk platform rather than through a bespoke AMI strategy.
- Remove hard-coded Elastic Beanstalk Python 3.6 paths from deployment configuration.
- Replace instance-local TLS certificate handling with AWS-managed TLS termination, with ACM plus ALB as the default target.
- Replace instance-local cron assumptions with a portable scheduling approach. If EB-hosted scheduling is retained temporarily, the invoked command must still be environment-agnostic and standalone.
- Ensure the application can be started, migrated, and collected with explicit commands without relying on Apache configuration side effects.
- Do not port the current Ubuntu Apache/mod_wsgi/Certbot/cron shape to Amazon Linux; replace that host-centric model with the minimum supported Elastic Beanstalk runtime model.
- Treat the legacy Ubuntu CloudFormation and Ansible automation as reference material for inventory and migration only, not as implementation to be updated in place.
- If ACM plus ALB is rejected on cost grounds, document the fallback as an explicit short-term exception; do not silently carry forward Certbot or committed certificate files as part of the target design.
- Even in any short-term fallback, remove committed private key and certificate material from the repository and document certificate issuance, renewal, and rotation ownership.
- Rationalize EB hooks and container commands to the minimum required deployment behavior.

Exit criteria:

- app starts under `gunicorn`
- staging deploy works without Apache/mod_wsgi customization
- migrations and static collection run as explicit commands
- no committed private key or certificate material remains part of the live deployment design

### Phase 2: Backend Modernization

Goals:

- move Django and Python to supported LTS versions
- upgrade or replace blocked backend dependencies in controlled steps

Version path:

1. Python `3.8` + Django `2.2 LTS`
2. Python `3.10` + Django `3.2 LTS`
3. Python `3.12` + Django `4.2 LTS`

Work for each hop:

- upgrade Django and packages to versions compatible with the target checkpoint
- run migrations and smoke tests
- fix deprecations before moving to the next checkpoint

Code changes expected across the backend:

- replace `django.conf.urls.url` with `path` or `re_path`
- replace `ugettext` and `ugettext_lazy` with `gettext` and `gettext_lazy`
- replace old cache backend names with supported backends
- update old CORS settings to current `django-cors-headers` configuration
- replace `raven` WSGI and logging integration with `sentry-sdk`
- replace deprecated or removed storage/backups configuration
- update any package usage affected by newer Django ORM, admin, form, middleware, or settings semantics

Special areas requiring close review:

- GraphQL stack compatibility
- Django admin customization
- blog integration
- image upload, thumbnail, and cropping behavior
- allauth flows
- CKEditor uploads
- S3 storage and backup behavior

Exit criteria:

- app runs on Python `3.12`
- app runs on Django `4.2 LTS`
- migrations apply cleanly on a fresh database and an upgraded database
- smoke tests and manual validation pass in staging

### Phase 3: Frontend and Asset Pipeline Modernization

Goals:

- move the frontend build to supported tooling
- preserve the current Django-integrated multi-entry model

Work:

- Keep the existing architecture of Django rendering pages that consume built React bundles.
- Upgrade:
  - `webpack 3` -> `webpack 5`
  - `webpack-dev-server` -> current compatible version
  - `Babel 6` -> `Babel 7`
  - `React 16` -> `React 18`
  - legacy lint/build tools -> current supported equivalents
  - `node-sass` -> `sass`
- Replace legacy frontend integrations:
  - `react-hot-loader` -> modern refresh flow or remove HMR temporarily during migration
  - `apollo-client` and `react-apollo` -> `@apollo/client`
  - `raven-js` and `raven-for-redux` -> modern Sentry frontend SDK
  - `react-google-maps` -> `@react-google-maps/api`
- Reassess Flow usage. If Flow is not actively providing value, remove Flow tooling rather than dragging it through the migration.
- Regenerate the lockfile with a modern npm version only after package selections are stable.

Exit criteria:

- clean install works on Node `20`
- production frontend build completes successfully
- webpack output still integrates with Django through `django-webpack-loader`
- representative React pages render and function in staging

### Phase 4: Staging Validation and Production Rollout

Goals:

- prove the modernized app in a production-like environment
- reduce production cutover risk

Work:

- Deploy the fully upgraded app to staging on the modernized EB platform.
- Validate:
  - homepage and major content pages
  - admin login and content editing
  - GraphQL endpoint and representative queries/mutations
  - authentication and password reset flows
  - blog rendering
  - file upload and media access
  - static asset loading and cache behavior
  - scheduled task execution
  - error reporting
- Rehearse rollback.
- Take and verify a production database backup before cutover.
- Execute production deployment during a controlled window.
- Run post-deploy smoke tests immediately after release.

Exit criteria:

- rollback procedure is documented and rehearsed
- production backup is verified
- post-deploy smoke tests pass

### Phase 5: Post-Upgrade Cleanup and Future Readiness

Goals:

- remove temporary compatibility code
- leave the system easy to maintain

Work:

- remove transitional compatibility shims no longer needed after Django 4.2 stabilization
- remove dead dependencies and scripts
- document the steady-state local setup and deployment workflow
- record follow-up modernization items that were intentionally deferred

Exit criteria:

- dependency manifests are clean
- deployment documentation reflects the new platform shape
- known deferred items are explicitly tracked

## Dependency Replacement Matrix

These replacements are the default implementation choices unless execution uncovers a concrete incompatibility that requires revisiting them.

| Current dependency or pattern | Planned replacement | Notes |
| --- | --- | --- |
| `raven` | `sentry-sdk[django]` | Replace WSGI wrapper and logging integration |
| `raven-js`, `raven-for-redux` | modern Sentry frontend SDK | Align frontend error capture with backend |
| `boto`, `s3_folder_storage`, `storages.backends.s3boto` | `django-storages` + `boto3` | Modern S3 integration |
| `node-sass` | `sass` | Remove deprecated native binding dependency |
| `react-hot-loader` | modern refresh tooling or temporary removal | Avoid legacy HMR path |
| `apollo-client`, `react-apollo` | `@apollo/client` | Modern Apollo integration |
| `react-google-maps` | `@react-google-maps/api` | Current maintained Google Maps wrapper |
| `django-geoposition` | custom supported replacement | Likely plain lat/lng fields plus custom widget |
| `django-jet` | remove during upgrade | Admin theming is not a blocker requirement |
| VCS-pinned packages | packaged maintained releases where possible | Keep pins only when no viable maintained release exists |

Packages requiring explicit compatibility review during execution:

- `django-blog-zinnia`
- `graphene-django`
- `graphene_django_extras`
- `django-allauth`
- `django-ckeditor`
- `django-compressor`
- `django-filter`
- `easy-thumbnails`
- `sorl-thumbnail`
- `django-image-cropping`
- `django-fluent-comments`

## Deployment and Operations Changes

### Required Deployment Changes

- Move off the current Python 3.6-targeted EB configuration.
- Stop relying on custom Apache/mod_wsgi files in `.ebextensions`.
- Stop deploying committed certificate and private key material.
- Standardize startup, migration, and static collection commands.
- Keep S3-backed storage for portability and operational simplicity.

### Required Operational Changes

- Validate database migration strategy against production data.
- Validate S3 media and static access patterns after storage backend migration.
- Ensure the scheduled job mechanism is explicit and documented.
- Ensure error reporting continues to work after the move from `raven`.
- Ensure the club can continue routine admin/content work without retraining on a bespoke new platform.

## Test and Validation Plan

### Automated Validation

- `manage.py check`
- `manage.py check --deploy` in production-like settings
- `manage.py makemigrations --check`
- full migration run on a clean database
- upgrade migration run against a restored production-like database
- smoke tests in CI
- frontend install and production build on Node `20`

### Manual Validation in Staging

- browse the homepage and key public pages
- log in through the user account flow
- log into admin and save an edited object
- load at least one React-backed page from each important area
- execute representative GraphQL queries and mutations
- upload and render media
- verify cached/static assets load correctly
- trigger or observe a scheduled job
- confirm Sentry receives a test error in staging

### Release Validation

- verify a fresh database backup exists before release
- deploy in a controlled window
- run post-deploy smoke tests immediately
- verify monitoring and logs
- verify rollback readiness before closing the change window

## Risks, Blockers, and Mitigations

### Risk: Legacy Package Incompatibility

Several Django packages in this repo are old enough that direct upgrades may not exist or may imply behavior changes.

Mitigation:

- use staged LTS checkpoints
- replace blockers instead of forcing them
- validate each high-risk integration in staging

### Risk: Minimal Existing Tests

The lack of tests increases the chance of regressions during package and framework upgrades.

Mitigation:

- add a small but meaningful smoke suite before major changes
- rely on staging validation for critical content and admin paths

### Risk: Deployment Drift

The current production environment may include behaviors not fully captured in the repo.

Mitigation:

- inventory AWS resources and production settings before implementation
- validate staging against observed production behavior rather than repo assumptions alone

### Risk: Frontend Toolchain Churn

Webpack/Babel/React changes can create many small integration failures even if the visible app stays the same.

Mitigation:

- keep the frontend architecture stable
- upgrade tooling deliberately
- use representative page-level validation after each major frontend step

### Risk: Storage and Media Regression

S3 storage backend changes can break uploads, URLs, thumbnails, or cached assets.

Mitigation:

- validate uploads, thumbnails, and static loading in staging before production
- keep the bucket layout stable where possible

## Rollback Strategy

Rollback must be defined before production cutover. The release is not ready without a documented rollback path.

Minimum rollback components:

- verified pre-release database backup
- previous known-good application artifact or deployment version
- clear procedure for restoring app and database independently if needed
- decision point for aborting the release if post-deploy smoke tests fail

Rollback rehearsal should be performed in staging or an equivalent safe environment before the production change window.

## Future Option: ECS Fargate

Elastic Beanstalk is the chosen near-term target because it is cheaper and operationally lighter for this site. A later move to ECS Fargate should remain possible with limited app rework if the modernization follows the portability rules in this document.

If a later Fargate migration is pursued, the intended shape is:

- ALB in front of the web service
- Django web container running `gunicorn`
- RDS for MySQL
- S3 for static and media
- ECR for container images
- AWS-managed secrets/configuration
- scheduled tasks run through ECS scheduled tasks or an equivalent AWS-native scheduling mechanism

The current modernization must therefore avoid reintroducing host-specific behavior that would complicate containerization later.

## Open Questions and Prerequisites

These items should be answered or confirmed before execution begins:

- the exact current production database version
- whether production still includes any unmanaged Ubuntu 18.04 host outside the repo-defined EB flow
- current TLS termination path and DNS ownership details
- whether memcached should be retained or replaced during modernization
- whether `django-blog-zinnia` has a viable Django 4.2-compatible path or should be replaced
- whether Flow should be removed entirely during frontend modernization
- what level of automated test coverage can be added before Phase 2 begins

## Definition of Done

The modernization is complete when all of the following are true:

- production runs on a modern AWS Elastic Beanstalk Python platform
- the app runs on Python `3.12`
- the app runs on Django `4.2 LTS`
- the frontend builds on Node `20`
- legacy blockers have been replaced or removed
- staging validation and production smoke validation pass
- rollback is documented and rehearsed
- the deployment shape is portable enough that a future ECS Fargate move would be mainly an infrastructure packaging exercise rather than another app rewrite
