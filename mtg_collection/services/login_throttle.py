"""Limite de tentativas de login erradas, em memória. Sem interface.

Conta os erros por nome de usuário e por endereço de quem tenta. Passou do limite dentro da janela, bloqueia
por um tempo. Acertar a senha zera a contagem daquele usuário. Reiniciar o servidor zera tudo (de propósito:
é uma trava contra robôs, não um cadastro de bloqueios).

Como o servidor fica ligado direto, contagens vencidas são descartadas: sem isso, cada nome inventado por um robô
ficaria na memória para sempre. Há também um teto de chaves (MAX_KEYS); passou dele, saem as mais antigas.
"""
import threading
import time
from collections import deque

WINDOW_SECONDS = 15 * 60
BLOCK_SECONDS = 15 * 60
MAX_PER_USER = 5  # erros seguidos no mesmo usuário
MAX_PER_ADDRESS = 20  # erros vindos do mesmo endereço, em usuários quaisquer
MAX_KEYS = 10_000  # usuários e endereços acompanhados ao mesmo tempo


class LoginThrottle:
    """Contador de erros de login seguro entre threads. Uma instância só (`throttle`) serve o app inteiro;
    os testes criam a sua com um relógio falso (`clock`)."""
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}  # em ordem do último erro (o mais antigo primeiro)
        self._blocked_until: dict[str, float] = {}

    @staticmethod
    def _keys(username: str, address: str) -> list[tuple[str, int]]:
        return [(f"user:{username.strip().lower()}", MAX_PER_USER), (f"addr:{address}", MAX_PER_ADDRESS)]

    def wait_seconds(self, username: str, address: str) -> int:
        """Quanto falta para poder tentar de novo (0 = pode tentar agora)."""
        now = self._clock()
        with self._lock:
            waits = [until - now for key, _ in self._keys(username, address)
                     if (until := self._blocked_until.get(key, 0)) > now]
        return int(max(waits, default=0)) + (1 if waits else 0)

    def failed(self, username: str, address: str) -> None:
        now = self._clock()
        with self._lock:
            for key, limit in self._keys(username, address):
                attempts = self._failures.pop(key, None) or deque()  # reinsere: vai para o fim da ordem
                attempts.append(now)
                while attempts and attempts[0] < now - WINDOW_SECONDS:
                    attempts.popleft()
                if len(attempts) >= limit:  # bloqueia; a contagem recomeça do zero, então nem volta para a lista
                    self._blocked_until[key] = now + BLOCK_SECONDS
                else:
                    self._failures[key] = attempts
            self._prune(now)

    def _prune(self, now: float) -> None:
        """Tira do começo (erros mais antigos) o que já venceu e o que passa do teto. Para no primeiro que ainda
        vale, então em geral olha só uma ou duas chaves."""
        while self._failures:
            key, attempts = next(iter(self._failures.items()))
            if attempts[-1] >= now - WINDOW_SECONDS and len(self._failures) <= MAX_KEYS:
                break
            del self._failures[key]
        if len(self._blocked_until) > MAX_KEYS:  # bloqueios: poucos, só limpa quando passa do teto
            self._blocked_until = {k: until for k, until in self._blocked_until.items() if until > now}
            while len(self._blocked_until) > MAX_KEYS:  # todos ainda valendo: sai o que vence primeiro
                del self._blocked_until[min(self._blocked_until, key=self._blocked_until.get)]

    def succeeded(self, username: str) -> None:
        key = f"user:{username.strip().lower()}"
        with self._lock:
            self._failures.pop(key, None)
            self._blocked_until.pop(key, None)


throttle = LoginThrottle()
