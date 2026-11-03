"""One finite field budget for condition discovery and mutation preparation."""

MAX_CONDITION_CONTROLLERS = 16
# A simple path contains the selected field plus its distinct controllers.
# Cycles are detected separately; path shape must not reduce the field budget.
MAX_CONDITION_PATH_FIELDS = MAX_CONDITION_CONTROLLERS + 1
