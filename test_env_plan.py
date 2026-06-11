from services.environment_planner import EnvironmentPlanner

metadata = {
    "version": "main",
    "component": "views.module"
}

print(EnvironmentPlanner.plan(metadata))