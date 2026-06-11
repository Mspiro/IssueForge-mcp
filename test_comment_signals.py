from classifiers.comment_signal_detector import CommentSignalDetector

comments = [
    "Needs work: failing test detected.",
    "Reroll patch attached.",
    "RTBC from subsystem maintainer."
]

result = CommentSignalDetector.detect(comments)

print(result)