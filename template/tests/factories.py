"""FactoryBoy factories for every model. Always call them with ``.create()``."""

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.notes.models import Note


class UserFactory(factory.django.DjangoModelFactory):
    """A user with a known password, ``password``."""

    class Meta:
        """Factory metadata."""

        model = get_user_model()
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    password = factory.django.Password("password")


class NoteFactory(factory.django.DjangoModelFactory):
    """A note written now."""

    class Meta:
        """Factory metadata."""

        model = Note

    owner = factory.SubFactory(UserFactory)
    text = factory.Faker("sentence")
    written_at = factory.LazyFunction(timezone.now)
