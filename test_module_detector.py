from services.module_requirement_detector import ModuleRequirementDetector

metadata = {
    "component": "views.module"
}

modified_files = [
    "core/modules/views/src/ViewExecutable.php"
]

print(
    ModuleRequirementDetector.detect(
        metadata,
        modified_files
    )
)