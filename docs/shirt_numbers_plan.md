# Plan: First-class ShirtNumber management

## Context

Today the shirt number lives directly on the `Member` row as `shirt_number = CharField(max_length=4, blank=True)` (`src/members/models/member.py:102`). This has several problems:

- No history — if a member gives up their shirt, the previous assignment is lost.
- No distinction between *the shirt* and *who's wearing it* — a shirt can't be marked out-of-circulation ("retired number", "damaged", "reserved").
- Uniqueness is enforced only by a nightly check (`src/core/management/commands/check_members.py:113-134`), so collisions can sit in the DB until someone runs the report.
- "One number per current member per gender" is a de facto rule but there's no DB mechanism for it.

The club currently has a pool of 171 shirts for each gender (Male 0-170, Female 0-170 — #0 is a legal shirt) but the max is **configurable** via `ClubInfo` and the pool is **extensible** over time. The club wants:

- A first-class model of each shirt in the pool with states **Available / Assigned / Unavailable**.
- Historic tracking of who wore each shirt and when.
- When a member stops being current (`Member.is_current` goes False), their shirt is reserved until **the end of the season after the one in which they last appeared** (so a player whose last appearance was in 2025-26 is reserved through end of 2026-27; a player whose last appearance was in 2023-24 is released immediately because that grace window has already elapsed). During the reservation window the shirt is Unavailable.
- Automatic re-assignment of the same shirt (if still held by that member in the grace window) when the member becomes current again.
- An optional reason and optional end date for an Unavailable shirt.
- The max shirt number is stored as a `ClubInfo` setting, editable in admin, and raising the max automatically extends the pool.

The design is **date-based** (start / optional end), not season-scoped, so mid-season reassignments are representable.

---

## Design

### Two new models in `src/members/models/shirt_number.py`

**`ShirtNumber`** — the pool (initially 342 rows; 171 × 2 genders — shirts 0..170 per gender, with #0 included), pre-populated by data migration and extensible via ClubInfo. Fields:

| Field | Type | Notes |
|---|---|---|
| `number` | `PositiveSmallIntegerField` | validator `MinValueValidator(0)` — shirt #0 is a legal number. No hard max on the field; the cap is enforced by the pool-extension logic driven by `ClubInfo`. |
| `gender` | `CharField(max_length=6, choices=Gender.Choices)` | from `src/core/models/util.py:70-77` |
| `status` | `CharField(max_length=12, choices=ShirtNumberStatus.Choices, default=Available)` | computed via `recompute_status()`, stored for list/filter speed |
| `unavailable_reason` | `CharField(max_length=255, blank=True, default='')` | required when status becomes Unavailable |
| `unavailable_until` | `DateField(null=True, blank=True)` | optional; past date → shirt returns to Available/Assigned on next recompute |

- `Meta.unique_together = ('number', 'gender')`, `ordering = ('gender', 'number')`.
- `ShirtNumberManager` with `by_gender(g)`, `available()`, `unavailable()`.
- `current_assignment()` returns the assignment where `end_date is None OR end_date >= today` (the single "active" row — this covers both normal assignment and grace-period hold).
- `recompute_status(save=True)` chooses the state via:
  1. If there is a current assignment:
     - If `assignment.member.is_current` is True → **Assigned**.
     - Else → **Unavailable** (member on grace-period hold).
  2. Elif `unavailable_reason` is set and (`unavailable_until is None` or `unavailable_until >= today`) → **Unavailable**.
  3. Else → **Available**.

**`ShirtNumberAssignment`** — history. Fields:

| Field | Type | Notes |
|---|---|---|
| `shirt` | `FK(ShirtNumber, on_delete=CASCADE, related_name='assignments')` | |
| `member` | `FK('Member', on_delete=CASCADE, related_name='shirt_assignments')` | |
| `start_date` | `DateField(default=timezone.now)` | |
| `end_date` | `DateField(null=True, blank=True)` | `None` ⇒ this is the current assignment |

- `Meta.ordering = ('-start_date',)`, index on `('shirt', 'end_date')`.
- Manager with `by_member`, `by_shirt`, `active()` (= `end_date IS NULL OR end_date >= today`), `current()` (= `end_date__isnull=True`).
- `clean()` enforces the business rules (all FK-touching checks guarded on `shirt_id` being set, because Django's `full_clean()` still invokes `clean()` even after `clean_fields()` has recorded a "required FK missing" error — accessing `self.shirt` on an unsaved blank row would raise `RelatedObjectDoesNotExist`):
  - `end_date >= start_date` (reject rows where the assignment "ended before it began").
  - `member.gender == shirt.gender`.
  - If the row is active (`end_date` NULL or in the future):
    - No other active row exists for the same **shirt** (one shirt → one member).
    - No other active row exists for the same **member** (one member → one shirt).
    - Both uniqueness queries use `shirt_id` / `member_id`, never `self.shirt` / `self.member`, so they never touch the related-object descriptor on blank rows.
- `save()` calls `full_clean()`, wraps the insert and `shirt.recompute_status()` in `transaction.atomic()`.
- `delete()` recomputes shirt status after deletion.

### Why no DB-level partial unique index

Production is MySQL (`src/cshc/settings/production.py:19`); local is SQLite. MySQL has no partial unique indexes, so we can't portably enforce "at most one row per shirt with `end_date IS NULL`" at the schema level. Enforcement therefore lives in `clean()` + `save()` (`full_clean()` is called from save, admin uses `full_clean` on inlines). The nightly integrity probe in `check_members.py` is kept as a safety net.

### Status enum

Add `ShirtNumberStatus` to `src/core/models/util.py` using the plain-class pattern already used by `Gender`, `DivisionResult`, etc. (`util.py:24-77`):

```python
class ShirtNumberStatus(object):
    Available   = 'Available'
    Assigned    = 'Assigned'
    Unavailable = 'Unavailable'
    Choices = (
        ('Available',   'Available'),
        ('Assigned',    'Assigned'),
        ('Unavailable', 'Unavailable'),
    )
```

Re-exported via `src/core/models/__init__.py`.

### Member.is_current signal wiring — with grace period

A new `src/members/signals.py` with:

- `pre_save(Member)` caches `_prev_is_current` on the instance by reading the old DB value (`Member.objects.only('is_current').get(pk=instance.pk)`).
- `post_save(Member)`:
  - **True → False** (departure): for every active assignment (end_date null or future) belonging to this member, compute `end_date = grace_period_end_for(member)` and save (triggers `recompute_status`). If the computed date is today or earlier, the assignment is effectively closed and the shirt is freed; if it's in the future, the shirt is **Unavailable** (reserved) until that date.
  - **False → True** (re-activation): find the member's most recent active assignment (end_date null OR end_date >= today, i.e. within grace window). If one exists, clear its `end_date` (back to None) — they resume with the same shirt. If no active assignment survives (grace period already elapsed, shirt was reassigned or freed), do nothing — the admin must create a new assignment manually. We do **not** steal the shirt from someone else.
- Register `members.signals` in `MembersConfig.ready()` (`src/members/apps.py`).

`grace_period_end_for(member)` is a helper in `src/members/models/shirt_number.py`. It anchors the reservation to the member's **last appearance's season**, not to today:

```python
def grace_period_end_for(member, today=None):
    """End of the season following the member's last match-appearance season.

    If the member has no appearances at all, grace period is zero
    (end_date = today) — they never earned a reservation.

    If the "next season" row doesn't exist in the DB yet (common when the
    departing player played in the current season and the following season
    hasn't been seeded yet), a synthetic end-date is computed from the
    configured SEASON_END_MONTH / SEASON_END_DAY on last_season.end.year + 1,
    so the player still gets a proper reservation window.
    """
    today = today or timezone.now().date()
    last_appearance = (
        member.appearances.select_related('match')
        .order_by('-match__date').first()
    )
    if not last_appearance:
        return today
    try:
        last_season = Season.objects.by_date(last_appearance.match.date)
    except Season.DoesNotExist:
        return today
    next_season = Season.objects.next(last_season)
    if next_season:
        return next_season.end
    return date(last_season.end.year + 1, SEASON_END_MONTH, SEASON_END_DAY)
```

**Examples (today = 2026-10-20):**

| Member's last appearance | Last-appearance season | Next season | Grace end-date | Effect |
|---|---|---|---|---|
| 2024-03-15 (match in 2023-24) | 2023-24 | 2024-25 (ends ~2025-06-30) | 2025-06-30 (past) | Shirt freed immediately |
| 2026-02-10 (match in 2025-26) | 2025-26 | 2026-27 (ends ~2027-06-30) | 2027-06-30 | Reserved until 2027-06-30 |
| 2026-09-20 (match in 2026-27) | 2026-27 | 2027-28 (ends ~2028-06-30) | 2028-06-30 | Reserved until 2028-06-30 |
| none | — | — | 2026-10-20 (today) | Shirt freed immediately |

**Nightly reconciliation**: add a step to `src/core/management/commands/nightly_tasks.py` that calls `ShirtNumber.recompute_status(save=True)` on **every** `ShirtNumber` (~342 rows — cheap full sweep). This handles both the grace-period expiry case and any status drift from backdoor writes. Log every correction. See "Status drift reconciliation" below for the full picture.

### Configurable pool size via ClubInfo

`ClubInfo` is a key-value table (`src/core/models/club_info.py`), not a fixed-column model, so no schema change needed. Introduce two canonical keys:

- `MaxShirtNumberMale` (default `"170"`)
- `MaxShirtNumberFemale` (default `"170"`)

Seeded by the same `0013` data migration that creates the initial pool.

Access helper in `src/members/models/shirt_number.py`:

```python
DEFAULT_MAX_SHIRT_NUMBER = 170

def get_max_shirt_number(gender):
    key = 'MaxShirtNumberMale' if gender == Gender.Male else 'MaxShirtNumberFemale'
    try:
        return int(ClubInfo.objects.get(key=key).value)
    except (ClubInfo.DoesNotExist, ValueError):
        return DEFAULT_MAX_SHIRT_NUMBER
```

**Pool extension**: when the max is raised in admin, add any missing `ShirtNumber` rows for that gender. Wire a `post_save` signal on `ClubInfo` keyed on the two names: when either key saves, iterate `0..new_max` for the matching gender and `get_or_create` any missing `ShirtNumber` rows (idempotent). Lowering the max does NOT delete existing shirts — it just prevents future creations (we never destroy history). If the user lowers below an active shirt's number, that shirt remains but is flagged by the integrity probe in `check_members`.

Also add a standalone management command `src/core/management/commands/sync_shirt_pool.py` that reads both `ClubInfo` values and performs the same `get_or_create` sweep. This is useful for CI/fresh envs and for one-shot admin runs if the signal was ever bypassed. Follows the existing `BaseCommand` convention from `init_data.py`.

**The command also reconciles stored status against the derived truth** — see "Status drift reconciliation" below. In sequence it:

1. For each gender: `get_or_create` rows 0..ClubInfo max.
2. For every `ShirtNumber` in the DB: capture the stored `status`, call `recompute_status(save=True)`, and report any rows whose status changed (format: `"Male #42: Assigned → Available"`).
3. Report any shirt with number > current ClubInfo max for its gender that still has an active assignment.
4. Report any shirt with more than one active assignment (constraint-escape detector — one-shirt-per-member direction).
5. Report any member with more than one active assignment (constraint-escape detector — one-member-per-shirt direction).
6. Exit code non-zero if any discrepancy was found and `--check` flag is passed (so CI can enforce clean state).

For ad-hoc fixes, `ShirtNumberAdmin` also exposes an admin action **"Reconcile status for selected shirts"** that runs step 2 against the selection.

### Status drift reconciliation

`ShirtNumber.status` is a stored field for list/filter speed, but the source of truth is `recompute_status()`. The field can drift from the derived truth when:

- Someone edits a row via raw SQL, `QuerySet.update()`, data migration, or admin field-editing before `readonly_fields` was tightened.
- A `ShirtNumberAssignment` is deleted via `QuerySet.delete()` (the bulk path doesn't call per-instance `delete()`, so the shirt is never notified).
- `unavailable_until` was in the future when set, then the date passed with no further save of the shirt.
- A `Member.is_current` is flipped by a bulk update that doesn't fire signals.

Mitigations layered defence-in-depth:

- **Admin**: `readonly_fields` includes `status`; the admin never writes it directly. The field is still displayed.
- **ORM path**: all first-class writes (`ShirtNumber.save`, `ShirtNumberAssignment.save/.delete`, Member signal) call `recompute_status()`.
- **Scheduled reconciliation**: `nightly_tasks` sweeps every `ShirtNumber` (not just those with expiring assignments — the pool is only ~342 rows, so a full sweep is cheap) and calls `recompute_status(save=True)` on each. Any correction is logged. This is the authoritative "self-heal" step.
- **On-demand**: `python manage.py sync_shirt_pool` or the "Reconcile status" admin action can be run at any time.
- **Integrity probe**: `check_members` reports anything the sweep had to correct, so admins see a trail rather than silent self-healing.

**So, directly answering the question**: if someone sets a shirt to `Assigned` without creating an assignment, (a) they can't do it via admin because the field is readonly, (b) if they do it via a backdoor (`.update()`, SQL, data migration), the next of: nightly sweep / sync_shirt_pool run / any save on that shirt or any of its (phantom) assignments / the "Reconcile status" admin action will flip it back to `Available` and log the correction.

### Admin wiring (`src/members/admin.py`)

**MemberAdmin changes:**
- Removed `'shirt_number'` from `list_filter`, `list_display`, and the Playing `fieldsets` entry.
- Added a readonly `current_shirt_display()` method on `MemberAdmin` that reads `member.current_shirt_number()` and is included in `list_display` so admins still see each member's current shirt in the member list.
- Extended `search_fields` with `'=shirt_assignments__shirt__number'` so the Members admin search box also looks up by shirt number (exact match, matches any assignment — current or historic — the member has ever had). Django's admin applies `.distinct()` automatically because the search traverses a reverse relation.
- A single `MemberShirtAssignmentInline` with a custom `ModelForm` (`MemberShirtAssignmentInlineForm`) that disables fields according to row state **for regular staff**:
  - **New row** (no PK yet): fully editable so the admin can pick a shirt and dates.
  - **Existing active row** (has PK, `end_date` is NULL or in the future): the shirt FK is disabled — changing which shirt a member holds is a *new assignment*, not an edit. Start/end dates remain editable so admins can end the row by setting `end_date`.
  - **Historic row** (has PK, `end_date` in the past): every field is disabled; the row is fully readonly.
  - **Superusers bypass all row-state restrictions**: every field on every row is editable. Model-level `clean()` rules still apply, so superusers can't silently violate the one-active-per-member or gender-match invariants. The `formfield_for_foreignkey` also loosens the shirt dropdown for superusers to all shirts of the member's gender (not just `Available`).
  - The admin's "Add another" button is **always available**; attempting to save a second active row raises a `ValidationError` from `ShirtNumberAssignment.clean()` (the one-active-per-member rule). This keeps the UI simple and uses model-level validation as the single source of truth for the invariant.
  - For regular staff, `formfield_for_foreignkey` limits the shirt dropdown (for new rows) to `Available` shirts of the member's gender plus their currently-held shirt. Existing rows' disabled dropdowns are pinned by the form to just the row's own FK value so the `<select>` renders the right selected option.
  - A shared `_ExistingRowReadonlyFormMixin` carries the "disable fields and narrow the FK queryset" behaviour, consumed by both inline forms. The request is injected into the form class via a dynamic subclass in `get_formset()` (`_inject_request_into_form` helper) so the mixin can check `request.user.is_superuser` from `__init__`.

**New ShirtNumberAdmin:**
- `list_display = ('number', 'gender', 'status', 'current_holder', 'unavailable_reason', 'unavailable_until')`.
- `list_filter = ('status', 'gender')`.
- `search_fields = ('number', 'assignments__member__first_name', 'assignments__member__last_name', 'assignments__member__known_as')`.
- `readonly_fields = ('number', 'gender', 'status')` — pool is fixed; status is derived.
- `has_add_permission` / `has_delete_permission` return `False` (pool is managed via ClubInfo max + `sync_shirt_pool`).
- Admin action: **"Reconcile status for selected shirts"**, which calls `recompute_status(save=True)` on each selected row and reports corrections.
- A single `ShirtAssignmentInline` using the same new/active/historic pattern, via `ShirtAssignmentInlineForm` (also uses `_ExistingRowReadonlyFormMixin`). For regular staff, the member FK is editable only on new rows; it is disabled on all existing rows (active or historic), and the row's dates are disabled on historic rows. Superusers see every field editable on every row, and their member dropdown shows all members of the shirt's gender (no `is_current` / shirtless filter). "Add another" stays visible for everyone; a second active row is rejected by `clean()`'s one-active-per-shirt rule. Autocomplete deliberately **not** used (the inline-in-table layout caused a double-dropdown rendering glitch, and the autocomplete AJAX endpoint on `MemberAdmin` ignores the gender filter).
- Loads `css/admin.css` via `Media.css` for consistency with `MemberAdmin`.

**No standalone ShirtNumberAssignment admin.**
`ShirtNumberAssignment` is deliberately **not** registered at the top level. Assignments are managed exclusively via the two inlines (Member → "Shirt number assignments" and ShirtNumber → "Assignments"). The combined cross-shirt / cross-member list wasn't adding value, and a third admin index entry made the UI more confusing.

### GraphQL (`src/members/schema.py`)

- Add `ShirtNumberType(DjangoObjectType)` and `ShirtNumberAssignmentType` next to `SquadMembershipType` (`schema.py:74-84`).
- **Preserve the existing `shirtNumber` field on `MemberType`** — the five frontend files that already consume it (`squadRosterQuery.jsx`, `memberListQuery.jsx`, `matchDataQuery.jsx`, `MemberAvatar/index.jsx`, `MemberTable/index.jsx`) stay unchanged. The resolver prefers the active assignment and falls back to the most recent historic one, so former players' last-known shirts still appear in public listings:
  ```python
  shirt_number = graphene.String()
  def resolve_shirt_number(self, info):
      assignment = self.current_shirt_number() or self.last_shirt_number()
      return str(assignment.shirt.number) if assignment else ''
  ```
- **Public search by shirt number**: `post_optimize_members` (the `name` filter used by the public member list) is extended so that a purely-numeric search term also matches members with any `ShirtNumberAssignment` on that shirt (current, in grace, or historic). The lookup is a `Q(pk__in=subquery)` so it doesn't inflate the `Count`/`Sum` annotations on the result.
- Expose top-level `shirt_numbers` + `shirt_number_assignments` list fields alongside `squad_memberships` (`schema.py:257`).

### `check_members.py` updates

- `get_duplicate_shirt_numbers` rewritten as an integrity probe — look for shirts with more than one active assignment (`end_date__isnull=True OR end_date__gte=today`). Should normally return nothing; a hit indicates the save/clean enforcement was bypassed.
- Added `get_members_with_multiple_shirts` — the reverse direction: members with more than one active assignment. Same should-never-happen semantics.
- Added a check: shirts whose `number > get_max_shirt_number(gender)` with an active assignment — reports admins lowering the ClubInfo max below in-use shirts.
- `format_inactive_member` rewritten to use `member.current_shirt_number()` (returns a formatted `"42 (grace until 2028-05-30)"` if in grace, `"42"` if assigned, `"-"` otherwise).

### Template update

`src/cshc/templates/members/_profile_pic_thumbnail.html` lines 19 and 25: change `{{ member.shirt_number|default:"" }}` to `{{ member.current_shirt_number.shirt.number|default:"" }}` (the `current_shirt_number()` method is callable in templates without parentheses).

---

## Migration strategy

### `0013_shirt_number.py` — single migration, in order:

1. `CreateModel(ShirtNumber)`.
2. `CreateModel(ShirtNumberAssignment)`.
3. `RunPython(seed_clubinfo_max, delete_clubinfo_max)` — insert `MaxShirtNumberMale=170` and `MaxShirtNumberFemale=170` in `ClubInfo` if absent.
4. `RunPython(populate_pool, delete_pool)` — nested loop reading the ClubInfo values for each gender, creating `ShirtNumber` rows 0..max with status `Available`.
5. `RunPython(migrate_existing, noop)` — for every `Member` with `shirt_number != ''`, inferring plausible dates from playing history:
   - Parse `int(stripped)`. If non-numeric or out of 0..`ClubInfo` max → `print()` a warning and skip.
   - Look up `ShirtNumber.objects.get(number=n, gender=member.gender)`.
   - **Earliest activity** = min of: earliest `SquadMembership.season.start`, earliest `Appearance.match.date`, `user.date_joined` (if any).
   - **Latest activity** = max of: latest `SquadMembership.season.end`, latest `Appearance.match.date`.
   - Current members are processed **first** (sort key `(not is_current, pk)`), so if a non-current member shares the same `(gender, number)` the current member wins the active slot and the non-current row goes in as a closed historic entry.
   - For **current** members (`is_current=True`):
     - `start_date` = earliest activity, or `today` as a fallback (clamped to `<= today`).
     - `end_date` = `None` (open assignment).
     - After insert, set `shirt.status='Assigned'` via `.update()` (the migration's historic `ShirtNumber` model from `apps.get_model` has no `recompute_status` method).
   - For **non-current** members (historic row):
     - `start_date` = earliest activity, or `today - 365d` as a fallback.
     - `end_date` = latest activity, clamped to `yesterday` so the row reads as historic. If `start > end`, start is clamped to `end`.
     - Overlaps with other historic rows on the same shirt are permitted — the `clean()` uniqueness rule applies only to active assignments. The migration uses `apps.get_model` which bypasses `clean()` anyway.
   - Collisions on *active* assignments (two current members claim the same `(number, gender)`) are reported and only the first wins; the loser is logged and left without a shirt.

### Field removal is deliberately deferred to a later release.

The old `Member.shirt_number = CharField(max_length=4, blank=True)` field is **kept on the model** in this release, with a docstring marking it as deprecated. Rationale:

- Production runs all pending migrations on every deploy. Shipping a `RemoveField` migration in the same release that introduces the new system means the old column is dropped before we've verified the new one in production. Keeping the field gives us a release or two to confirm `ShirtNumberAssignment` is populating correctly before the old column goes away.
- Nothing in the code reads or writes it any more — all consumers switched to `member.current_shirt_number()` / the active `ShirtNumberAssignment` — so the stored values will freeze at migration time. That's fine; we're treating them as redundant history.
- The field must stay on the model (not just the DB) so Django keeps writing `shirt_number=''` on every new Member insert. The 0001_initial DB column is `NOT NULL` with no server-side default, so dropping the model attribute while leaving the column in place would break INSERTs under strict-mode MySQL.

**Follow-up release plan**: once the new system has run cleanly in production, remove `shirt_number` from `src/members/models/member.py`, run `python manage.py makemigrations members` to generate the `RemoveField` migration (likely numbered 0014 or 0015 depending on what has landed in between), and ship that in its own PR.

---

## Files

### New
- `src/members/models/shirt_number.py` — the two models + managers + `grace_period_end_for()` + `get_max_shirt_number()`.
- `src/members/signals.py` — pre/post-save handlers on `Member`, plus a `post_save(ClubInfo)` handler for pool extension.
- `src/members/migrations/0013_shirt_number.py` — tables, ClubInfo seed, pool, data migration.
- `src/members/migrations/0014_grant_shirt_number_permissions.py` — data migration that back-grants the auto-created `add/change/delete_shirtnumber` and `add/change/delete_shirtnumberassignment` permissions to every Group and User that already has `members.change_member`. Without this, staff who previously managed shirt numbers via the free-text field would see nothing in the new admin until an admin manually assigned the permissions. Idempotent, safe to re-run.
- `src/core/management/commands/sync_shirt_pool.py` — idempotent sweep that reconciles `ShirtNumber` rows with the current ClubInfo max per gender.

(No `0014_remove_member_shirt_number.py` in this release — the old field is kept and will be removed in a later release once the new system has been validated in production. See "Migration strategy" above.)

### Modified
- `src/members/models/__init__.py` — re-export `ShirtNumber`, `ShirtNumberAssignment`.
- `src/members/models/member.py` — add `current_shirt_number()` method returning the active assignment (open-ended or in grace) or `None`, and `last_shirt_number()` returning the most recent assignment (active or historic) so former players' last-known shirts can be surfaced. The old `shirt_number` CharField is kept but marked deprecated via its docstring; it is no longer referenced anywhere and will be removed in a follow-up release.
- `src/members/apps.py` — add `ready()` method importing `members.signals`.
- `src/members/admin.py` — strip `shirt_number` from `MemberAdmin`; extend `MemberAdmin.search_fields` with `'=shirt_assignments__shirt__number'`; add `MemberShirtAssignmentInline` and `ShirtAssignmentInline`; register `ShirtNumberAdmin`. `ShirtNumberAssignment` is intentionally not registered at the top level.
- `src/members/schema.py` — add two `DjangoObjectType`s and matching list types, a `shirt_number` resolver on `MemberType` that falls back to the last historic assignment, and top-level `shirt_numbers` + `shirt_number_assignments` fields. Extend `post_optimize_members` so numeric search terms also match members with any `ShirtNumberAssignment` on that shirt.
- `src/core/models/util.py` — add `ShirtNumberStatus` class alongside `Gender`.
- `src/core/models/__init__.py` — re-export `ShirtNumberStatus` (via `from .util import *`).
- `src/core/management/commands/check_members.py` — rewrite `get_duplicate_shirt_numbers` as an integrity probe; update `format_inactive_member` to render `"42 (grace until 2028-05-30)"` style; add check for in-use shirts above current ClubInfo max.
- `src/core/management/commands/nightly_tasks.py` — add a reconcile step that recomputes status on every `ShirtNumber`.
- `src/cshc/templates/members/_profile_pic_thumbnail.html` — switch two lines to `member.current_shirt_number.shirt.number`.

Reused patterns:
- Plain-class Choices enum (`src/core/models/util.py:24-77`).
- Manager/QuerySet style with `by_member` / `current()` (`src/members/models/squad_membership.py:27-47`).
- `TabularInline` with `extra = 0` (`src/members/admin.py:11-15`).
- `@admin.register(Model)` decorator (`src/members/admin.py:17-74`).
- `DjangoObjectType` + resolver (`src/members/schema.py:74-131`).
- Data migration + management-command-friendly `print()` warnings (`src/core/management/commands/check_members.py`).

---

## Verification

1. **Schema sanity**
   - `python manage.py makemigrations --dry-run members` → "No changes detected" after 0013 is in place.
   - `python manage.py check` → no system check errors.

2. **Local migration run (SQLite)**
   - `python manage.py migrate members 0013` → `ShirtNumber.objects.count() == 342` (171 per gender × 2).
   - Spot-check: `Member.objects.filter(is_current=True).exclude(shirt_number='').count()` roughly equals `ShirtNumberAssignment.objects.filter(end_date__isnull=True).count()` (minus any non-numeric skips reported in the migration output).
   - The old `shirt_number` column is still there — it's deliberately not dropped in this release.

3. **Admin walkthrough**
   - `/admin/members/shirtnumber/` lists 342 rows; filter by gender / status works.
   - Open a Member → "Shirt number assignments" inline shows the member's history.
   - Attempt to create a second open assignment on the same shirt → raises `ValidationError`.
   - On a shirt admin page, set `unavailable_reason="Retired"` → saving flips `status` to `Unavailable`; clearing the reason flips it back.
   - Set `unavailable_until` to a past date → the next save of the shirt (or next recompute) returns it to Available/Assigned.

4. **`is_current` signal + grace period**
   - **Reservation case**: pick a current member whose latest `Appearance` is in the current or previous season. Edit → `is_current=False` → save. Confirm the assignment's `end_date` is the end date of the season *after* their last-appearance season, and the shirt's `status = Unavailable`.
   - **Immediate release case**: pick a current member whose latest `Appearance` is two or more seasons ago (or who has no appearances at all). Set `is_current=False` → save. Confirm `end_date` ends up today-or-earlier and shirt status becomes `Available` on the same save.
   - **Re-activation inside the window**: flip the first member's `is_current` back to True while still inside their reservation window. Confirm the existing assignment's `end_date` is cleared back to None (same assignment row, no new one), status flips to `Assigned`.
   - **Re-activation after the window**: simulate elapsed grace by setting `end_date` to yesterday manually, run `python manage.py nightly_tasks`, confirm shirt status flips to `Available`. Flip the member back to current → confirm no auto-reassignment.
   - **Collision**: assign the shirt manually to a NEW member during the first member's reservation window — should fail with a `ValidationError` ("That shirt is already assigned") because the first member still has an active (future-end-dated) assignment.

5. **Configurable pool size via ClubInfo**
   - In admin → `ClubInfo`, change `MaxShirtNumberMale` from `170` to `175`.
   - Confirm five new `ShirtNumber` rows (Male 171-175, status Available) appear immediately.
   - Lower it back to `170` — the five rows remain (we never destroy history); confirm `check_members` reports nothing because they have no active assignments. Assign one of them → `check_members` now flags it as "above current max".
   - Run `python manage.py sync_shirt_pool` on a fresh DB → produces the same 342 rows.

6. **Status drift reconciliation**
   - Pick a shirt in `Available` state. In a shell, run `ShirtNumber.objects.filter(pk=sn.pk).update(status='Assigned')` to bypass `save()`. Reload in admin → shows `Assigned` incorrectly.
   - Run `python manage.py nightly_tasks` (or `sync_shirt_pool`). Reload in admin → status is back to `Available`, and the command output logs the correction.
   - Pick a shirt in `Assigned` state. Delete its underlying assignment via `ShirtNumberAssignment.objects.filter(pk=a.pk).delete()` (bulk, skips per-instance delete). Reload → still shows `Assigned`. Run the sweep → corrected to `Available` with a log line.
   - Try to edit `status` directly in the admin change form → the field is readonly; cannot be modified.

7. **GraphQL smoke test**
   - Query `{ members { results { fullName shirtNumber } } }` — resolver returns the number string. For a former member whose grace window has elapsed, the resolver falls back to their last historic shirt.
   - On the public member list, type a number into the search box → results include every member who's ever worn that shirt (current, in grace, or historic).
   - Verify in-browser: `MemberList`, `TeamDetail.SquadRoster`, `MemberAvatar`, `MatchData` all render shirt numbers unchanged.

8. **`check_members`**
   - `python manage.py check_members --no-email` → "No duplicate shirt numbers found." Inactive-member report shows `-` for members with no current shirt, or `"42 (grace until 2028-06-30)"` if in grace, or just the number if assigned. If an active shirt is above the ClubInfo max, the command flags it.

9. **Admin search by shirt number**
   - Open `/admin/members/member/`, type `42` in the search box → every member who has ever had shirt #42 appears (current, in grace, or historic). The `Shirt` column in the list shows `-` for anyone who no longer holds it.

10. **Rollback drill**
    - `python manage.py migrate members 0012` reverses cleanly: the data migration's reverse is `noop`, the pool and both new tables are dropped, and `Member.shirt_number` is unaffected (still populated with its pre-migration values). Assignments are lost, which is acceptable at this stage because the authoritative data still lives on `Member.shirt_number`.
