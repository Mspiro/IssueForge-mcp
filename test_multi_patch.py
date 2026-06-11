from services.multi_patch_analyzer import MultiPatchAnalyzer


patch_ids = [
    "7032291",
    "7038984",
    "7038985"
]

analyzer = MultiPatchAnalyzer()

results = analyzer.analyze_all_patches(patch_ids)

best_patch = analyzer.select_best_patch(results)

print(best_patch)