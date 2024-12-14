.PHONY: format lint

# Run isort to sort imports
format:
    isort .

# Run ruff to lint the code
lint:
    ruff .