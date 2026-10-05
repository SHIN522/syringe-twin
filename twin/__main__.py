"""Start the reusable backend on localhost:8000."""
import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('twin.api:app', host='127.0.0.1', port=int(os.getenv('SYRINGETWIN_API_PORT','8000')),
                log_level='warning')
