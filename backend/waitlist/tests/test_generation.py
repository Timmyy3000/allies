import pytest

from waitlist.exceptions import WaitlistValidationError
from waitlist.services.generation import validate_output


def test_validate_output_rejects_ally_name_as_address():
    with pytest.raises(WaitlistValidationError):
        validate_output("Hola, Roban!", ally_name="Roban")


def test_validate_output_does_not_reject_ally_name_as_substring():
    assert validate_output("Hola, Robando!", ally_name="Roban") == "Hola, Robando!"
