import pytest
from budgie.budgie import main

def test_main(capsys):
    main()
    captured = capsys.readouterr()
    assert "Budgie" in captured.out
