from classifiers.fix_strategy_generator import FixStrategyGenerator

signals = [
    "Filter value normalization issue",
    "Query construction pipeline issue",
    "Likely query builder or filter processing bug"
]

functions = [
    "_build",
    "convertExposedInput"
]

result = FixStrategyGenerator.generate(signals, functions)

print(result)