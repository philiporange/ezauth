from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key


def test_publishable_key_dev():
    pk = generate_publishable_key("dev")
    assert pk.startswith("pk_test_")


def test_publishable_key_prod():
    pk = generate_publishable_key("prod")
    assert pk.startswith("pk_live_")


def test_secret_key_dev():
    sk = generate_secret_key("dev")
    assert sk.startswith("sk_test_")


def test_secret_key_prod():
    sk = generate_secret_key("prod")
    assert sk.startswith("sk_live_")


def test_generate_jwk_pair():
    private_pem, kid, jwk_public = generate_jwk_pair()

    assert private_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert len(kid) > 0
    assert jwk_public["kty"] == "RSA"
    assert jwk_public["alg"] == "RS256"
    assert jwk_public["kid"] == kid
    assert "n" in jwk_public
    assert "e" in jwk_public


def test_jwk_pairs_are_unique():
    _, kid1, _ = generate_jwk_pair()
    _, kid2, _ = generate_jwk_pair()
    assert kid1 != kid2
