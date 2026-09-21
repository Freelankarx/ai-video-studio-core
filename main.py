import os
import uuid
import shutil
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pyngrok import ngrok

# Import our pipeline modules
from app.audio_pipeline import clone_voice
from app.video_pipeline import generate_scene
from app.sync_pipeline import sync_lips

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="NeuralCut AI Backend")

# CORS is CRITICAL: Allows your Vercel frontend to talk to this Ngrok backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict to your Vercel URL in production (e.g., "https://your-app.vercel.app")
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static folder to serve generated videos back to the frontend
STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def health_check():
    return {"status": "online", "gpu": "ready", "message": "NeuralCut Backend is live!"}

@app.post("/api/generate")
async def generate_video(
    face_image: UploadFile = File(...),
    reference_audio: UploadFile = File(...),
    driving_video: UploadFile = File(None),  # Optional
    prompt: str = Form(...),
    style: str = Form(...)
):
    request_id = uuid.uuid4().hex[:8]
    logger.info(f"🚀 [{request_id}] NEW REQUEST RECEIVED!")
    logger.info(f"📝 Prompt: '{prompt}' | Style: '{style}'")
    logger.info(f"📁 Files: Face({face_image.filename}), Audio({reference_audio.filename})")

    # 1. Setup unique temporary directory for this request
    temp_dir = os.path.join("temp_uploads", request_id)
    os.makedirs(temp_dir, exist_ok=True)
    
    # Use UUIDs for filenames to prevent collisions
    face_ext = os.path.splitext(face_image.filename)[1] or ".jpg"
    audio_ext = os.path.splitext(reference_audio.filename)[1] or ".wav"
    
    face_path = os.path.join(temp_dir, f"face{face_ext}")
    audio_path = os.path.join(temp_dir, f"audio{audio_ext}")
    
    try:
        # Save uploaded files
        with open(face_path, "wb") as buffer:
            shutil.copyfileobj(face_image.file, buffer)
        with open(audio_path, "wb") as buffer:
            shutil.copyfileobj(reference_audio.file, buffer)

        # 2. Run the Sequential AI Pipelines
        logger.info(f"🎙️ [{request_id}] Step 1: Cloning Voice...")
        cloned_audio_path = await clone_voice(audio_path)
        
        logger.info(f"🎬 [{request_id}] Step 2: Generating Scene...")
        raw_video_path = await generate_scene(face_path, prompt, style)
        
        logger.info(f"👄 [{request_id}] Step 3: Syncing Lips...")
        final_video_path = await sync_lips(raw_video_path, cloned_audio_path)

        # 3. Move final video to static folder for frontend access
        output_filename = f"output_{request_id}.mp4"
        final_static_path = os.path.join(STATIC_DIR, output_filename)
        shutil.copy(final_video_path, final_static_path)
        
        # Construct the public Ngrok URL for the video
        tunnels = ngrok.get_tunnels()
        public_url = tunnels[0].public_url if tunnels else "http://localhost:8000"
        video_url = f"{public_url}/static/{output_filename}"

        logger.info(f"✅ [{request_id}] Generation complete! Video URL: {video_url}")

        return {
            "success": True,
            "message": "Video generated successfully!",
            "video_url": video_url,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"❌ [{request_id}] ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # 4. Clean up temp files to save GPU/Disk space
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"🧹 [{request_id}] Temporary files cleaned up.")

# ==========================================
# 🚀 NGROK TUNNEL & SERVER STARTUP
# ==========================================
if __name__ == "__main__":
    # 1. Securely read the token from environment variables
    # (In Kaggle: Set this in the "Secrets" tab. In Colab: Use userdata.get('NGROK_AUTH_TOKEN'))
    NGROK_AUTH_TOKEN = os.environ.get("NGROK_AUTH_TOKEN")
    
    if not NGROK_AUTH_TOKEN or NGROK_AUTH_TOKEN == "YOUR_NGROK_AUTH_TOKEN_HERE":
        logger.error("❌ NGROK_AUTH_TOKEN is missing! Please set it in your environment variables.")
        raise ValueError("Missing Ngrok Auth Token. Check your environment variables.")
        
    logger.info("🔑 Authenticating with Ngrok...")
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)
    
    # 2. Create a public tunnel to port 8000
    logger.info("🌐 Starting Ngrok tunnel on port 8000...")
    public_url = ngrok.connect(8000)
    
    logger.info("\n" + "="*60)
    logger.info("🌐 NGROK TUNNEL ACTIVE!")
    logger.info(f"👉 COPY THIS URL TO YOUR FRONTEND (app.js):")
    logger.info(f"   {public_url}/api/generate")
    logger.info("="*60 + "\n")

    # 3. Start the FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8000)
