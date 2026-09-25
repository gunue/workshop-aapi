"""Render-only fixture contracts; these tests never contact a cluster."""

import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEAMS = "abc"
REPOSITORY = "https://github.com/gunue/workshop-aapi.git"
LOCAL_SERVER = "https://kubernetes.default.svc"
APP_LABEL = "app.kubernetes.io/name"
KINDS = {
    ("v1", "ServiceAccount", "checkout-api"),
    ("v1", "Service", "checkout-api"),
    ("apps/v1", "Deployment", "checkout-api"),
    ("route.openshift.io/v1", "Route", "checkout"),
}
POLICY_KINDS = {
    ("v1", "ResourceQuota", "checkout-budget"),
    ("v1", "LimitRange", "checkout-limits"),
}


def render(root, team):
    cli = shutil.which("oc") or shutil.which("kubectl")
    if cli is None:
        raise AssertionError("Install oc or kubectl to run render-only manifest tests")
    path = root / "deploy" / "overlays" / "ss76v" / f"team-{team}"
    result = subprocess.run(
        [cli, "kustomize", str(path)], capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise AssertionError(f"Kustomize failed for team {team}: {result.stderr}")
    objects = [obj for obj in yaml.safe_load_all(result.stdout) if obj]
    indexed = {obj["kind"]: obj for obj in objects}
    if len(indexed) != len(objects):
        raise AssertionError("Unexpected duplicate resource kinds in fixture overlay")
    return indexed


def container(objects):
    return objects["Deployment"]["spec"]["template"]["spec"]["containers"][0]


def set_fault(root, team, enabled):
    overlay = root / "deploy" / "overlays" / "ss76v" / f"team-{team}"
    path = overlay / ("service-selector.yaml" if team == "b" else "runtime.yaml")
    document = yaml.safe_load(path.read_text())
    if team == "b":
        document["spec"]["selector"][APP_LABEL] = (
            "checkout-api-mismatch" if enabled else "checkout-api"
        )
    else:
        target = document["spec"]["template"]["spec"]["containers"][0]
        if team == "a":
            setting = next(item for item in target["env"] if item["name"] == "CHECKOUT_MODE")
            setting["value"] = "invalid-demo-mode" if enabled else "normal"
        else:
            target["resources"]["requests"]["cpu"] = "700m" if enabled else "100m"
    path.write_text(yaml.safe_dump(document, sort_keys=False))


def changes(before, after, path=()):
    """Return differing leaf paths so an intentional fault cannot hide extra edits."""
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in before.keys() | after.keys():
            if key not in before or key not in after:
                result.append(path + (key,))
            else:
                result.extend(changes(before[key], after[key], path + (key,)))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [item for index, pair in enumerate(zip(before, after))
                for item in changes(*pair, path + (index,))]
    return [] if before == after else [path]


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = {team: render(ROOT, team) for team in TEAMS}

    def test_only_owned_namespaced_resources_and_one_pinned_image(self):
        images = set()
        for team, objects in self.rendered.items():
            with self.subTest(team=team):
                identities = {(obj["apiVersion"], obj["kind"], obj["metadata"]["name"])
                              for obj in objects.values()}
                self.assertEqual(identities, KINDS | (POLICY_KINDS if team == "c" else set()))
                for obj in objects.values():
                    self.assertEqual(obj["metadata"]["namespace"], f"workshop-team-{team}")
                image = container(objects)["image"]
                self.assertRegex(image, r"^(?:docker\.io/)?gunayeng/workshop-aapi@sha256:[a-f0-9]{64}$")
                self.assertNotEqual(image.rsplit(":", 1)[-1], "0" * 64, "Replace the placeholder digest before publication")
                images.add(image)
        self.assertEqual(len(images), 1, "Faults must retain the same reviewed image")

    def test_readonly_runtime_has_no_api_identity_or_extra_containers(self):
        for team, objects in self.rendered.items():
            with self.subTest(team=team):
                deployment = objects["Deployment"]["spec"]
                self.assertEqual(deployment["replicas"], 1)
                self.assertEqual(deployment["strategy"]["type"], "Recreate")
                pod = deployment["template"]["spec"]
                self.assertEqual(len(pod["containers"]), 1)
                self.assertFalse(pod.get("initContainers"))
                self.assertFalse(pod.get("volumes"))
                self.assertFalse(pod["automountServiceAccountToken"])
                self.assertEqual(pod["serviceAccountName"], "checkout-api")
                self.assertFalse(objects["ServiceAccount"]["automountServiceAccountToken"])
                app = container(objects)
                self.assertEqual(app["name"], "checkout-api")
                self.assertFalse(app.get("envFrom"))
                self.assertFalse(app.get("volumeMounts"))
                security = app["securityContext"]
                self.assertTrue(security["readOnlyRootFilesystem"])
                self.assertFalse(security["allowPrivilegeEscalation"])
                self.assertFalse(security.get("privileged", False))
                self.assertEqual(security["capabilities"]["drop"], ["ALL"])
                self.assertFalse(security["capabilities"].get("add"))
                pod_security = pod.get("securityContext", {})
                self.assertTrue(security.get("runAsNonRoot", pod_security.get("runAsNonRoot")))
                self.assertNotIn("runAsUser", security)
                self.assertNotIn("runAsUser", pod_security)
                self.assertFalse(pod.get("hostNetwork", False))
                self.assertFalse(pod.get("hostPID", False))

    def test_fault_settings_are_restricted_to_their_designated_team(self):
        for team, objects in self.rendered.items():
            with self.subTest(team=team):
                app = container(objects)
                env = app["env"]
                self.assertEqual(len(env), 1)
                self.assertEqual(env[0]["name"], "CHECKOUT_MODE")
                self.assertNotIn("valueFrom", env[0])
                modes = ("normal", "invalid-demo-mode") if team == "a" else ("normal",)
                self.assertIn(env[0]["value"], modes)
                requests = app["resources"]["requests"]
                self.assertIn(requests["cpu"], ("100m", "700m") if team == "c" else ("100m",))
                self.assertEqual(requests["memory"], "64Mi")
                self.assertEqual(app["resources"]["limits"], {"cpu": "800m", "memory": "128Mi"})
                selector = objects["Service"]["spec"]["selector"]
                self.assertEqual(set(selector), {APP_LABEL})
                permitted = ("checkout-api", "checkout-api-mismatch") if team == "b" else ("checkout-api",)
                self.assertIn(selector[APP_LABEL], permitted)

    def test_routing_and_probes_remain_connected_to_the_healthy_pod(self):
        for team, objects in self.rendered.items():
            with self.subTest(team=team):
                deployment = objects["Deployment"]["spec"]
                labels = deployment["template"]["metadata"]["labels"]
                self.assertEqual(labels[APP_LABEL], "checkout-api")
                self.assertEqual(deployment["selector"]["matchLabels"], {APP_LABEL: "checkout-api"})
                app = container(objects)
                self.assertEqual(app["ports"], [{"name": "http", "containerPort": 8080}])
                for probe, path in (("livenessProbe", "/healthz"), ("readinessProbe", "/readyz")):
                    self.assertEqual(app[probe]["httpGet"], {"path": path, "port": "http"})
                service = objects["Service"]["spec"]
                self.assertEqual(service["type"], "ClusterIP")
                self.assertEqual(len(service["ports"]), 1)
                self.assertEqual(service["ports"][0]["port"], 8080)
                self.assertEqual(service["ports"][0]["targetPort"], "http")
                self.assertEqual(service["ports"][0]["name"], "http")
                route = objects["Route"]["spec"]
                self.assertEqual(route["to"]["kind"], "Service")
                self.assertEqual(route["to"]["name"], "checkout-api")
                self.assertEqual(route["port"]["targetPort"], "http")
                self.assertEqual(route["tls"], {"termination": "edge", "insecureEdgeTerminationPolicy": "Redirect"})
                self.assertNotIn("host", route)

    def test_quota_failure_is_admission_not_invalid_container_resources(self):
        objects = self.rendered["c"]
        hard = objects["ResourceQuota"]["spec"]["hard"]
        self.assertEqual(hard, {"requests.cpu": "500m", "limits.cpu": "1",
                               "requests.memory": "256Mi", "limits.memory": "512Mi", "pods": "4"})
        limits = objects["LimitRange"]["spec"]["limits"]
        self.assertEqual(limits, [{"type": "Container", "min": {"cpu": "10m", "memory": "16Mi"},
                                  "max": {"cpu": "800m", "memory": "128Mi"},
                                  "defaultRequest": {"cpu": "100m", "memory": "64Mi"},
                                  "default": {"cpu": "800m", "memory": "128Mi"}}])
        maximum = int(limits[0]["max"]["cpu"].removesuffix("m"))
        budget = int(hard["requests.cpu"].removesuffix("m"))
        self.assertLessEqual(100, budget)
        self.assertGreater(700, budget)
        self.assertLessEqual(700, maximum)
        self.assertEqual(700 - budget, 200)
        for kind in ("ResourceQuota", "LimitRange"):
            self.assertEqual(objects[kind]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-1")
        self.assertEqual(objects["Deployment"]["metadata"].get("annotations", {}).get(
            "argocd.argoproj.io/sync-wave", "0"), "0")

    def test_each_fault_changes_one_field_and_reset_restores_baseline(self):
        with tempfile.TemporaryDirectory(prefix="workshop-contract-") as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "deploy", root / "deploy")
            for team in TEAMS:
                set_fault(root, team, False)
            baseline = {team: render(root, team) for team in TEAMS}
            for team in TEAMS:
                with self.subTest(team=team):
                    set_fault(root, team, True)
                    fault = {item: render(root, item) for item in TEAMS}
                    expected = copy.deepcopy(baseline)
                    if team == "a":
                        container(expected[team])["env"][0]["value"] = "invalid-demo-mode"
                    elif team == "b":
                        expected[team]["Service"]["spec"]["selector"][APP_LABEL] = "checkout-api-mismatch"
                    else:
                        container(expected[team])["resources"]["requests"]["cpu"] = "700m"
                    self.assertEqual(len(changes(baseline, fault)), 1)
                    self.assertEqual(fault, expected, "Fault escaped its intended field/namespace")
                    set_fault(root, team, False)
                    self.assertEqual({item: render(root, item) for item in TEAMS}, baseline)


class GitOpsTests(unittest.TestCase):
    def test_project_and_applications_cannot_manage_shared_infrastructure(self):
        path = ROOT / "gitops" / "ss76v"
        self.assertTrue((path / "project.yaml").is_file(), "Missing local Argo bootstrap project")
        project = yaml.safe_load((path / "project.yaml").read_text())
        self.assertEqual(project["kind"], "AppProject")
        self.assertEqual(project["metadata"]["name"], "workshop-aapi")
        self.assertEqual(project["metadata"]["namespace"], "openshift-gitops")
        spec = project["spec"]
        self.assertEqual(spec["sourceRepos"], [REPOSITORY])
        self.assertEqual(spec["clusterResourceWhitelist"], [])
        self.assertEqual(spec["clusterResourceBlacklist"], [{"group": "*", "kind": "*"}])
        self.assertEqual({(item["server"], item["namespace"]) for item in spec["destinations"]},
                         {(LOCAL_SERVER, f"workshop-team-{team}") for team in TEAMS})
        allowed = {(api.rpartition("/")[0], kind) for api, kind, _ in KINDS | POLICY_KINDS}
        self.assertEqual({(item["group"], item["kind"]) for item in spec["namespaceResourceWhitelist"]}, allowed)
        for team in TEAMS:
            with self.subTest(team=team):
                app = yaml.safe_load((path / f"team-{team}.yaml").read_text())
                self.assertEqual(app["kind"], "Application")
                self.assertEqual(app["metadata"]["name"], f"workshop-checkout-{team}")
                self.assertEqual(app["metadata"]["namespace"], "openshift-gitops")
                self.assertFalse(app["metadata"].get("finalizers"))
                spec = app["spec"]
                self.assertEqual(spec["project"], "workshop-aapi")
                self.assertEqual(spec["source"], {"repoURL": REPOSITORY, "targetRevision": "lab/ss76v",
                                                   "path": f"deploy/overlays/ss76v/team-{team}"})
                self.assertEqual(spec["destination"], {"server": LOCAL_SERVER, "namespace": f"workshop-team-{team}"})
                self.assertEqual(spec["syncPolicy"]["automated"], {"prune": True, "selfHeal": True, "allowEmpty": False})
                self.assertEqual(spec["syncPolicy"]["syncOptions"], ["FailOnSharedResource=true"])


if __name__ == "__main__":
    unittest.main()
