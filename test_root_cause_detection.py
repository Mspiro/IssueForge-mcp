from classifiers.root_cause_detector import RootCauseDetector

functions = [
    "_build",
    "convertExposedInput"
]

subsystems = [
    "Views",
    "Plugin system"
]

result = RootCauseDetector.detect(functions, subsystems)

print(result)