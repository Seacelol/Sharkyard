from mtg_collection.services.login_throttle import BLOCK_SECONDS, MAX_PER_ADDRESS, MAX_PER_USER, LoginThrottle


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_blocks_user_after_limit_and_unblocks_later():
    clock = Clock()
    t = LoginThrottle(clock)
    for _ in range(MAX_PER_USER - 1):
        t.failed("Marcelo", "1.1.1.1")
    assert t.wait_seconds("marcelo", "2.2.2.2") == 0
    t.failed("marcelo", "1.1.1.1")
    assert t.wait_seconds(" MARCELO ", "2.2.2.2") > 0  # bloqueia o usuário de qualquer endereço
    assert t.wait_seconds("outro", "2.2.2.2") == 0
    clock.now += BLOCK_SECONDS + 1
    assert t.wait_seconds("marcelo", "1.1.1.1") == 0


def test_blocks_address_trying_many_users():
    t = LoginThrottle(Clock())
    for i in range(MAX_PER_ADDRESS):
        t.failed(f"user{i}", "9.9.9.9")
    assert t.wait_seconds("qualquer", "9.9.9.9") > 0
    assert t.wait_seconds("qualquer", "8.8.8.8") == 0


def test_old_failures_expire_and_success_resets():
    clock = Clock()
    t = LoginThrottle(clock)
    for _ in range(MAX_PER_USER - 1):
        t.failed("ana", "1.1.1.1")
    clock.now += 16 * 60  # fora da janela de 15 min
    t.failed("ana", "1.1.1.1")
    assert t.wait_seconds("ana", "1.1.1.1") == 0
    for _ in range(MAX_PER_USER - 1):
        t.failed("ana", "1.1.1.1")
    t.succeeded("ana")
    t.failed("ana", "1.1.1.1")
    assert t.wait_seconds("ana", "1.1.1.1") == 0
