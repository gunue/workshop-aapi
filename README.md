# workshop-aapi

Synthetic checkout fixture for the AI-assisted OpenShift operations workshop.
One image serves three independent namespaces. The demo cluster's own Argo CD
owns these fixtures; the existing Lightspeed gateway/MCP only observes them.

The app serves `/healthz`, `/readyz`, and `/api/checkout` on port 8080. Set
`CHECKOUT_MODE=normal`; any other value exits 64 with a structured validation
error. Responses contain fixed synthetic data. There is no database, credential,
Kubernetes API client, request log, or filesystem write.

## Local validation

Requires Python 3.9+ and `oc` or `kubectl` (Kustomize is used offline):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -B -m unittest discover -s tests -v
CHECKOUT_MODE=normal python3 -B app/server.py
```

Tests accept the three documented intentional faults and reject cross-team fault
placement. A passing render test does not establish live cluster health.

## Image

`Containerfile` pins its UBI Python base. Only `app/server.py` is copied. Both
Docker and Podman context ignore files allowlist the build inputs. Runtime uses
an arbitrary non-root UID, read-only root filesystem and no capabilities.

```bash
docker build -f Containerfile -t gunayeng/workshop-aapi:REVIEWED_TAG .
```

Publish only after reviewing the added image layers. Replace every overlay's
image digest together; scenarios never change images or mutable tags.

## GitOps and scenarios

See [scenario operations](docs/scenarios.md). `deploy/overlays/ss76v/team-{a,b,c}`
are separate Applications. `gitops/ss76v` is bootstrap-only and must be applied to
the demo cluster's `openshift-gitops`, never the central SECCL Argo CD.

Argo CD reads the public repository over HTTPS without repository credentials.
Private configuration and environment files belong outside this repository. Existing namespaces
and observer RBAC remain infrastructure-owned. No namespace, RBAC, Secret or
operator objects are included here.
