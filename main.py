from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "CareerMatch AI server is running"}
