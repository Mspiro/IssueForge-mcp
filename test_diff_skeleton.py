from classifiers.diff_skeleton_generator import DiffSkeletonGenerator

plan = {
    "target_files": [
        "core/modules/views/src/ViewExecutable.php"
    ],
    "target_functions": [
        "_build"
    ],
    "edit_strategy": [
        "Merge grouped filter values before WHERE clause construction."
    ]
}

print(DiffSkeletonGenerator.generate(plan))