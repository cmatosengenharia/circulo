import sys

NOME = "{{nome}}"


def saudacao(quem: str) -> str:
    return f"{NOME}: olá, {quem}"


if __name__ == "__main__":
    print(saudacao(" ".join(sys.argv[1:]) or "mundo"))
