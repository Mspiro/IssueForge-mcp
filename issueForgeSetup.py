#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil

# ANSI colors for styling
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner():
    banner = r"""
{BLUE}{BOLD}======================================================================
  _____  _____  _____ _    _ ______ ______ ____  _____   _____ ______ 
 |_   _|/ ____|/ ____| |  | |  ____|  ____/ __ \|  __ \ / ____|  ____|
   | | | (___ | (___ | |  | | |__  | |__ | |  | | |__) | |  __| |__   
   | |  \___ \ \___ \| |  | |  __| |  __|| |  | |  _  /| | |_ |  __|  
  _| |_ ____) |____) | |__| | |____| |   | |__| | | \ \| |__| | |____ 
 |_____|_____/|_____/ \____/|______|_|    \____/|_|  \_\\_____|______|
                                                                      
                  Drupal Issue Repro & Patch Engine
======================================================================{RESET}
""".replace("{BLUE}", BLUE).replace("{BOLD}", BOLD).replace("{RESET}", RESET)
    print(banner)


def check_prerequisites():
    print(f"{BLUE}Checking prerequisites...{RESET}")
    # Check Python version
    if sys.version_info < (3, 8):
        print(f"{RED}Error: Python 3.8+ is required.{RESET}")
        sys.exit(1)

    # Check Git
    if not shutil.which("git"):
        print(f"{RED}Error: Git is required to clone and update IssueForge.{RESET}")
        sys.exit(1)

    # Check DDEV
    if not shutil.which("ddev"):
        print(f"{YELLOW}Warning: DDEV is not installed. You will need it to provision environments.{RESET}")

    print(f"{GREEN}Prerequisites OK.{RESET}\n")


def setup_workspace():
    print(f"{BLUE}{BOLD}Step 1: Workspace Directory Selection{RESET}")
    current_dir = os.path.dirname(os.path.abspath(__file__))

    target_dir = input(f"Select installation directory [{current_dir}]: ").strip()
    if not target_dir:
        target_dir = current_dir

    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)
    print(f"Target directory set to: {GREEN}{target_dir}{RESET}\n")

    # Clone/Pull repo if files don't exist
    required_files = ["server.py", "requirements.txt", "services", "classifiers"]
    missing_files = [f for f in required_files if not os.path.exists(os.path.join(target_dir, f))]

    if missing_files:
        print(f"{BLUE}Repository files are missing. Cloning Mspiro/IssueForge-mcp...{RESET}")
        try:
            # Clone into temp and move or clone directly if empty
            if os.listdir(target_dir):
                # Directory not empty, clone into temp then copy
                temp_dir = os.path.join(target_dir, "temp_clone")
                subprocess.run(["git", "clone", "https://github.com/Mspiro/IssueForge-mcp.git", temp_dir], check=True)
                for item in os.listdir(temp_dir):
                    if item == ".git":
                        continue
                    shutil.move(os.path.join(temp_dir, item), os.path.join(target_dir, item))
                shutil.rmtree(temp_dir)
            else:
                subprocess.run(["git", "clone", "https://github.com/Mspiro/IssueForge-mcp.git", target_dir], check=True)
            print(f"{GREEN}Cloned successfully.{RESET}\n")
        except Exception as e:
            print(f"{RED}Error cloning repository: {e}{RESET}")
            sys.exit(1)
    else:
        print(f"{GREEN}Existing IssueForge installation detected.{RESET}\n")

    return target_dir


def setup_venv(target_dir):
    print(f"{BLUE}{BOLD}Step 2: Python Virtual Environment Setup{RESET}")
    venv_dir = os.path.join(target_dir, "venv")

    # Resolve pip command path first
    if os.name == "nt":
        pip_path = os.path.join(venv_dir, "Scripts", "pip")
        python_path = os.path.join(venv_dir, "Scripts", "python")
    else:
        pip_path = os.path.join(venv_dir, "bin", "pip")
        python_path = os.path.join(venv_dir, "bin", "python")

    # Check if virtual environment is missing or corrupt (missing pip)
    if not os.path.exists(pip_path):
        print("Virtual environment or pip missing. Recreating environment...")
        if os.path.exists(venv_dir):
            try:
                shutil.rmtree(venv_dir)
            except Exception:
                pass
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)

    print("Installing python dependencies...")
    req_file = os.path.join(target_dir, "requirements.txt")
    subprocess.run([pip_path, "install", "-r", req_file], check=True)
    print(f"{GREEN}Virtual environment ready.{RESET}\n")

    return python_path


def configure_keys(target_dir):
    print(f"{BLUE}{BOLD}Step 3: LLM API Key Configuration{RESET}")
    env_file = os.path.join(target_dir, ".env")

    # Read existing keys if any
    existing_keys = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    existing_keys[k.strip()] = v.strip()

    print("Configure your keys below. Press Enter to keep existing, or skip.")
    gemini_key = input(f"Gemini API Key [{existing_keys.get('GEMINI_API_KEY', 'None')}]: ").strip()
    openai_key = input(f"OpenAI API Key [{existing_keys.get('OPENAI_API_KEY', 'None')}]: ").strip()
    anthropic_key = input(f"Anthropic API Key [{existing_keys.get('ANTHROPIC_API_KEY', 'None')}]: ").strip()

    # Fallback to existing if blank
    gemini_key = gemini_key or existing_keys.get("GEMINI_API_KEY", "")
    openai_key = openai_key or existing_keys.get("OPENAI_API_KEY", "")
    anthropic_key = anthropic_key or existing_keys.get("ANTHROPIC_API_KEY", "")

    # Save to .env
    with open(env_file, "w") as f:
        f.write("# IssueForge Environment Configuration\n")
        f.write(f"GEMINI_API_KEY={gemini_key}\n")
        f.write(f"OPENAI_API_KEY={openai_key}\n")
        f.write(f"ANTHROPIC_API_KEY={anthropic_key}\n")

    print(f"{GREEN}API keys successfully configured in .env file.{RESET}\n")


def run_interactive_loop(target_dir, python_path):
    print(f"{BLUE}{BOLD}Step 4: Issue Analysis & Reproduction{RESET}")

    # Inject target directory to python path
    sys.path.insert(0, target_dir)
    os.chdir(target_dir)

    try:
        from server import IssueForgeServer
        from services.environment_provisioner import EnvironmentProvisioner
        from services.patch_applier import PatchApplier
    except ImportError as e:
        print(f"{RED}Error importing IssueForge services: {e}{RESET}")
        print("Please verify the files are present in the target directory.")
        return

    engine = IssueForgeServer()

    while True:
        issue_url = input(f"\nEnter Drupal.org issue URL (or 'q' to quit): ").strip()
        if not issue_url:
            continue
        if issue_url.lower() == "q":
            break

        print(f"\n{BLUE}Analyzing issue details...{RESET}")
        try:
            context = engine.analyze_issue(issue_url)
        except Exception as e:
            print(f"{RED}Failed to analyze issue: {e}{RESET}")
            continue

        print(f"\n{GREEN}{BOLD}=== Issue Analysis Success ==={RESET}")
        print(f"{BOLD}Title:{RESET} {context.get('issue_title')}")
        print(f"{BOLD}Component:{RESET} {context.get('component')}")
        print(f"{BOLD}Target Branch:{RESET} {context.get('environment_plan', {}).get('checkout_ref')}")
        print(f"{BOLD}Latest Patch ID:{RESET} {context.get('environment_plan', {}).get('latest_patch_id')}")
        print(f"{BOLD}Patch Compatibility:{RESET} {context.get('patch_compatibility', {}).get('is_compatible')}")
        print(f"{BOLD}RTBC Status:{RESET} {context.get('patch_status')}")

        print(f"\n{BOLD}Reproduction Steps:{RESET}")
        for idx, step in enumerate(context.get("reproduction_steps", []), 1):
            print(f"  {idx}. {step}")

        # 1. Ask to provision environment
        provision_choice = input(f"\nWould you like to provision a local Drupal environment? (y/n): ").strip().lower()
        if provision_choice == "y":
            env_plan = context.get("environment_plan", {})
            issue_id = issue_url.split("/")[-1]
            print(f"\n{BLUE}Provisioning Drupal container environment (env_{issue_id})...{RESET}")
            try:
                res = EnvironmentProvisioner.provision(issue_id, env_plan)
                if res.get("success"):
                    env_path = res.get("env_path")
                    site_url = res.get("site_url")
                    print(f"{GREEN}Environment provisioned successfully!{RESET}")
                    print(f"Site Path: {env_path}")
                    print(f"Site URL:  {BLUE}{site_url}{RESET}")

                    # Copy and Run Reproduction Script
                    repro_script = context.get("reproduction_script")
                    if repro_script:
                        print(f"\n{BLUE}Writing and executing reproduction setup script...{RESET}")
                        repro_file = os.path.join(env_path, "setup_reproduction.php")
                        with open(repro_file, "w") as rf:
                            rf.write(repro_script)

                        # Run via DDEV Drush script
                        run_res = subprocess.run(
                            ["ddev", "drush", "scr", "setup_reproduction.php"],
                            cwd=env_path,
                            capture_output=True,
                            text=True
                        )
                        if run_res.returncode == 0:
                            print(f"{GREEN}Reproduction script executed successfully!{RESET}")
                            print(run_res.stdout)
                        else:
                            print(f"{RED}Reproduction script failed: {run_res.stderr}{RESET}")
                else:
                    print(f"{RED}Provisioning failed: {res.get('message')}{RESET}")
                    continue
            except Exception as e:
                print(f"{RED}Error provisioning: {e}{RESET}")
                continue

            # 2. Ask to apply patch
            latest_patch_id = env_plan.get("latest_patch_id")
            if latest_patch_id:
                apply_choice = input(f"\nLatest patch {latest_patch_id} is available. Would you like to apply it? (y/n): ").strip().lower()
                if apply_choice == "y":
                    print(f"\n{BLUE}Checking compatibility and applying patch {latest_patch_id}...{RESET}")
                    try:
                        apply_res = PatchApplier.apply_patch(env_path, str(latest_patch_id))
                        if apply_res.get("success"):
                            print(f"{GREEN}Success! Patch applied and Drupal cache rebuilt.{RESET}")
                            print(apply_res.get("message"))
                        else:
                            print(f"{RED}Patch application failed: {apply_res.get('message')}{RESET}")
                    except Exception as e:
                        print(f"{RED}Error applying patch: {e}{RESET}")


def main():
    print_banner()
    check_prerequisites()
    target_dir = setup_workspace()
    python_path = setup_venv(target_dir)
    configure_keys(target_dir)
    run_interactive_loop(target_dir, python_path)
    print(f"\n{GREEN}IssueForge Session closed. Thank you!{RESET}")


if __name__ == "__main__":
    main()
