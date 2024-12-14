.PHONY: format lint

# Run isort to sort imports
format:
    isort .
    ruff format .

# Run ruff to lint the code
lint:
    ruff lint .
