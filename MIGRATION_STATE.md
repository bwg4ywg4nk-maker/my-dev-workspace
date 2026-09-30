1.








 






ProfessionalPresentationAgent — Migration Handoff
Current Repository
/Users/sultannejaiman/CodexProjects/ProfessionalPresentationAgent

Shortcut:
~/CodexProjects/ProfessionalPresentationAgent

Latest known state:
Branch: main
Working tree: clean
Current phase: Milestone 3C.2b
Next major task: Phase 4.5B trusted provider activation

The latest completed work was the provider build/runtime identity prerequisite. It passed independent review, was committed, the initially omitted test files were amended into that commit, and git status --short was clean afterward.
1. Architecture Overview & Key Files
High-level presentation pipeline
The project evolved from a basic PowerPoint generator into a deterministic, evidence-bound presentation system.
User topic / documents
        ↓
Immutable source capture
        ↓
Deterministic extraction
        ↓
Evidence validation / normalization
        ↓
Content binding
        ↓
Presentation planning
        ↓
Semantic composition
        ↓
Display/layout resolution
        ↓
Trusted typography/provider boundary
        ↓
PowerPoint renderer
        ↓
Editable PPTX

Only the renderer layer should depend directly on python-pptx.
Earlier architecture:
Validated evidence + content
→ Presentation plan
→ Composition
→ Composition model
→ PowerPoint renderer
→ PPTX

Completed major milestones
Milestone 1
Initial deterministic presentation pipeline.
Commit:
4f7267d Complete Milestone 1 presentation pipeline

Included:
- presentation model
- composition
- renderer abstraction
- python-pptx implementation
- native PowerPoint charts
- basic QA
Milestone 2
Evidence/extraction system.
Completed:
- immutable source snapshots
- deterministic extraction
- evidence verification
- quantitative evidence
- evidence projection
- offline demonstration
Important commits included:
4dabe9a Add Milestone 2 Phase 1 evidence foundation
9ac954a Add deterministic snapshot extraction
c86d726 Add Milestone 2 Phase 2B evidence verification
f46e8d9 Add Milestone 2 Phase 2C quantitative evidence
c589471 Add Milestone 2 Phase 2D.1 evidence projection
770ebbd Add Milestone 2 Phase 2D.2 offline demo

Milestone 3A
Generalized content binding.
9824d5b Add Milestone 3A generalized content binding

Milestone 3B
Presentation planning.
e9e0ea0 Add Milestone 3B presentation planning

Milestone 3C.1
Semantic composition.
b28a8b2 Add Milestone 3C.1 semantic composition

Milestone 3C.2a
Display resolution.
0ad5222 Add Milestone 3C.2a display resolution

Milestone 3C.2b Architecture
This became the largest security/determinism phase.
The purpose is to ensure layout/typography measurements are produced only by an explicitly verified runtime/provider environment.
Conceptually:
Protected deployment
        ↓
Restricted native launcher
        ↓
Hardened Runtime / loader verification
        ↓
Attachment/provisioning verification
        ↓
Deployment binding verification
        ↓
Provider build/runtime identity verification
        ↓
Isolated Python bootstrap
        ↓
Trusted provider activation     ← NEXT PHASE
        ↓
Layout measurement

The system intentionally fails closed unless every prerequisite is established.
Frozen typography/layout contract
Main document:
docs/milestone3_phase3c2b_layout.md

Commit:
06e0bfa Freeze Milestone 3C.2b layout contract

Important fixed assumptions include:
Profile:
ascii-lf-arial-regular-basic-720dpi-v1

Scope:
- printable ASCII U+0020–U+007E
- LF-only text
- LTR
- Arial Regular
- 18 / 24 / 32 pt
- Pillow BASIC layout
- no fallback
- no hyphenation
- no wrapping
- no justification
- no synthetic styles
- exact metric/rounding rules
- negative bearings retained
Arial SHA-256:
525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9

Do not modify or reinterpret this frozen contract.
Important Native / Security Components
Restricted launcher
Primary files:
tools/restricted_launcher/launcher.c
tools/restricted_launcher/bootstrap.c

Implemented:
- restricted original environment
- deferred Python load
- isolated CPython startup
- process identity
- lifecycle invalidation
- fork/retry rejection
- no Python-settable qualification token
Relevant commit:
6695bf2 Add Milestone 3C.2b restricted launcher Phase 2

Bootstrap:
7543a66 Add Milestone 3C.2b isolated bootstrap Phase 3

Pillow / provider foundation
Important files:
src/presentation_agent/_pillow_basic.py
src/presentation_agent/_provider_manifests.py
src/presentation_agent/layout.py
src/presentation_agent/_build_evidence.py

Controlled-build foundation commit:
a0707ee Add Milestone 3C.2b controlled build Phase 1

Same-face cmap agreement:
0035b39 Add Milestone 3C.2b cmap agreement Phase 4

Deployment evidence
Important files:
src/presentation_agent/_deployment_evidence.py
src/presentation_agent/_shared_cache.py

Supporting documentation:
tools/restricted_launcher/DEPLOYMENT_EVIDENCE.md

Features:
- runtime artifact inventory
- CPython modules
- native extensions
- universal/fat Mach-O support
- dyld shared-cache identity
- architecture checks
- immutable hashes
- runtime identity
Known deterministic runtime identity previously produced:
sha256:eb4120c8bd159d205cdb82316d951124e4e38d5c311fc9f0f6623d760e1f2114

Launch policy
Important file:
src/presentation_agent/_launch_policy.py

Documentation:
tools/restricted_launcher/LAUNCH_POLICY_EVIDENCE.md

This binds:
- allowed environment
- launcher identity
- startup sequence
- runtime evidence
- protection assumptions
Hardened Runtime / loader-state layer
Important native files:
tools/restricted_launcher/hardened_runtime.c
tools/restricted_launcher/loader_state.c
tools/restricted_launcher/startup_inventory.c

Python-side inventory:
src/presentation_agent/_startup_inventory.py

Implemented:
- hardened runtime checking
- library validation retained
- loader-variable rejection
- CDHash/process binding
- native startup image inventory
- process identity continuity
- fresh-exec boundary
No disable-library-validation entitlement should be introduced casually.
Deployment protection
Python implementation:
src/presentation_agent/_deployment_protection.py

Documentation:
tools/restricted_launcher/DEPLOYMENT_PROTECTION.md

Explicit threat-model decision:
Root/admin is trusted for the lifetime of the protected process.

The system does not attempt to survive a malicious root/admin who can arbitrarily replace kernel state, mounts, backing stores, or authenticated pins.
Deployment protection verifies concepts including:
- read-only protected deployment
- mount identity
- backing store
- protected pin file
- path containment
- protection across lifecycle checkpoints
- concurrent invalidation
A concurrency defect was found and fixed: an in-flight lifecycle check may not succeed after another thread permanently invalidates the lifecycle.
Attachment provisioning protocol
Files:
tools/restricted_launcher/attachment_protocol.h
tools/restricted_launcher/attachment_provisioner.c
tools/restricted_launcher/attachment_observer.c

Tests:
tests/test_milestone3_phase3c2b_attachment.py

Implemented:
- trusted-admin lease/provisioning model
- boot/session binding
- fresh challenges
- per-process leases
- Mach audit-token sender authentication
- protection against inherited/transferred-descriptor misuse
- backing-image/pin identity
- replay protection
- disconnect/fork invalidation
- identity recheck before success
Attachment → launcher integration
Files:
tools/restricted_launcher/attachment_launcher.c
tests/attachment_launcher_test_support.py
tests/test_milestone3_phase3c2b_attachment_launcher.py

The integration:
- establishes attachment state before Python load
- retains lease across bootstrap
- binds process identity
- verifies deployment/path binding
- permanently rejects invalid lifecycle state
A TOCTOU-style path defect was found and fixed:
dlopen() must use the exact retained, fingerprint-verified framework path rather than a separate mutable caller buffer.

Deployment binding package
Python file:
src/presentation_agent/_deployment_binding.py

Test:
tests/test_milestone3_phase3c2b_binding.py

This deterministic package binds:
- deployment evidence hash
- launch-policy evidence hash
- startup inventory
- protected launcher path
- Python framework path
- module-resolution paths
- attachment pin-file digest
- deployment identity
It is not itself an authorization token or lease.
Native deployment adapter
Native file:
tools/restricted_launcher/deployment_binding.c

Test:
tests/test_milestone3_phase3c2b_native_adapter.py

It consumes the deployment binding before Python loading.
Important invariant fixed during review:
A missing native package must never fall back to an older unverified load seam.

The native binding is mandatory in the production load path.
Provider identity prerequisite — latest completed work
Python:
src/presentation_agent/_provider_identity.py

Native:
tools/restricted_launcher/provider_identity.c
tools/restricted_launcher/deployment_inputs.h

Documentation:
tools/restricted_launcher/PROVIDER_IDENTITY.md

Tests:
tests/test_milestone3_phase3c2b_provider_identity.py
tests/test_milestone3_phase3c2b_native_provider.py

Existing files also modified during this prerequisite included:
src/presentation_agent/_deployment_binding.py
tools/restricted_launcher/deployment_binding.c
tools/restricted_launcher/attachment_launcher.c
tools/restricted_launcher/launcher.c
tools/restricted_launcher/bootstrap.c

The provider identity binds authenticated identities for:
- controlled build
- runtime
- provider adapter/artifacts
- font
- frozen profile
Native verification rechecks those artifacts through the trusted attachment/deployment boundary.
Latest review result:
A. PROVIDER IDENTITY REVIEW PASS

This work was committed, then the two initially omitted test files were added via:
git commit --amend --no-edit

Latest known:
git status --short
# no output

2. Current Bugs / Incomplete Work
There is no known unresolved committed bug at the latest checkpoint.
The primary remaining work is functionality not yet implemented.
Phase 4.5B provider activation — NOT COMPLETE
The provider itself remains intentionally closed.
Current desired transition:
Fully verified native state
        ↓
trusted activation handoff
        ↓
_open_provider()

But only the verified native execution path must be capable of this.
Ordinary Python execution must continue to fail.
Must still prevent
- ordinary interpreter activation
- Python-settable activation token
- Python-settable boolean/state
- environment-variable bypass
- public setter
- public qualification hook
- stale activation state
- replayed state
- forked state
- attachment lease loss
- deployment mismatch
- launch-policy mismatch
- startup-inventory mismatch
- provider artifact mismatch
- lifecycle retry after permanent invalidation
Important
Even once Phase 4.5B works:
Do not call the runtime “production qualified” yet.

That belongs to Phase 5 acceptance.
Phase 5 — NOT STARTED
Phase 5 is the final acceptance/qualification gate.
Expected validation includes:
- successful clean fresh-exec run
- deterministic repeated runs
- correct provider measurements
- ordinary interpreter still denied
- wrong Arial rejected
- wrong build/runtime rejected
- modified provider rejected
- wrong evidence rejected
- attachment/pin mismatch rejected
- startup inventory mismatch rejected
- fork/retry rejected
- lifecycle mutation rejected
- lease loss rejected
- final trusted end-to-end layout operation
Final regression / documentation pass — NOT DONE
After Phase 5:
full test suite
→ final negative tests
→ integration/demo
→ documentation cleanup
→ Git review
→ final commit/checkpoint

3. Immediate Next Technical Tasks
Task 1 — Resume Phase 4.5B
This should be the next Codex objective.
Recommended prompt:
Continue ProfessionalPresentationAgent Milestone 3C.2b.

TASK: implement only Phase 4.5B trusted provider activation.

Do not modify the frozen contract.
Do not start Phase 5.
Do not stage or commit.
Do not research broadly.

Prerequisites are now committed:
- protected deployment binding package;
- native deployment adapter;
- provider build/runtime identity verification;
- attachment lease and provisioning;
- substitution protection;
- Hardened Runtime;
- startup inventory;
- lifecycle/fork invalidation;
- deployment and launch-policy evidence.

Implement only:

1. Allow provider initialization only after every trusted native prerequisite
   has verified successfully in the same process/lifecycle.

2. Keep ordinary Python execution fail-closed.

3. Do not expose:
   - Python-settable token;
   - setter;
   - boolean;
   - environment bypass;
   - public activation API.

4. Permanently reject activation after:
   - lifecycle invalidation;
   - fork;
   - lease loss;
   - evidence mismatch;
   - startup inventory mismatch;
   - provider identity mismatch.

5. Do not claim final production qualification.

Add focused Phase 4.5B positive and negative tests only.

Validation:
- focused Phase 4.5B tests;
- nearby provider/layout/launcher tests;
- git diff --check;
- git status --short.

Return only:

A. PHASE 4.5B READY FOR REVIEW

or

B. BLOCKED
- concrete blocker
- minimum fix

Task 2 — Independent review
If implementation returns A, perform a narrow read-only review.
Do not stage before review.
Review should verify:
- activation originates only from native trusted state
- no ordinary Python path can reproduce it
- state is same-process and lifecycle-bound
- invalidation is irreversible
- activation cannot be replayed
- provider initialization does not equal final qualification
Task 3 — Commit Phase 4.5B
Only after independent review passes:
git add ...
git diff --cached --check
git commit ...
git status --short

Final status must be clean.
Task 4 — Phase 5 acceptance
Only after Phase 4.5B is committed.
This should exercise the complete chain:
protected deployment
→ trusted launcher
→ attachment verification
→ deployment binding
→ provider identity
→ native activation
→ Pillow provider
→ deterministic typography measurement

Task 5 — Full project validation
After Phase 5:
- complete regression suite
- deterministic output check
- final sample deck
- documentation consistency
- Git cleanliness
- final milestone commit
4. Custom Rules & Requirements Established
Development workflow
Always use:
PLAN
→ REVIEW / CHALLENGE
→ IMPLEMENT
→ INSPECT
→ TEST
→ VALIDATE
→ GIT REVIEW
→ HUMAN COMMIT

Do not allow Codex to skip directly from implementation to commit.
Codex prompting
Prompts should be:
- short
- narrowly scoped
- one objective at a time
- explicit about what not to change
- token-efficient
Avoid broad prompts such as:
finish milestone
review everything
fix all issues

Prefer:
Fix only X.
Run only Y tests.
Return A or B.

Codex quota management
The user has repeatedly hit Codex limits.
Therefore:
- focused tests first
- no full-suite reruns during small increments
- no repeated web research
- no nice-to-have refactors
- no unrelated cleanup
- stop at clean Git checkpoints when quota is low
A reminder has been scheduled for the weekly reset.
Git rules
Before independent review
Do not:
git add
git commit
git push

After review passes
The user prefers all obvious Git commands together rather than one command per message.
Typical sequence:
git add ...

git diff --cached --check

git commit -m "..."

git status --short

Expected final state:
git status --short
# no output

If reviewed files were accidentally omitted
Use:
git add <missing-files>
git diff --cached --check
git commit --amend --no-edit
git status --short

Temporary WIP rule
If exiting Codex while work is unreviewed:
git stash push -u -m "WIP <description>"

Check:
git stash list

Restore later:
git stash pop

Do not create a normal commit solely to preserve unfinished/unreviewed work.
Security / qualification rules
Fail closed
If evidence or state is:
- missing
- malformed
- stale
- mismatched
- changed
- partially verified
- forked
- disconnected
- replayed
the provider path must reject.
No best-effort fallback.
No Python qualification token
Never add:
- public Python setter
- public boolean
- magic environment variable
- reusable Python object
- token returned to Python that establishes qualification
Ordinary interpreter execution must remain unable to manufacture trusted state.
Native-before-Python rule
Trust-critical deployment verification must occur before Python is loaded.
Do not solve native verification by launching another Python process.
Hardened Runtime
Preserve:
- Hardened Runtime
- library validation
- loader-state verification
- startup inventory verification
Do not add:
com.apple.security.cs.disable-library-validation

unless explicitly redesigned and reviewed.
Threat model
Explicitly accepted:
Privileged root/admin is trusted for the process lifetime.

The project is not required to defend against a malicious administrator capable of changing:
- kernel state
- mounts
- backing stores
- authenticated pins
- trusted deployment configuration
This assumption must remain documented and explicit.
Provider activation versus qualification
These are distinct.
Phase 4.5B may establish:
trusted provider activation

It must not claim:
production qualification

Final qualification belongs only to Phase 5 after acceptance testing.
Typography contract rule
Do not modify or reinterpret:
docs/milestone3_phase3c2b_layout.md

without deliberately reopening the frozen contract.
Do not copy, publish, or commit Arial font bytes.
The project may bind/hash the font artifact, but the font file itself must remain external/private.
Migration Summary
The project is not in a broken state. It currently has a clean Git checkpoint after completing and reviewing the provider identity prerequisite.
The next workflow should not redo deployment protection, attachment provisioning, native adapter work, provider identity work, or the frozen typography contract.
Resume directly at:
Milestone 3C.2b
→ Phase 4.5B trusted provider activation
→ Phase 5 acceptance
→ final regression / documentation / completion

Approximate project state at migration:
Milestone 3C.2b: ~93–96% complete
Overall current roadmap: ~90%+ complete

The principal remaining engineering objective is to safely open the provider only through the trusted native execution path, then prove the complete system in Phase 5.