from api.main import app


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "8000")),
        reload=False,
    )
