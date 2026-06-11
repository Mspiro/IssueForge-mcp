class DdevScriptGenerator:
    """
    Generate reproducible DDEV bootstrap shell script.
    Automatically installs:

    - correct Drupal version
    - install profile
    - modules
    - themes
    """

    @staticmethod
    def generate(env_plan: dict):

        repo = env_plan["repository"]
        ref = env_plan["checkout_ref"]
        project_type = env_plan["project_type"]
        install_profile = env_plan["install_profile"]

        modules = env_plan.get("required_modules", [])
        themes = env_plan.get("required_themes", [])

        module_enable_cmd = ""
        theme_enable_cmd = ""
        theme_set_cmd = ""

        if modules:
            module_enable_cmd = (
                f"ddev drush en {' '.join(modules)} -y"
            )

        if themes:

            theme_enable_cmd = (
                f"ddev drush theme:enable {' '.join(themes)} -y"
            )

            theme_set_cmd = (
                f"ddev drush config:set system.theme default {themes[0]} -y"
            )

        contrib_modules = env_plan.get("contrib_modules", [])
        contrib_themes = env_plan.get("contrib_themes", [])

        download_cmds = []

        is_drupal7 = (project_type == "drupal7" or ref.startswith("7"))

        if contrib_modules:
            if is_drupal7:
                download_cmds.append(
                    f"echo 'Downloading contrib modules...'\n"
                    f"ddev drush dl {' '.join(contrib_modules)} -y"
                )
            else:
                packages = [f"drupal/{m}" for m in contrib_modules]
                download_cmds.append(
                    f"echo 'Downloading contrib modules...'\n"
                    f"ddev composer require {' '.join(packages)} -W"
                )

        if contrib_themes:
            if is_drupal7:
                download_cmds.append(
                    f"echo 'Downloading contrib themes...'\n"
                    f"ddev drush dl {' '.join(contrib_themes)} -y"
                )
            else:
                packages = [f"drupal/{t}" for t in contrib_themes]
                download_cmds.append(
                    f"echo 'Downloading contrib themes...'\n"
                    f"ddev composer require {' '.join(packages)} -W"
                )

        download_cmd_str = "\n\n".join(download_cmds)
        if download_cmd_str:
            download_cmd_str += "\n"

        script = f"""#!/bin/bash

PROJECT_NAME=drupal_issue_env

echo "Cloning Drupal..."
git clone {repo} $PROJECT_NAME

cd $PROJECT_NAME

echo "Checking out {ref}..."
git checkout {ref}

echo "Initializing DDEV..."
ddev config --project-type={project_type} --docroot=

echo "Starting DDEV..."
ddev start

echo "Installing dependencies..."
ddev composer install

echo "Installing Drupal ({install_profile} profile)..."
ddev drush si {install_profile} -y

{download_cmd_str}echo "Enabling required modules..."
{module_enable_cmd}

echo "Enabling required themes..."
{theme_enable_cmd}

echo "Setting default theme..."
{theme_set_cmd}

echo "Environment ready!"
ddev launch
"""

        return script