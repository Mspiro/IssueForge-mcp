class DiffSkeletonGenerator:
    """
    Generate a unified diff-style skeleton from patch plan.
    This is not a full patch yet — it prepares edit anchors.
    """

    @staticmethod
    def generate(plan):

        files = plan.get("target_files", [])
        functions = plan.get("target_functions", [])
        strategies = plan.get("edit_strategy", [])

        skeleton = []

        for file_path in files:

            skeleton.append(f"diff --git a/{file_path} b/{file_path}")
            skeleton.append(f"--- a/{file_path}")
            skeleton.append(f"+++ b/{file_path}")

            for fn in functions:
                skeleton.append(f"@@ function {fn} @@")
                skeleton.append(
                    f"+ // TODO: {strategies[min(len(strategies)-1, functions.index(fn))]}"
                )

            skeleton.append("")

        return "\n".join(skeleton)