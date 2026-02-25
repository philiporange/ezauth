import uuid
from datetime import datetime, timezone

import factory

from ezauth.models.application import Application, Environment
from ezauth.models.tenant import Tenant
from ezauth.models.user import User
from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key


class TenantFactory(factory.Factory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Tenant {n}")


class ApplicationFactory(factory.Factory):
    class Meta:
        model = Application

    name = factory.Sequence(lambda n: f"App {n}")
    environment = Environment.dev
    publishable_key = factory.LazyFunction(lambda: generate_publishable_key("dev"))
    secret_key = factory.LazyFunction(lambda: generate_secret_key("dev"))
    primary_domain = "localhost"

    @factory.lazy_attribute
    def jwk_private_pem(self):
        pem, _, _ = generate_jwk_pair()
        return pem

    @factory.lazy_attribute
    def jwk_kid(self):
        _, kid, _ = generate_jwk_pair()
        return kid


class UserFactory(factory.Factory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password_hash = None
    email_verified_at = None
