# backend/auth.py
from dotenv import load_dotenv
from fastapi import HTTPException, Header
from supabase import create_client
import os
load_dotenv()

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]  # service key, not anon key
)

async def get_current_user(authorization: str = Header(...)):
    try:
        token = authorization.replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        return user
    except:
        raise HTTPException(status_code=401, detail="Invalid token")