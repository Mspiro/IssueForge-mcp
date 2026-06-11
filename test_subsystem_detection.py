from classifiers.subsystem_detector import SubsystemDetector

files = [
    "core/modules/views/src/ViewExecutable.php",
    "core/modules/views/src/Plugin/views/filter/FilterPluginBase.php"
]

result = SubsystemDetector.detect_from_paths(files)

print(result)