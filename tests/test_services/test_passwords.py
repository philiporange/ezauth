from ezauth.services.passwords import hash_password, needs_rehash, verify_password


def test_hash_and_verify():
    pw = "my-secret-password"
    h = hash_password(pw)
    assert verify_password(pw, h) is True


def test_verify_wrong_password():
    h = hash_password("correct")
    assert verify_password("wrong", h) is False


def test_hash_is_different_each_time():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # Different salts


def test_needs_rehash():
    h = hash_password("test")
    # Freshly hashed with current params should not need rehash
    assert needs_rehash(h) is False
