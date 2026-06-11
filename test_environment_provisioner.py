from server import IssueForgeServer
from services.environment_provisioner import EnvironmentProvisioner

print("--- Step 1: Getting issue details ---")
server = IssueForgeServer()
result = server.analyze_issue(
    "https://www.drupal.org/project/drupal/issues/3517198"
)

env_plan = result["environment_plan"]
print("Environment Plan:")
for k, v in env_plan.items():
    print(f"  {k}: {v}")

print("\n--- Step 2: Running Environment Provisioner ---")
# Let's provision using the issue ID 3517198
try:
    provision_res = EnvironmentProvisioner.provision("3517198", env_plan)
    print("\nProvisioning Result:")
    for k, v in provision_res.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"\nProvisioning Failed: {e}")
