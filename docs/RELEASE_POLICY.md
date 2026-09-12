# Scales Release Versioning and Branching Policy

Effective date: 2026-09-11  
Applies to all Scales artifacts until the `v1.0.0` coordinated release.  
Owner: Product  
Review cadence: every major (`0.x.0`) release or quarterly, whichever comes first.

---

## 1. Policy goals

- Keep the three active codebases (`ScalesInfrastructure`, `ScalesMobile`, `DragonHost2-Hermes`) releasable independently before 1.0.
- Make it obvious which client builds can talk to which backend/portal deployment.
- Minimize long-lived release branches; ship from `main` whenever possible.
- Define a predictable hotfix path that does not block normal feature work.
- Document how the four shipping artifacts converge on a single `v1.0.0` version.

---

## 2. Artifacts and repositories

| Artifact | Repository | Delivery channel | Version file / tag |
|----------|------------|------------------|--------------------|
| Backend + Portal | `Garenthino/ScalesInfrastructure` | Docker redeploy on production VPS | `ScalesInfrastructure/pyproject.toml`, git tag, Docker image tag |
| Mobile Android | `Garenthino/ScalesMobile` | Google Play Store; GitHub Releases fallback | `ScalesMobile/pubspec.yaml`, git tag, GitHub Release |
| Desktop KJ (Windows/Linux) | `Garenthino/DragonHost2-Hermes` | In-app auto-update; VPS `/download` fallback | `DragonHost2-Hermes/pyproject.toml` or `version.txt`, git tag, installer filename |
| Documentation | `ScalesInfrastructure/docs/` | Shipped with backend/portal Docker image and published portal | `docs/RELEASE_POLICY.md` (this file) |

> **Note on the two Flutter trees:** The live mobile app is still the standalone `Garenthino/ScalesMobile` repo. The newer `/home/garenthino/Scales/ScalesMobile` monorepo is not yet the release target. Until the monorepo is promoted, all release tooling, tags, and Play Store builds continue to come from `Garenthino/ScalesMobile`.

---

## 3. Interim versioning scheme (pre-1.0)

We follow [Semantic Versioning 2.1.0](https://semver.org/) with one pre-1.0 relaxation:

| Version change | Meaning in pre-1.0 | Examples |
|----------------|--------------------|----------|
| `0.x.0` | Minor release. New features, user-visible changes, breaking API or contract changes are allowed and expected. | `0.3.0`, `0.4.0` |
| `0.x.y` | Patch release. Bug fixes, hotfixes, security patches, performance fixes. No new user-facing features unless they are required to fix a broken flow. | `0.3.1`, `0.3.2` |
| Pre-release tags | Use `-beta.N`, `-rc.N` for staged Play Store tracks or desktop preview channels. | `0.4.0-beta.1`, `0.4.0-rc.2` |
| Build metadata | Use `+build.N` for CI build numbers; not part of version identity. | `0.3.1+build.47` |

### 3.1 Versioning each artifact independently before 1.0

Before 1.0, each artifact is versioned on its own timeline:

- **Backend/portal:** bumps `0.x.y` when the API, admin portal, or deployed Docker image changes.
- **Mobile:** bumps `0.x.y` when a build is cut for Play Store/GitHub Releases.
- **Desktop:** bumps `0.x.y` when a signed installer is published for auto-update.

It is normal and expected for the artifacts to be on different `0.x.y` versions before 1.0 (e.g., backend `0.3.8`, mobile `0.4.1`, desktop `0.3.5`). The compatibility matrix in Section 6 governs which combinations are supported.

### 3.2 Choosing the next version

1. Look up the most recent released version for that artifact.
2. Decide whether the change is user-visible / contract-changing (bump minor) or a fix/stability improvement (bump patch).
3. For coordinated milestones, product may pre-allocate a target minor (e.g., "all artifacts ship `0.4.0` for the loyalty launch").

---

## 4. Branching model

### 4.1 Default: trunk-based development on `main`

- All daily work lands on `main` via pull/merge requests.
- `main` must always be deployable/buildable; CI blocks merges that fail tests or builds.
- Releases are cut from `main` by tagging, not by creating long-lived release branches.

### 4.2 Tags are the release record

- Each release gets an annotated git tag: `v<artifact>-<semver>` is allowed, but we prefer plain `v<semver>` per repo because each repo already represents one artifact.
- Examples:
  - `ScalesInfrastructure`: `v0.3.8`
  - `ScalesMobile`: `v0.4.1`
  - `DragonHost2-Hermes`: `v0.3.5`
- Tags are immutable. If a build is bad, delete the bad release artifact; do not retag.

### 4.3 When release branches are allowed

Create a release branch only when:

1. A long-running stabilization period is needed and `main` must remain open for the next milestone, **or**
2. A hotfix must be applied to a version that is already several commits behind `main` and the fix cannot safely ride the next `main` deploy (see Section 7).

Branch naming: `release/<major>.<minor>` (e.g., `release/0.3`).

### 4.4 Short-lived feature branches

- Use descriptive branch names: `feat/mobile-queue-cancel`, `fix/desktop-rotation-echo`, `docs/release-policy`.
- Rebase or squash-merge onto `main`. Delete remote branches after merge.

---

## 5. Release cadence and alignment

### 5.1 Before 1.0: independent cadence

| Artifact | Target cadence |
|----------|----------------|
| Backend/portal | Continuous deploy from `main`; tagged release every 1–2 weeks or at product milestones. |
| Mobile Android | 2–4 week Play Store releases; patch releases within 48 hours for critical crashes. |
| Desktop KJ | 2–4 week installer releases; urgent hotfixes via in-app auto-update channel. |
| Docs | Updated with every release; no separate version before 1.0. |

### 5.2 The path to 1.0

`v1.0.0` is a **coordinated, date-driven release** that marks the first stable public launch of the complete Scales system. At 1.0:

- All four artifacts share the same version: `v1.0.0`.
- The backend/portal, mobile, and desktop repositories all tag `v1.0.0`.
- The docs hub publishes the `v1.0.0` compatibility matrix and user-facing changelog.
- After 1.0, all four artifacts remain aligned on major/minor versions. Patch releases may still be independent for emergency fixes (e.g., `v1.0.1` mobile-only crash fix), but the minor version is locked across the ecosystem.

### 5.3 1.0 readiness gates

Before tagging `v1.0.0`, product and engineering jointly sign off on:

1. **API contract freeze:** no breaking changes to the mobile/desktop/server contract for at least one full release cycle.
2. **Compatibility matrix green:** the target mobile and desktop builds have been proven against the target backend/portal in production-like conditions.
3. **Rollback tested:** the emergency rollback procedure in Section 7.2 has been exercised at least once end-to-end on staging.
4. **Release channels ready:** Play Store, VPS auto-update, and GitHub Releases are configured and smoke-tested.
5. **Support runbook ready:** version strings are visible in-app/in-portal so support can read them back from users.

---

## 6. Compatibility matrix

The matrix below is the source of truth for which client versions are supported against which backend/portal versions. A cell marked **✅ Supported** means that combination is expected to work and is eligible for support. **⚠️ Deprecated** means it works today but will be dropped at the next minor. **❌ Unsupported** means it may fail and is not supported.

### 6.1 Current compatibility target

| Client / Backend | Backend `0.3.x` | Backend `0.4.x` | Backend `1.0.x` |
|--------------------|-----------------|-----------------|-----------------|
| **Mobile `0.3.x`** | ✅ Supported | ⚠️ Deprecated | ❌ Unsupported |
| **Mobile `0.4.x`** | ⚠️ Deprecated | ✅ Supported | ❌ Unsupported |
| **Mobile `1.0.x`** | ❌ Unsupported | ❌ Unsupported | ✅ Supported |
| **Desktop `0.3.x`** | ✅ Supported | ⚠️ Deprecated | ❌ Unsupported |
| **Desktop `0.4.x`** | ⚠️ Deprecated | ✅ Supported | ❌ Unsupported |
| **Desktop `1.0.x`** | ❌ Unsupported | ❌ Unsupported | ✅ Supported |

### 6.2 Compatibility rules

1. **N and N-1:** a client minor version supports the matching backend minor and the previous backend minor. Older combinations may work but are not guaranteed.
2. **Breaking contract changes:** if a release introduces a breaking API or sync contract change, product and engineering must agree to either:
   - bump the client minor in lockstep, or
   - keep backward compatibility in the server for one minor cycle.
3. **Server-first for breaking changes:** when a breaking server change ships, the corresponding client updates are required before the deprecated window closes.
4. **Emergency overrides:** product can extend a deprecated window by documenting it in the release notes.

### 6.3 Where version information lives

- **Backend:** `GET /v1/health` returns `{ "version": "0.3.8" }`.
- **Portal:** version displayed in the admin footer; reads from the backend health endpoint at build time or from an env var.
- **Mobile:** version shown on Settings → About; sourced from `pubspec.yaml`.
- **Desktop:** version shown in Help → About; sourced from the package version file.

Support must ask for **all three** version strings when triaging cross-system issues.

---

## 7. Hotfix and emergency rollback policy

### 7.1 Hotfix criteria

A hotfix is a patch release (`0.x.y` bump) that is allowed to skip the normal release queue when one of the following is true:

- Production data corruption or loss.
- Security vulnerability with active exposure.
- Payment or authentication flow broken for all users.
- KJ desktop or mobile client cannot connect to the backend at all.
- Performance degradation causing venue-level downtime.

Product and the on-call engineer make the go/no-go decision. Hotfixes may ship with reduced test coverage only if the risk of waiting exceeds the risk of the reduced coverage.

### 7.2 Hotfix procedure (trunk-based)

For a hotfix that can be applied to `main` and then released:

1. Create a branch from the latest `main`: `hotfix/<short-description>`.
2. Fix and add a regression test when feasible.
3. Open a PR, get a single reviewer, and merge to `main`.
4. Run the artifact-specific release checks:
   - Backend/portal: `pytest` + `npm run build` in `web_portal/`.
   - Mobile: `flutter test` + `flutter build apk --release`.
   - Desktop: full Windows build + installer smoke test.
5. Tag the next patch version on `main`.
6. Deploy or publish the artifact.
7. Update the compatibility matrix in this document if the fix changes a contract.

### 7.3 Hotfix from a release branch

If the hotfix cannot ride `main` (e.g., `main` already contains the next minor and the affected production version is behind):

1. Create the release branch from the last known good tag if it does not exist: `git checkout -b release/0.3 v0.3.8`.
2. Branch from the release branch: `hotfix/<short-description>-0.3`.
3. Apply, test, and merge the hotfix into `release/0.3`.
4. Tag a patch release from the release branch: `v0.3.9`.
5. **Forward-port the fix:** cherry-pick or re-apply the same change to `main` so the next minor does not regress.
6. Deploy/publish the patched artifact.
7. Document the branch existence in this file and in release notes.

### 7.4 Emergency rollback procedure

If a release causes critical failure and a forward fix is slower than reverting:

1. **Stop the bleed:** pause further deploys/publishes to the affected channel.
2. **Identify the last known good version.** The compatibility matrix and release notes are the primary references.
3. **Backend/portal rollback:**
   - Re-deploy the previous Docker image tag on the VPS.
   - If a database migration was included, assess whether the schema is backward-compatible. If not, the rollback requires a compensating migration or data repair.
4. **Mobile rollback:**
   - Play Store: promote the previous production release in Play Console (no immediate re-upload).
   - GitHub Releases: mark the bad release as a pre-release and update the download link to the previous APK.
5. **Desktop rollback:**
   - Re-point the in-app update manifest to the previous installer version.
   - Update the VPS `/download` page to serve the previous installer.
6. **Communicate:** post the incident in the internal channel, update the public status page if warranted, and add a retro item.
7. **Recover forward:** once stable, ship a proper hotfix with the root cause fixed.

### 7.5 Rollback guardrails

- Never roll back to a version older than the last successfully exercised backup of the production database.
- If a rollback includes a schema downgrade, require engineering + product sign-off.
- After any rollback, verify the compatibility matrix still reflects the live deployed versions.

---

## 8. Release notes and changelog

- Every tagged release must have release notes in the GitHub Release (mobile/desktop) or in `docs/releases/` (backend/portal).
- Release notes include:
  - Version and date.
  - Link to the milestone/kanban card.
  - User-facing changes (bullet list).
  - API or contract changes, with migration notes.
  - Known issues and deprecations.
  - Compatibility matrix slice for this release.

Keep the canonical `CHANGELOG.md` at `ScalesInfrastructure/CHANGELOG.md` and mirror major mobile/desktop releases there.

---

## 9. Glossary

- **Artifact:** a separately built, versioned, and shipped component of Scales (backend/portal, mobile Android, desktop KJ, docs).
- **Backward-compatible:** a client or server change that does not require a coordinated update on the other side.
- **Breaking contract change:** any change to the API, sync payload, or identity mapping that would cause an existing client to fail or corrupt data.
- **Release branch:** a `release/<major>.<minor>` branch used only for stabilization or backported hotfixes.
- **Trunk-based:** development model where `main` is the single source of truth and releases are tagged from it.

---

*Policy version: 0.1.0 — initial policy before 1.0.*
