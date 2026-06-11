from classifiers.patch_status_classifier import PatchStatusClassifier

signals = ["Ready for community review"]

status = PatchStatusClassifier.classify(signals)

print(status)