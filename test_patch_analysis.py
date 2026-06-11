from services.patch_analyzer import PatchAnalyzer

analysis = PatchAnalyzer.analyze_patch_file("test_patch.diff")

print(analysis)