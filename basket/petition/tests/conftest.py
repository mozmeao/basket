import uuid

import pytest

from basket.petition.models import Petition


@pytest.fixture
def petition():
    return Petition.objects.create(
        name="The Dude",
        email="thedude@example.com",
        title="Dude",
        affiliation="The Knudsens",
        approved=True,
        token=uuid.uuid4(),
    )
