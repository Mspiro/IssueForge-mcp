from classifiers.patch_plan_generator import PatchPlanGenerator

result = PatchPlanGenerator.build_plan(
    modified_files=[
        "core/modules/views/src/ViewExecutable.php"
    ],
    modified_functions=[
        "_build",
        "convertExposedInput"
    ],
    detected_subsystems=[
        "Views",
        "Plugin system"
    ],
    root_cause_signals=[
        "Query construction pipeline issue"
    ]
)

print(result)