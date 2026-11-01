from fastapi import FastAPI

from app.logica import NOME, saude

app = FastAPI(title=NOME)
app.get("/saude")(saude)
