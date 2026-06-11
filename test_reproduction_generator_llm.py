import os
from services.reproduction_generator_llm import ReproductionGeneratorLlm

print("--- Testing LlmClient and ReproductionGeneratorLlm ---")

# Let's inspect active keys
gemini_key = os.getenv("GEMINI_API_KEY")
openai_key = os.getenv("OPENAI_API_KEY")
anthropic_key = os.getenv("ANTHROPIC_API_KEY")

print(f"GEMINI_API_KEY configured: {bool(gemini_key)}")
print(f"OPENAI_API_KEY configured: {bool(openai_key)}")
print(f"ANTHROPIC_API_KEY configured: {bool(anthropic_key)}")

if not (gemini_key or openai_key or anthropic_key):
    print("\nWARNING: No LLM API keys configured. The tool will fall back to manual step echo output.")

issue_title = "Multi-selected grouped view filters use AND instead of OR."
problem_summary = "Grouped filters are not behaving correctly when multiple groups are selected in an exposed filter. The expectation for multiselect view filters, is that they combine selections using OR, not AND."
reproduction_steps = [
    "Create a view (based on any fieldable entity)",
    "Add an exposed dropdown filter (I recommend a List (text) field)",
    "Select Grouped filters and create some groupings",
    "Allow multiple selections",
    "Add a view page for easy testing and save your view",
    "Visit your view and select multiple groups on your exposed filter"
]
detected_subsystems = ["Views", "Plugin system"]
modified_files = [
    "core/modules/views/src/ViewExecutable.php",
    "core/modules/views/src/Plugin/views/filter/FilterPluginBase.php"
]

print("\n--- Generating Reproduction Setup Script via LLM ---")
php_code = ReproductionGeneratorLlm.generate_script(
    issue_title=issue_title,
    problem_summary=problem_summary,
    reproduction_steps=reproduction_steps,
    detected_subsystems=detected_subsystems,
    modified_files=modified_files
)

print("\nGenerated PHP Code Output:")
if php_code:
    print(php_code)
else:
    print("(No response generated - fallback simple script will be used)")
