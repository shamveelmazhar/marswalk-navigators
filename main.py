"""Entry point for running the Marswalk Navigators FastAPI service."""
import uvicorn
from marswalk.api import app

if __name__ == "__main__":
    uvicorn.run("marswalk.api:app", host="0.0.0.0", port=8000, reload=True)
