from services.theme_requirement_detector import ThemeRequirementDetector
from services.environment_planner import EnvironmentPlanner
from services.ddev_script_generator import DdevScriptGenerator

# Test 1: Theme detection from metadata and paths
print("--- Test 1: Core and Contrib Theme Detection ---")
metadata = {
    "title": "Fix alignment bug in Olivero theme and Gin administrator layout",
    "component": "theme system",
    "problem_description_html": "<p>When using olivero, things look weird. We should also test with gin subtheme.</p>",
    "tags": "olivero, gin",
}

modified_files = [
    "core/themes/olivero/css/base.css",
    "themes/contrib/gin/gin.theme",
    "themes/custom/my_subtheme/my_subtheme.info.yml"
]

detected = ThemeRequirementDetector.detect(metadata, modified_files)
print("Detected themes:", detected)
print("Is claro contrib?", ThemeRequirementDetector.is_contrib("claro"))
print("Is gin contrib?", ThemeRequirementDetector.is_contrib("gin"))
print("Is my_subtheme contrib?", ThemeRequirementDetector.is_contrib("my_subtheme"))

# Test 2: Environment planning with contrib themes and modules
print("\n--- Test 2: Environment Planning with Contribs ---")
env_metadata = {
    "title": "GIN admin theme and paragraphs module issues",
    "component": "gin",
    "version": "10.3.x-dev",
    "problem_description_html": "Using paragraphs, webform, and olivero.",
    "patch_file_ids": ["7032291"]
}
env_files = [
    "core/themes/olivero/css/base.css",
    "themes/contrib/gin/gin.theme"
]

plan = EnvironmentPlanner.plan(env_metadata, env_files)
print("Plan modules:", plan["required_modules"])
print("Plan themes:", plan["required_themes"])
print("Plan contrib modules:", plan["contrib_modules"])
print("Plan contrib themes:", plan["contrib_themes"])

# Test 3: DDEV Script Generation
print("\n--- Test 3: DDEV Script Generation for Drupal 10 ---")
script = DdevScriptGenerator.generate(plan)
print(script)

# Test 4: DDEV Script Generation for Drupal 7
print("\n--- Test 4: DDEV Script Generation for Drupal 7 ---")
plan_d7 = plan.copy()
plan_d7["project_type"] = "drupal7"
plan_d7["checkout_ref"] = "7.x"
script_d7 = DdevScriptGenerator.generate(plan_d7)
print(script_d7)
