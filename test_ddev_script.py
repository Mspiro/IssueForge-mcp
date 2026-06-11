from services.ddev_script_generator import DdevScriptGenerator

plan = {
    "repository": "https://git.drupalcode.org/project/drupal.git",
    "checkout_ref": "main"
}

print(DdevScriptGenerator.generate(plan))