# Target instruments while retaining strong live Music suppression

On 2026-10-16 the user requested preserving clapping and audience sounds while
removing only instruments, then explicitly prioritized strong Music removal
when that conflicts with audience preservation. This revises ADR-0004's desired
content boundary and the old glossary's classification of crowd as Music;
retain the existing speech model as the live default until a replacement meets
both suppression and timing requirements. Do not restore the rejected mixture
or broadly pass transients: these also restore drums and other instruments.

Evaluate models that separate Music from Vocal and SFX against applause,
cheering, percussion, singing, and overlapping mixtures. Speech enhancement is
not an instruments-only classifier; current loss of audience sounds is a known
model limitation, not evidence that audience sounds are unwanted.
