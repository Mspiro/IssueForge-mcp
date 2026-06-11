from typing import Any, List


class TextNormalizer:
    """
    Utility for safely flattening mixed metadata structures
    (str | list | int | None) into a single searchable string.
    """

    @staticmethod
    def flatten(values: List[Any]) -> str:
        """
        Convert mixed metadata values into a clean string.
        """

        flattened = []

        for value in values:

            if value is None:
                continue

            if isinstance(value, str):
                flattened.append(value)

            elif isinstance(value, (int, float)):
                flattened.append(str(value))

            elif isinstance(value, list):
                flattened.extend(
                    str(item)
                    for item in value
                    if isinstance(item, (str, int, float))
                )

            elif isinstance(value, dict):
                flattened.extend(
                    str(v)
                    for v in value.values()
                    if isinstance(v, (str, int, float))
                )

        return " ".join(flattened)